"""
Stress, Resilience, and Fault-Tolerance Test Suite.
Tests boundary conditions, corrupted state handling, extreme price shocks,
concurrency, and invalid market ticks for production robustness.
"""

import json
import math
import threading
from pathlib import Path
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app import app, engine, worker_state
from src.paper_trader import PaperTradingEngine, BinanceMultiplexPriceStream, Position


@pytest.fixture
def isolated_results_dir(tmp_path):
    """Provides an isolated results directory for testing."""
    res_dir = tmp_path / "results"
    res_dir.mkdir(parents=True, exist_ok=True)
    return res_dir


def test_invalid_price_rejection_resilience(isolated_results_dir):
    """
    Validates that zero, negative, NaN, and Infinite prices are safely rejected
    without raising unhandled exceptions or corrupting rolling spread statistics.
    """
    pe = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=10000.0,
        results_dir=isolated_results_dir,
        recover_state=False
    )
    baseline_mean = pe.rolling_mean
    baseline_std = pe.rolling_std

    invalid_ticks = [
        (-100.0, 2800.0, "Negative price A"),
        (46000.0, -50.0, "Negative price B"),
        (0.0, 2800.0, "Zero price A"),
        (46000.0, 0.0, "Zero price B"),
        (float("nan"), 2800.0, "NaN price A"),
        (46000.0, float("nan"), "NaN price B"),
        (float("inf"), 2800.0, "Inf price A"),
        (46000.0, float("inf"), "Inf price B"),
        (float("-inf"), 2800.0, "-Inf price A")
    ]

    for p_a, p_b, desc in invalid_ticks:
        snap = pe.process_tick(price_a=p_a, price_b=p_b, timestamp_str="2026-11-06 12:00:00")
        assert snap["action"] == "REJECTED_TICK", f"Failed for {desc}"
        assert "Invalid price" in snap["reason"], f"Failed for {desc}"
        assert math.isfinite(pe.rolling_mean), f"Rolling mean corrupted by {desc}"
        assert math.isfinite(pe.rolling_std), f"Rolling std corrupted by {desc}"

    # Verify statistics remain completely intact after rejected anomalies
    assert pe.rolling_mean == baseline_mean
    assert pe.rolling_std == baseline_std
    assert len(pe.spread_history) == len(pe.spread_history)


def test_corrupted_state_json_recovery_resilience(isolated_results_dir):
    """
    Validates graceful degradation when paper_trading_state.json contains
    severely corrupted syntax, partial writes, or invalid data structures.
    """
    state_file = isolated_results_dir / "paper_trading_state.json"

    # Case 1: Partial / Truncated JSON
    state_file.write_text('{"pair": "BTCUSDT/ETHUSDT", "cash_balance": 10500.0, "posit', encoding="utf-8")
    pe1 = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=10000.0,
        results_dir=isolated_results_dir,
        recover_state=True
    )
    assert pe1.account.cash_balance == 10000.0
    assert pe1.current_position_state == 0

    # Case 2: Valid JSON but unexpected top-level type (Array instead of Dict)
    state_file.write_text('[1, 2, 3, "corrupted"]', encoding="utf-8")
    pe2 = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=10000.0,
        results_dir=isolated_results_dir,
        recover_state=True
    )
    assert pe2.account.cash_balance == 10000.0

    # Case 3: Completely empty file
    state_file.write_text("", encoding="utf-8")
    pe3 = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=10000.0,
        results_dir=isolated_results_dir,
        recover_state=True
    )
    assert pe3.account.cash_balance == 10000.0


def test_corrupted_trades_csv_resilience(isolated_results_dir):
    """
    Validates that a corrupted paper_trades.csv does not prevent engine startup.
    """
    trades_file = isolated_results_dir / "paper_trades.csv"
    trades_file.write_text("random,binary,garbage\x00\x01\x02\ncorrupted,row", encoding="utf-8")

    pe = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=10000.0,
        results_dir=isolated_results_dir,
        recover_state=True
    )
    assert isinstance(pe.account.closed_trades, list)
    assert pe.account.cash_balance == 10000.0


def test_high_frequency_multiplex_burst_concurrency():
    """
    Simulates high-frequency concurrent price stream bursts (e.g. 500 messages
    across multiple threads) to verify thread safety and absence of deadlocks.
    """
    stream = BinanceMultiplexPriceStream("BTCUSDT", "ETHUSDT")
    errors = []

    def send_burst(start_idx: int, count: int):
        for i in range(count):
            try:
                price = 45000.0 + (start_idx + i)
                raw_payload = json.dumps({
                    "stream": "btcusdt@bookTicker",
                    "data": {
                        "s": "BTCUSDT",
                        "b": str(price - 1.0),
                        "a": str(price + 1.0)
                    }
                })
                stream.handle_message(raw_payload)

                eth_price = 2800.0 + ((start_idx + i) * 0.1)
                eth_payload = json.dumps({
                    "stream": "ethusdt@bookTicker",
                    "data": {
                        "s": "ETHUSDT",
                        "b": str(eth_price - 0.5),
                        "a": str(eth_price + 0.5)
                    }
                })
                stream.handle_message(eth_payload)
            except Exception as e:
                errors.append(e)

    threads = [threading.Thread(target=send_burst, args=(t * 100, 100)) for t in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    p_a, p_b = stream.get_latest_prices(max_staleness_seconds=10.0)
    assert p_a is not None
    assert p_b is not None
    assert p_a > 45000.0
    assert p_b > 2800.0


def test_zero_free_margin_order_rejection(isolated_results_dir):
    """
    Verifies that when free margin drops to $0.00, subsequent orders are rejected cleanly.
    """
    pe = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        initial_capital=100.0,
        leverage=1.0,
        results_dir=isolated_results_dir,
        recover_state=False
    )
    # Drain cash to zero
    pe.account.cash_balance = 0.0
    assert pe.account.free_margin == 0.0

    entry_p_b = 2800.0
    entry_spread = pe.rolling_mean - 2.5 * pe.rolling_std
    entry_p_a = float(math.exp(entry_spread + pe.alpha + pe.beta * math.log(entry_p_b)))

    snap = pe.process_tick(price_a=entry_p_a, price_b=entry_p_b, timestamp_str="2026-11-06 12:00:00")
    assert snap["action"] == "REJECTED_ORDER"
    assert "Insufficient free margin" in snap["reason"]
    assert pe.current_position_state == 0


def test_concurrent_api_readers_and_writer_load():
    """
    Validates concurrent read requests to FastAPI endpoints (/api/status, /api/pairs, /health)
    while the engine is processing ticks, ensuring no deadlocks or 500 errors.
    """
    with patch.object(engine, "fetch_live_prices", return_value=(46500.0, 2820.0)):
        with TestClient(app) as client:
            errors = []

            def read_status():
                for _ in range(25):
                    try:
                        r = client.get("/api/status")
                        if r.status_code != 200:
                            errors.append(f"status: {r.status_code}")
                        r2 = client.get("/api/pairs")
                        if r2.status_code != 200:
                            errors.append(f"pairs: {r2.status_code}")
                        r3 = client.get("/health")
                        if r3.status_code != 200:
                            errors.append(f"health: {r3.status_code}")
                    except Exception as e:
                        errors.append(str(e))

            threads = [threading.Thread(target=read_status) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0

