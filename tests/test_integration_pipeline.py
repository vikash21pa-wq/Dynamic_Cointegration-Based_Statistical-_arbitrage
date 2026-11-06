"""
End-to-End Integration Test Suite for Dynamic Cointegration Statistical Arbitrage.
Verifies the complete pipeline lifecycle across all modules:
  1. Full trade lifecycle: entry, lot rounding, margin allocation, 8h funding, exit convergence, and persistence.
  2. State recovery & reboot persistence across engine restarts.
  3. Web API, autonomous worker, and WebSocket tick broadcasting integration.
  4. Extreme margin shock and automated forced liquidation risk engine.
  5. Dynamic pair switching between cointegrated markets.
"""

import json
import math
from pathlib import Path
import numpy as np
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app import app, engine, worker_state
from src.paper_trader import PaperTradingEngine, PaperAccount, Position


@pytest.fixture
def isolated_results_dir(tmp_path):
    """Provides an isolated directory for test persistence artifacts."""
    results_dir = tmp_path / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    return results_dir


def test_full_arbitrage_trade_lifecycle_integration(isolated_results_dir):
    """
    Integration Test 1: Full Arbitrage Round-Trip Lifecycle
    - Validates intra-candle tick aggregation & 5m bar rollover
    - Validates entry order execution with Binance lot sizing & initial margin locking
    - Validates periodic 8h perpetual funding settlement on boundary
    - Validates exit mean-reversion convergence, margin unlocking, and trade ledger persistence
    - Validates post-restart state recovery from disk
    """
    pe = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=10000.0,
        leverage=5.0,
        allocation_pct=0.10,
        entry_threshold=2.0,
        exit_threshold=0.25,
        candle_minutes=5,
        results_dir=isolated_results_dir,
        recover_state=False
    )
    pe.alpha = 1.4648
    pe.beta = 1.1678
    pe.spread_history = np.random.RandomState(42).normal(0.0, 0.01, pe.zscore_window).tolist()
    pe._update_rolling_statistics()

    # 1. Intra-candle tick aggregation in Bar 1 (12:00:00 - 12:04:59)
    snap1 = pe.process_tick(price_a=46000.0, price_b=2800.0, timestamp_str="2026-11-05 12:00:15")
    assert snap1["ticks_in_candle"] == 1
    assert snap1["position_state"] == 0

    snap2 = pe.process_tick(price_a=46100.0, price_b=2795.0, timestamp_str="2026-11-05 12:02:30")
    assert snap2["ticks_in_candle"] == 2
    assert snap2["candle_closed"] is False

    # 2. Advance to Bar 2 (12:05:00) -> Triggers Bar 1 rollover
    snap3 = pe.process_tick(price_a=46050.0, price_b=2800.0, timestamp_str="2026-11-05 12:05:00")
    assert snap3["candle_closed"] is True
    assert pe.last_completed_candle is not None
    assert pe.last_completed_candle.ticks == 2

    # 3. Simulate Entry Signal: Spread undervaluation -> Z-score <= -2.0
    # Dynamically derive Asset A price to achieve target entry Z = -2.5
    entry_p_b = 2800.0
    entry_spread = pe.rolling_mean - 2.5 * pe.rolling_std
    entry_p_a = float(math.exp(entry_spread + pe.alpha + pe.beta * math.log(entry_p_b)))
    snap_entry = pe.process_tick(price_a=entry_p_a, price_b=entry_p_b, timestamp_str="2026-11-05 12:06:00")

    assert snap_entry["action"] == "OPEN_LONG_SPREAD"
    assert snap_entry["position_state"] == 1
    assert pe.current_position_state == 1
    assert len(pe.account.positions) == 2

    # Check exchange lot size compliance & margin lock
    pos_btc = pe.account.positions["BTCUSDT"]
    pos_eth = pe.account.positions["ETHUSDT"]
    assert pos_btc.side == "LONG"
    assert pos_eth.side == "SHORT"
    assert pos_btc.contracts >= 0.001
    assert pos_eth.contracts >= 0.001
    assert snap_entry["initial_margin_locked"] > 0
    assert snap_entry["free_margin"] == pytest.approx(snap_entry["cash_balance"] - snap_entry["initial_margin_locked"], abs=0.1)

    # 4. Cross 8-Hour Funding Boundary (e.g. 16:00:00 UTC) while holding position (Z = -1.2)
    hold_p_b = 2800.0
    hold_spread = pe.rolling_mean - 1.2 * pe.rolling_std
    hold_p_a = float(math.exp(hold_spread + pe.alpha + pe.beta * math.log(hold_p_b)))
    mock_funding_rates = {"BTCUSDT": 0.0002, "ETHUSDT": 0.0001}
    with patch.object(pe, "fetch_live_funding_rates", return_value=mock_funding_rates):
        snap_funding = pe.process_tick(
            price_a=hold_p_a,
            price_b=hold_p_b,
            timestamp_str="2026-11-05 16:00:00"
        )
    assert snap_funding["funding_settled"] is True
    assert snap_funding["total_funding_paid"] != 0.0
    assert snap_funding["position_state"] == 1
    assert (isolated_results_dir / "paper_funding.csv").exists()

    # 5. Simulate Mean Reversion Convergence Exit (Z-score >= -0.25)
    # Target spread = rolling_mean -> price_a = exp(rolling_mean + alpha + beta*ln(price_b))
    exit_p_b = 2800.0
    exit_spread = pe.rolling_mean
    exit_p_a = float(math.exp(exit_spread + pe.alpha + pe.beta * math.log(exit_p_b)))
    snap_exit = pe.process_tick(price_a=exit_p_a, price_b=exit_p_b, timestamp_str="2026-11-05 16:10:00")

    assert snap_exit["action"] == "CLOSE_SPREAD"
    assert snap_exit["position_state"] == 0
    assert pe.current_position_state == 0
    assert len(pe.account.positions) == 0
    assert snap_exit["initial_margin_locked"] == 0.0
    assert snap_exit["free_margin"] == pytest.approx(snap_exit["cash_balance"], abs=0.1)
    assert len(pe.account.closed_trades) == 1
    assert (isolated_results_dir / "paper_trades.csv").exists()

    # 6. Reboot Recovery Verification
    # Instantiate fresh engine with recover_state=True targeting the same isolated directory
    pe_recovered = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=10000.0,
        results_dir=isolated_results_dir,
        recover_state=True
    )
    assert pe_recovered.current_position_state == 0
    assert len(pe_recovered.account.positions) == 0
    assert len(pe_recovered.account.closed_trades) == 1
    assert len(pe_recovered.account.funding_history) >= 2
    assert pe_recovered.account.cash_balance == pytest.approx(pe.account.cash_balance, rel=1e-5)
    assert pe_recovered.account.realized_pnl == pytest.approx(pe.account.realized_pnl, rel=1e-5)


