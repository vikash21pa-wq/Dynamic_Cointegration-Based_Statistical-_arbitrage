"""
Unit tests for 8-Hour Perpetual Funding Rate Settlement Mechanism.
Verifies funding payment calculations, periodic 8-hour boundary detection (00:00, 08:00, 16:00 UTC),
carry drag accounting, and persistence across server restarts.
"""

import shutil
import pytest
import pandas as pd
from pathlib import Path
from src.paper_trader import PaperTradingEngine, PaperAccount, Position


@pytest.fixture
def temp_results_dir(tmp_path):
    d = tmp_path / "results"
    d.mkdir(parents=True, exist_ok=True)
    yield d
    shutil.rmtree(tmp_path, ignore_errors=True)


def test_apply_funding_payment_long_and_short():
    """Long positions pay positive funding; short positions receive positive funding."""
    account = PaperAccount(initial_balance=10000.0)

    # 1. Long 0.1 BTC at $60,000 with 0.01% (0.0001) positive funding rate
    # Notional = $6,000 -> Payment = $0.60
    # Long pays positive funding: cash decreases by $0.60
    res_long = account.apply_funding_payment(
        symbol="BTCUSDT",
        side="LONG",
        contracts=0.1,
        mark_price=60000.0,
        funding_rate=0.0001,
        timestamp_str="2026-03-01 08:00:00"
    )
    assert res_long["payment"] == pytest.approx(0.60, abs=1e-4)
    assert res_long["cash_change"] == pytest.approx(-0.60, abs=1e-4)
    assert account.cash_balance == pytest.approx(9999.40, abs=1e-4)
    assert account.total_funding_paid == pytest.approx(0.60, abs=1e-4)

    # 2. Short 2.0 ETH at $3,000 with 0.01% (0.0001) positive funding rate
    # Notional = $6,000 -> Payment = $0.60
    # Short receives positive funding: cash increases by $0.60
    res_short = account.apply_funding_payment(
        symbol="ETHUSDT",
        side="SHORT",
        contracts=2.0,
        mark_price=3000.0,
        funding_rate=0.0001,
        timestamp_str="2026-03-01 08:00:00"
    )
    assert res_short["payment"] == pytest.approx(0.60, abs=1e-4)
    assert res_short["cash_change"] == pytest.approx(0.60, abs=1e-4)
    assert account.cash_balance == pytest.approx(10000.00, abs=1e-4)
    assert account.total_funding_paid == pytest.approx(0.00, abs=1e-4)


def test_apply_funding_payment_negative_rate():
    """Negative funding rate inverts cashflow (Longs receive, Shorts pay)."""
    account = PaperAccount(initial_balance=10000.0)

    # Long 0.1 BTC at $60,000 with -0.02% (-0.0002) negative funding rate
    # Notional = $6,000 -> Gross payment = -$1.20
    # Long receives: cash increases by $1.20
    res = account.apply_funding_payment(
        symbol="BTCUSDT",
        side="LONG",
        contracts=0.1,
        mark_price=60000.0,
        funding_rate=-0.0002,
        timestamp_str="2026-03-01 08:00:00"
    )
    assert res["cash_change"] == pytest.approx(1.20, abs=1e-4)
    assert account.cash_balance == pytest.approx(10001.20, abs=1e-4)
    assert account.total_funding_paid == pytest.approx(-1.20, abs=1e-4)


