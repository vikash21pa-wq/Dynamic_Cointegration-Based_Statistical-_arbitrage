"""
Unit tests for PaperTradingEngine State Recovery & Position Persistence.
Verifies re-hydration of open positions, cash balance, realized PnL,
and historical closed trades across server restarts.
"""

import json
import numpy as np
import pytest
import pandas as pd
from src.paper_trader import PaperTradingEngine, Position


def test_recovery_from_clean_state(tmp_path):
    """Verifies that engine boots cleanly with defaults when no state file exists."""
    engine = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=10000.0,
        results_dir=tmp_path,
        recover_state=True
    )
    assert engine.account.cash_balance == 10000.0
    assert engine.account.realized_pnl == 0.0
    assert engine.current_position_state == 0
    assert len(engine.account.positions) == 0
    assert len(engine.account.closed_trades) == 0


def test_recovery_closed_trades_from_csv(tmp_path):
    """Verifies that historical closed trades in CSV are re-hydrated into account."""
    trades_data = [
        {
            "pair": "BTCUSDT/ETHUSDT",
            "direction": "LONG_SPREAD",
            "entry_time": "2024-01-01 10:00:00",
            "exit_time": "2024-01-01 11:30:00",
            "exit_reason": "Mean convergence",
            "holding_ticks": 18,
            "gross_pnl": 125.50,
            "fees_paid": 5.20,
            "net_pnl": 120.30,
            "account_equity": 10120.30
        }
    ]
    trades_df = pd.DataFrame(trades_data)
    trades_df.to_csv(tmp_path / "paper_trades.csv", index=False)

    engine = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=10000.0,
        results_dir=tmp_path,
        recover_state=True
    )
    assert len(engine.account.closed_trades) == 1
    assert engine.account.closed_trades[0]["direction"] == "LONG_SPREAD"
    assert engine.account.closed_trades[0]["net_pnl"] == 120.30


def test_recovery_open_position_and_lifecycle(tmp_path):
    """
    Full lifecycle test:
    1. Engine 1 opens an active LONG_SPREAD position via natural Z-score threshold entry.
    2. Simulated server crash/shutdown occurs.
    3. Engine 2 boots up and recovers the open positions, contract sizes, and entry prices.
    4. Next tick triggers mean convergence exit; Engine 2 liquidates recovered legs correctly.
    """
    engine1 = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=10000.0,
        results_dir=tmp_path,
        recover_state=False
    )

    # Calculate price that creates Z = -2.2 (entry condition: Z <= -2.0)
    p_b_entry = 2800.0
    spread_entry = engine1.rolling_mean - 2.2 * engine1.rolling_std
    p_a_entry = float(np.exp(engine1.alpha + engine1.beta * np.log(p_b_entry) + spread_entry))

    # Process entry tick to trigger OPEN_LONG_SPREAD and persist state
    snap1 = engine1.process_tick(price_a=p_a_entry, price_b=p_b_entry, timestamp_str="2024-01-01 12:00:00")
    assert snap1["action"] == "OPEN_LONG_SPREAD"
    assert snap1["position_state"] == 1
    assert "BTCUSDT" in engine1.account.positions
    assert "ETHUSDT" in engine1.account.positions

    contracts_a = engine1.account.positions["BTCUSDT"].contracts
    contracts_b = engine1.account.positions["ETHUSDT"].contracts
    entry_p_a = engine1.account.positions["BTCUSDT"].entry_price
    entry_p_b = engine1.account.positions["ETHUSDT"].entry_price
    cash_after_open = engine1.account.cash_balance

    # Verify state file was saved with positions
    state_file = tmp_path / "paper_trading_state.json"
    assert state_file.exists()
    with open(state_file, "r") as f:
        saved_json = json.load(f)
    assert "positions" in saved_json
    assert "BTCUSDT" in saved_json["positions"]
    assert "ETHUSDT" in saved_json["positions"]

    # --- SIMULATE SERVER REBOOT ---
    del engine1

    engine2 = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=10000.0,
        results_dir=tmp_path,
        recover_state=True
    )

    # Verify Engine 2 successfully restored Engine 1's open trade state
    assert engine2.current_position_state == 1
    assert engine2.account.cash_balance == pytest.approx(cash_after_open, rel=1e-5)
    assert "BTCUSDT" in engine2.account.positions
    assert "ETHUSDT" in engine2.account.positions
    assert engine2.account.positions["BTCUSDT"].contracts == pytest.approx(contracts_a, rel=1e-5)
    assert engine2.account.positions["ETHUSDT"].contracts == pytest.approx(contracts_b, rel=1e-5)
    assert engine2.account.positions["BTCUSDT"].entry_price == pytest.approx(entry_p_a, rel=1e-5)
    assert engine2.account.positions["ETHUSDT"].entry_price == pytest.approx(entry_p_b, rel=1e-5)
    assert engine2.account.positions["BTCUSDT"].side == "LONG"
    assert engine2.account.positions["ETHUSDT"].side == "SHORT"

    # Now feed a tick that triggers exit condition (spread convergence: Z = 0 >= -0.25)
    p_b_exit = 2800.0
    spread_exit = engine2.rolling_mean
    p_a_exit = float(np.exp(engine2.alpha + engine2.beta * np.log(p_b_exit) + spread_exit))
    snap2 = engine2.process_tick(price_a=p_a_exit, price_b=p_b_exit, timestamp_str="2024-01-01 12:05:00")

    # Engine 2 should have closed the recovered position cleanly
    assert snap2["action"] == "CLOSE_SPREAD"
    assert engine2.current_position_state == 0
    assert len(engine2.account.positions) == 0
    assert len(engine2.account.closed_trades) == 1
    assert engine2.account.closed_trades[0]["direction"] == "LONG_SPREAD"


def test_recovery_disabled_when_flag_false(tmp_path):
    """Verifies that recover_state=False ignores disk state and creates a fresh portfolio."""
    state_file = tmp_path / "paper_trading_state.json"
    dummy_state = {
        "pair": "BTCUSDT/ETHUSDT",
        "cash_balance": 15000.0,
        "position_state": 1,
        "realized_pnl": 5000.0,
        "fees_paid": 50.0,
        "positions": {}
    }
    with open(state_file, "w") as f:
        json.dump(dummy_state, f)

    engine = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=10000.0,
        results_dir=tmp_path,
        recover_state=False
    )
    assert engine.account.cash_balance == 10000.0
    assert engine.current_position_state == 0
    assert engine.account.realized_pnl == 0.0