def test_margin_shock_and_liquidation_integration(isolated_results_dir):
    """
    Integration Test 2: Risk Management & Emergency Forced Liquidation
    - Enters leveraged position at 5x
    - Injects severe adverse market shock causing total_equity < maintenance_margin
    - Verifies automated liquidation execution and risk isolation
    """
    pe = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=200.0,
        leverage=5.0,
        allocation_pct=1.0,  # Full margin commitment
        entry_threshold=2.0,
        exit_threshold=0.25,
        results_dir=isolated_results_dir,
        recover_state=False
    )
    pe.alpha = 1.4648
    pe.beta = 1.1678
    pe.spread_history = np.random.RandomState(42).normal(0.0, 0.01, pe.zscore_window).tolist()
    pe._update_rolling_statistics()

    # Enter Long Spread: Buy BTC @ 40,000, Sell ETH @ 3,000 (Z-score <= -2.0)
    pe.process_tick(price_a=40000.0, price_b=3000.0, timestamp_str="2026-11-05 10:00:00")
    assert pe.current_position_state == 1
    assert len(pe.account.positions) == 2

    # Severe adverse market crash on Long leg (BTC plunges to $1,000 while ETH surges to $20,000)
    # Causing massive negative equity far below maintenance margin requirement
    snap_shock = pe.process_tick(price_a=1000.0, price_b=20000.0, timestamp_str="2026-11-05 10:01:00")

    assert snap_shock["action"] == "LIQUIDATION"
    assert "Forced Liquidation" in snap_shock["reason"]
    assert pe.current_position_state == 0
    assert len(pe.account.positions) == 0
    assert len(pe.account.closed_trades) == 1
    assert pe.account.closed_trades[0]["exit_reason"].startswith("Forced Liquidation")