def test_periodic_8h_funding_settlement_on_boundary(temp_results_dir):
    """
    Crossing the 8-hour UTC boundary (00:00, 08:00, 16:00) must settle funding
    fees for all open positions.
    """
    engine = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=10000.0,
        allocation_pct=0.10,
        entry_threshold=10.0,
        exit_threshold=-10.0,
        results_dir=temp_results_dir,
        recover_state=False
    )
    engine.alpha = 0.0
    engine.beta = 1.0
    engine.rolling_mean = 0.0
    engine.rolling_std = 0.01
    engine.spread_history = [0.0] * engine.zscore_window

    # Ingest baseline tick at 07:50 UTC to initialize engine funding period
    engine.process_tick(60000.0, 60000.0, "2026-03-01 07:50:00")

    # Open position: Long spread at 07:52 UTC (Buy BTC, Sell ETH)
    engine._open_spread_position(1, price_a=60000.0, price_b=3000.0, timestamp_str="2026-03-01 07:52:00")
    assert engine.current_position_state == 1
    assert len(engine.account.positions) == 2

    # Ingest tick at 07:55:00 UTC (same 8h window -> no funding settlement)
    snap1 = engine.process_tick(60000.0, 60000.0, "2026-03-01 07:55:00")
    assert snap1["funding_settled"] is False
    assert len(engine.account.funding_history) == 0

    # Ingest tick at 08:00:05 UTC (CROSSES 08:00 BOUNDARY!)
    # Both open positions must settle 8-hour funding!
    snap2 = engine.process_tick(60000.0, 60000.0, "2026-03-01 08:00:05")
    assert snap2["funding_settled"] is True
    assert snap2["action"] == "FUNDING_SETTLED"
    assert len(engine.account.funding_history) == 2
    assert (temp_results_dir / "paper_funding.csv").exists()


def test_no_funding_when_flat(temp_results_dir):
    """Crossing 8-hour boundary with no open positions does not deduct funding."""
    engine = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=10000.0,
        entry_threshold=999.0,  # Ensure completely flat
        results_dir=temp_results_dir,
        recover_state=False
    )
    engine.alpha = 0.0
    engine.beta = 1.0
    engine.rolling_mean = 0.0
    engine.rolling_std = 0.01
    engine.spread_history = [0.0] * engine.zscore_window

    snap1 = engine.process_tick(60000.0, 60000.0, "2026-03-01 07:55:00")
    assert snap1["position_state"] == 0
    assert len(engine.account.positions) == 0

    snap2 = engine.process_tick(60000.0, 60000.0, "2026-03-01 08:00:05")

    assert snap2["funding_settled"] is False
    assert len(engine.account.funding_history) == 0
    assert engine.account.total_funding_paid == 0.0


def test_funding_history_persistence_and_recovery(temp_results_dir):
    """Funding ledger and cumulative carry drag must persist and re-hydrate on restart."""
    engine1 = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=10000.0,
        allocation_pct=0.10,
        entry_threshold=10.0,
        exit_threshold=-10.0,
        results_dir=temp_results_dir,
        recover_state=False
    )
    engine1.alpha = 0.0
    engine1.beta = 1.0

    # Initialize at 07:50:00
    engine1.process_tick(60000.0, 60000.0, "2026-03-01 07:50:00")
    engine1._open_spread_position(1, price_a=60000.0, price_b=3000.0, timestamp_str="2026-03-01 07:52:00")

    # Trigger funding settlement at 08:00:05
    engine1.process_tick(60000.0, 60000.0, "2026-03-01 08:00:05")

    funding_records = len(engine1.account.funding_history)
    assert funding_records == 2
    total_funding = engine1.account.total_funding_paid

    # Reboot engine with recover_state=True
    engine2 = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        results_dir=temp_results_dir,
        recover_state=True
    )
    assert len(engine2.account.funding_history) == funding_records
    assert engine2.account.total_funding_paid == pytest.approx(total_funding, abs=1e-4)
    assert engine2.last_funding_period_id == engine1.last_funding_period_id


def test_fetch_live_funding_rates_fallback():
    """Live API query falls back to valid default float funding rates when needed."""
    engine = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        recover_state=False
    )
    rates = engine.fetch_live_funding_rates()
    assert "BTCUSDT" in rates
    assert "ETHUSDT" in rates
    assert isinstance(rates["BTCUSDT"], float)
    assert isinstance(rates["ETHUSDT"], float)
