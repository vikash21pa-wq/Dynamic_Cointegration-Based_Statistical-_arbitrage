"""
Unit tests for Exchange Lot Sizing, Step Size Precision, and Minimum Notional Limits.
"""

import pytest
import shutil
from pathlib import Path
from src.paper_trader import PaperTradingEngine, BINANCE_FUTURES_RULES, SymbolRules


@pytest.fixture
def temp_results_dir(tmp_path):
    d = tmp_path / "results"
    d.mkdir(parents=True, exist_ok=True)
    yield d
    shutil.rmtree(tmp_path, ignore_errors=True)


def test_binance_rules_registered():
    """Verify universe symbols are present in BINANCE_FUTURES_RULES with valid step sizes."""
    expected_symbols = [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
        "ADAUSDT", "DOGEUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT"
    ]
    for sym in expected_symbols:
        assert sym in BINANCE_FUTURES_RULES
        rule = BINANCE_FUTURES_RULES[sym]
        assert rule.step_size > 0
        assert rule.min_qty > 0
        assert rule.min_notional >= 5.0
        assert rule.qty_precision >= 0


def test_step_size_flooring(temp_results_dir):
    """Test that quantities are floored to step sizes and not rounded up."""
    engine = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        results_dir=temp_results_dir,
        recover_state=False
    )

    # BTCUSDT: step_size=0.001, prec=3
    # 0.021389417 should floor to 0.021
    qty, err = engine.round_lot_size("BTCUSDT", 0.021389417, price=60000.0)
    assert err is None
    assert qty == 0.021

    # 0.0019999 should floor to 0.001
    qty, err = engine.round_lot_size("BTCUSDT", 0.0019999, price=60000.0)
    assert err is None
    assert qty == 0.001

    # DOGEUSDT: step_size=1.0, prec=0
    # 123.78 should floor to 123.0
    qty, err = engine.round_lot_size("DOGEUSDT", 123.78, price=0.15)
    assert err is None
    assert qty == 123.0

    # SOLUSDT: step_size=0.01, prec=2
    # 5.6789 should floor to 5.67
    qty, err = engine.round_lot_size("SOLUSDT", 5.6789, price=150.0)
    assert err is None
    assert qty == 5.67

    # XRPUSDT: step_size=0.1, prec=1
    # 45.98 should floor to 45.9
    qty, err = engine.round_lot_size("XRPUSDT", 45.98, price=0.60)
    assert err is None
    assert qty == 45.9


def test_min_notional_rejection(temp_results_dir):
    """Orders with notional value under $5.00 must be rejected."""
    engine = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        results_dir=temp_results_dir,
        recover_state=False
    )

    # 0.001 BTC at $3,000 = $3.00 (< $5.00)
    qty, err = engine.round_lot_size("BTCUSDT", 0.001, price=3000.0)
    assert qty == 0.0
    assert err is not None
    assert "below minNotional" in err

    # 10 DOGE at $0.15 = $1.50 (< $5.00)
    qty, err = engine.round_lot_size("DOGEUSDT", 10.0, price=0.15)
    assert qty == 0.0
    assert err is not None
    assert "below minNotional" in err

    # 50 DOGE at $0.15 = $7.50 (>= $5.00)
    qty, err = engine.round_lot_size("DOGEUSDT", 50.0, price=0.15)
    assert qty == 50.0
    assert err is None


def test_min_qty_rejection(temp_results_dir):
    """Quantities below min_qty (after flooring) must be rejected."""
    engine = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        results_dir=temp_results_dir,
        recover_state=False
    )

    # 0.0005 BTC (< 0.001 min_qty)
    qty, err = engine.round_lot_size("BTCUSDT", 0.0005, price=65000.0)
    assert qty == 0.0
    assert err is not None
    assert "below exchange minQty" in err

    # 0.4 DOGE (< 1.0 min_qty)
    qty, err = engine.round_lot_size("DOGEUSDT", 0.4, price=100.0)
    assert qty == 0.0
    assert err is not None
    assert "below exchange minQty" in err


def test_order_rejection_insufficient_capital(temp_results_dir):
    """Engine must reject opening positions if allocation is too small to meet $5 min notional."""
    # initial_balance = $50, allocation_pct = 0.05 -> budget = $2.50 (< $5.00 per leg)
    engine = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=50.0,
        allocation_pct=0.05,
        results_dir=temp_results_dir,
        recover_state=False
    )
    engine.rolling_mean = 0.0
    engine.rolling_std = 0.01

    # Try opening position: gross budget is $2.50, legs will be ~$1.15 each (< $5.00)
    success = engine._open_spread_position(1, price_a=60000.0, price_b=3000.0, timestamp_str="2026-03-01 10:00:00")
    assert success is False
    assert engine.current_position_state == 0
    assert len(engine.account.positions) == 0


def test_order_execution_compliant_sizing(temp_results_dir):
    """Engine must successfully open spread with properly rounded step sizes."""
    engine = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=10000.0,
        allocation_pct=0.10,  # $1,000 budget
        results_dir=temp_results_dir,
        recover_state=False
    )
    engine.alpha = 0.0
    engine.beta = 1.0
    engine.rolling_mean = 0.0
    engine.rolling_std = 0.01

    # Budget $1000 -> $500 for BTC, $500 for ETH
    # BTC at $60,000 -> 500 / 60000 = 0.008333... -> 0.008 BTC
    # ETH at $3,000 -> 500 / 3000 = 0.16666... -> 0.166 ETH
    success = engine._open_spread_position(1, price_a=60000.0, price_b=3000.0, timestamp_str="2026-03-01 10:00:00")
    assert success is True
    assert engine.current_position_state == 1

    pos_a = engine.account.positions["BTCUSDT"]
    pos_b = engine.account.positions["ETHUSDT"]

    assert pos_a.contracts == 0.008
    assert pos_b.contracts == 0.166
    assert pos_a.notional >= 5.0
    assert pos_b.notional >= 5.0


def test_process_tick_rejected_order_action(temp_results_dir):
    """When an entry signal occurs but lot sizing fails, snapshot records REJECTED_ORDER."""
    engine = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=20.0,
        allocation_pct=0.10,  # $2.00 total budget -> rejected
        entry_threshold=2.0,
        results_dir=temp_results_dir,
        recover_state=False
    )
    engine.rolling_mean = 0.0
    engine.rolling_std = 0.01
    engine.alpha = 0.0
    engine.beta = 1.0

    # Trigger Z <= -2.0 entry condition:
    # ln(Pa) - ln(Pb) = spread. Say Pa=60000, Pb=61500 -> ln(60000/61500) = -0.02469 -> Z = -2.47
    snap = engine.process_tick(60000.0, 61500.0, "2026-03-01 10:00:00")
    assert snap["action"] == "REJECTED_ORDER"
    assert "Exchange lot size / minimum notional check failed" in snap["reason"]
    assert engine.current_position_state == 0