def test_web_api_and_websocket_integration():
    """
    Integration Test 3: Web Application & REST/WebSocket Live Integration
    - Tests server health & diagnostic status
    - Verifies real-time manual tick injection
    - Verifies WebSocket tick push and dynamic pair switching
    """
    with patch.object(engine, "fetch_live_prices", return_value=(47000.0, 2850.0)):
        with TestClient(app) as client:
            # 1. Health check
            res_health = client.get("/health")
            assert res_health.status_code == 200
            assert res_health.json()["status"] == "ok"

            # 2. Worker diagnostic status
            res_worker = client.get("/api/worker")
            assert res_worker.status_code == 200
            worker_data = res_worker.json()
            assert "feed_source" in worker_data
            assert "stream_connected" in worker_data

            # 3. Available universe pairs
            res_pairs = client.get("/api/pairs")
            assert res_pairs.status_code == 200
            pairs_info = res_pairs.json()
            assert "pairs" in pairs_info
            assert any(p["pair"] == "BTCUSDT/ETHUSDT" for p in pairs_info["pairs"])

            # 4. Inject live market tick via worker endpoint
            res_tick = client.post("/api/worker/tick", json={"price_a": 46800.0, "price_b": 2840.0})
            assert res_tick.status_code == 200
            tick_snap = res_tick.json()
            assert tick_snap["pair"] == engine.pair_name
            assert tick_snap["price_a"] == 46800.0
            assert tick_snap["price_b"] == 2840.0

            # 5. Connect WebSocket tick listener
            with client.websocket_connect("/ws/ticks") as ws:
                initial_tick = ws.receive_json()
                assert "pair" in initial_tick
                assert "zscore" in initial_tick

                # Inject tick and verify pushed to WebSocket client
                client.post("/api/worker/tick", json={"price_a": 46900.0, "price_b": 2845.0})
                broadcast_tick = ws.receive_json()
                assert broadcast_tick["price_a"] == 46900.0

            # 6. Switch pair to SOLUSDT/AVAXUSDT and verify API state
            res_switch = client.post("/api/pair", json={"pair": "SOLUSDT/AVAXUSDT"})
            assert res_switch.status_code == 200
            assert res_switch.json()["pair"] == "SOLUSDT/AVAXUSDT"

            res_status = client.get("/api/status")
            assert res_status.status_code == 200
            assert res_status.json()["pair"] == "SOLUSDT/AVAXUSDT"

            res_history = client.get("/api/history")
            assert res_history.status_code == 200
            assert "spreads" in res_history.json()

            # Restore baseline pair
            client.post("/api/pair", json={"pair": "BTCUSDT/ETHUSDT"})
            assert engine.pair_name == "BTCUSDT/ETHUSDT"


def test_multi_candle_walk_forward_integration(isolated_results_dir):
    """
    Integration Test 4: Multi-Candle Intraday Walk-Forward Simulation
    - Walks forward through 6 sequential 5-minute bars (30 minutes)
    - Verifies stability of rolling equilibrium parameters across bars
    """
    pe = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=10000.0,
        zscore_window=30,
        candle_minutes=5,
        results_dir=isolated_results_dir,
        recover_state=False
    )
    pe.alpha = 1.4648
    pe.beta = 1.1678
    pe.spread_history = [0.0] * 30
    pe._update_rolling_statistics()

    initial_mean = pe.rolling_mean
    initial_std = pe.rolling_std

    # Walk forward across 6 5-minute bars (30 ticks, 1 tick every minute)
    for minute in range(30):
        bar_idx = minute // 5
        minute_in_bar = minute % 5
        ts = f"2026-11-05 10:{minute:02d}:00"

        # Stable random walk around market equilibrium
        p_a = 46000.0 + (minute * 5.0)
        p_b = 2800.0 + (minute * 0.3)
        snap = pe.process_tick(price_a=p_a, price_b=p_b, timestamp_str=ts)

        if minute_in_bar == 0 and minute > 0:
            assert snap["candle_closed"] is True

    # After 30 minutes, 6 candles closed, rolling statistics adjusted stably
    assert len(pe.spread_history) == 30
    assert abs(pe.rolling_mean - initial_mean) < 0.05
    assert pe.rolling_std > 0.0

