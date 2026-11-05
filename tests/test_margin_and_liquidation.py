"""
Unit tests for Margin Allocation & Liquidation Risk Engine.
Verifies initial margin locking, free margin enforcement, maintenance margin monitoring,
and forced liquidation state machine execution.
"""

import shutil
import pytest
from pathlib import Path
from src.paper_trader import PaperTradingEngine, PaperAccount, Position


@pytest.fixture
def temp_results_dir(tmp_path):
    d = tmp_path / "results"
    d.mkdir(parents=True, exist_ok=True)
    yield d
    shutil.rmtree(tmp_path, ignore_errors=True)


def test_initial_margin_locked_at_leverage():
    """At 5x leverage, 20% (1/5) of total position notional must be locked as initial margin."""
    account = PaperAccount(initial_balance=10000.0, leverage=5.0)
    assert account.initial_margin_locked == 0.0
    assert account.free_margin == 10000.0

    # Add 2 open legs of $2,500 each ($5,000 gross notional)
    account.positions["BTCUSDT"] = Position(
        symbol="BTCUSDT",
        side="LONG",
        contracts=0.05,
        entry_price=50000.0,
        notional=2500.0,
        entry_time="2026-03-01 12:00:00"
    )
    account.positions["ETHUSDT"] = Position(
        symbol="ETHUSDT",
        side="SHORT",
        contracts=1.0,
        entry_price=2500.0,
        notional=2500.0,
        entry_time="2026-03-01 12:00:00"
    )

    # 5000 / 5 = 1000 locked margin (20%)
    assert account.initial_margin_locked == 1000.0
    assert account.free_margin == 9000.0


def test_order_rejection_insufficient_free_margin(temp_results_dir):
    """Engine must reject opening positions if free margin cannot cover initial margin."""
    engine = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=500.0,
        allocation_pct=0.80,  # $400 budget
        results_dir=temp_results_dir,
        recover_state=False,
        leverage=1.0
    )
    # Drain free margin by setting cash_balance very low
    engine.account.cash_balance = 10.0
    engine.rolling_mean = 0.0
    engine.rolling_std = 0.01

    # Order requires ~$8 in notional per leg (> $5 min notional), but cash balance is only $10
    # and allocation is 80% ($8 total budget < $10 required notional per leg)
    success = engine._open_spread_position(1, price_a=60000.0, price_b=3000.0, timestamp_str="2026-03-01 12:00:00")
    assert success is False
    assert engine.current_position_state == 0
    assert len(engine.account.positions) == 0


def test_maintenance_margin_and_margin_ratio():
    """Validates maintenance margin calculation and margin ratio."""
    account = PaperAccount(
        initial_balance=1000.0,
        leverage=5.0,
        maintenance_margin_pct=0.05  # 5% maintenance margin
    )
    account.positions["BTCUSDT"] = Position(
        symbol="BTCUSDT",
        side="LONG",
        contracts=0.02,
        entry_price=50000.0,
        notional=1000.0,
        entry_time="2026-03-01 12:00:00"
    )

    # Entry notional = 1000 -> Maintenance margin = 1000 * 0.05 = $50.00
    prices = {"BTCUSDT": 50000.0}
    assert account.get_maintenance_margin(prices) == 50.0

    # Total equity = $1000 -> Margin ratio = 50 / 1000 = 5% (0.05)
    assert account.get_margin_ratio(prices) == 0.05
    assert account.is_liquidatable(prices) is False


def test_forced_liquidation_trigger(temp_results_dir):
    """
    When total equity drops below maintenance margin, the engine must
    execute a forced liquidation, liquidate all positions, and emit action='LIQUIDATION'.
    """
    engine = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=1000.0,
        allocation_pct=1.0,
        leverage=5.0,
        maintenance_margin_pct=0.05,
        results_dir=temp_results_dir,
        recover_state=False
    )
    engine.alpha = 0.0
    engine.beta = 1.0
    engine.rolling_mean = 0.0
    engine.rolling_std = 0.01

    # 1. Open a LONG spread: Buy BTC at 60,000, Sell ETH at 3,000
    # $1000 budget -> $500 BTC, $500 ETH -> 0.008 BTC, 0.166 ETH
    success = engine._open_spread_position(1, price_a=60000.0, price_b=3000.0, timestamp_str="2026-03-01 12:00:00")
    assert success is True
    assert engine.current_position_state == 1
    assert engine.account.initial_margin_locked > 0

    # 2. Crash BTC from 60,000 to 1,000 (huge unrealized loss on Long BTC leg)
    # Long leg loss = 0.008 * (1000 - 60000) = -$472.00
    # Total equity drops drastically
    # Let's drop BTC to 100.0: loss = 0.008 * (100 - 60000) = -$479.20
    # ETH shoots up to 10,000: Short leg loss = 0.166 * (3000 - 10000) = -$1,162.00
    # Total unrealized loss = -$1,641.20 -> Total equity < 0 (< maintenance margin!)
    crash_prices = {"BTCUSDT": 100.0, "ETHUSDT": 10000.0}
    assert engine.account.is_liquidatable(crash_prices) is True

    # 3. Process tick with crash prices: Engine must trigger LIQUIDATION
    snap = engine.process_tick(100.0, 10000.0, "2026-03-01 12:05:00")

    assert snap["action"] == "LIQUIDATION"
    assert "Forced Liquidation" in snap["reason"]
    assert engine.current_position_state == 0
    assert len(engine.account.positions) == 0
    assert engine.account.initial_margin_locked == 0.0
    assert snap["initial_margin_locked"] == 0.0
    assert len(engine.account.closed_trades) == 1
    assert "Forced Liquidation" in engine.account.closed_trades[0]["exit_reason"]


def test_margin_telemetry_in_snapshot(temp_results_dir):
    """Snapshot must contain real-time margin metrics and lock margin on entry."""
    engine = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=10000.0,
        leverage=5.0,
        results_dir=temp_results_dir,
        recover_state=False
    )
    # 1. Neutral tick where Z-score is near 0 -> no trade -> margin locked = 0
    engine.alpha = 0.0
    engine.beta = 1.0
    engine.rolling_mean = 0.0
    engine.rolling_std = 0.01

    snap_neutral = engine.process_tick(50000.0, 50000.0, "2026-03-01 12:00:00")
    assert snap_neutral["action"] == "HOLD"
    assert snap_neutral["initial_margin_locked"] == 0.0
    assert snap_neutral["free_margin"] == snap_neutral["cash_balance"]
    assert snap_neutral["leverage"] == 5.0

    # 2. Extreme tick triggering entry: margin must be locked
    snap_entry = engine.process_tick(50000.0, 51500.0, "2026-03-01 12:05:00")
    assert snap_entry["action"] == "OPEN_LONG_SPREAD"
    assert snap_entry["initial_margin_locked"] > 0.0
    assert snap_entry["free_margin"] < snap_entry["cash_balance"]
