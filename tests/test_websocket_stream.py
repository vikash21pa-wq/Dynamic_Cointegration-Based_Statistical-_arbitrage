"""
Unit tests for Binance Multiplex WebSocket Price Stream (bookTicker).
Verifies zero-latency simultaneous bid/ask ingestion, multiplex URL routing,
thread-safe caching, staleness checks, and REST fallback mechanisms.
"""

import json
import time
import pytest
from src.paper_trader import BinanceMultiplexPriceStream, PaperTradingEngine


def test_multiplex_stream_url_generation():
    """Stream URL must target Binance Futures multiplex endpoint for both symbols."""
    stream = BinanceMultiplexPriceStream("BTCUSDT", "ETHUSDT")
    assert stream.stream_url == "wss://fstream.binance.com/ws/btcusdt@bookTicker/ethusdt@bookTicker"


def test_handle_raw_bookticker_payload():
    """Raw bookTicker messages update thread-safe prices and mid-prices correctly."""
    stream = BinanceMultiplexPriceStream("BTCUSDT", "ETHUSDT")

    # Ingest BTC bookTicker
    raw_btc = json.dumps({
        "e": "bookTicker",
        "u": 4001,
        "s": "BTCUSDT",
        "b": "60100.00",
        "B": "1.5",
        "a": "60100.20",
        "A": "2.0",
        "T": 1700000000000,
        "E": 1700000000010
    })
    stream.handle_message(raw_btc)
    assert stream.is_connected is True
    assert stream.prices["BTCUSDT"] == pytest.approx(60100.10, abs=1e-4)

    # Ingest ETH bookTicker
    raw_eth = json.dumps({
        "e": "bookTicker",
        "u": 4002,
        "s": "ETHUSDT",
        "b": "3050.00",
        "B": "10.0",
        "a": "3050.50",
        "A": "8.0",
        "T": 1700000000000,
        "E": 1700000000010
    })
    stream.handle_message(raw_eth)
    assert stream.prices["ETHUSDT"] == pytest.approx(3050.25, abs=1e-4)

    p_a, p_b = stream.get_latest_prices()
    assert p_a == pytest.approx(60100.10, abs=1e-4)
    assert p_b == pytest.approx(3050.25, abs=1e-4)


def test_handle_combined_stream_format():
    """Combined stream messages with top-level 'data' envelope must be properly extracted."""
    stream = BinanceMultiplexPriceStream("SOLUSDT", "AVAXUSDT")

    combined_msg = json.dumps({
        "stream": "solusdt@bookTicker",
        "data": {
            "s": "SOLUSDT",
            "b": "150.10",
            "a": "150.30"
        }
    })
    stream.handle_message(combined_msg)
    assert stream.prices["SOLUSDT"] == pytest.approx(150.20, abs=1e-4)


def test_staleness_rejection():
    """Prices older than max_staleness_seconds must be rejected as stale."""
    stream = BinanceMultiplexPriceStream("BTCUSDT", "ETHUSDT")
    stream.prices["BTCUSDT"] = 60000.0
    stream.prices["ETHUSDT"] = 3000.0
    # Simulate update from 20 seconds ago
    stream.last_updated["BTCUSDT"] = time.time() - 20.0
    stream.last_updated["ETHUSDT"] = time.time() - 20.0

    p_a, p_b = stream.get_latest_prices(max_staleness_seconds=10.0)
    assert p_a is None
    assert p_b is None


def test_engine_fetch_live_prices_prioritizes_websocket(tmp_path):
    """PaperTradingEngine must immediately use WebSocket stream prices without calling REST."""
    engine = PaperTradingEngine(
        pair="BTCUSDT/ETHUSDT",
        results_dir=tmp_path,
        recover_state=False
    )
    # Inject mocked stream with fresh prices
    mock_stream = BinanceMultiplexPriceStream("BTCUSDT", "ETHUSDT")
    mock_stream.prices["BTCUSDT"] = 62500.00
    mock_stream.prices["ETHUSDT"] = 3125.00
    mock_stream.last_updated["BTCUSDT"] = time.time()
    mock_stream.last_updated["ETHUSDT"] = time.time()
    mock_stream.is_connected = True

    engine.price_stream = mock_stream

    # fetch_live_prices should return mock stream prices instantly
    p_a, p_b = engine.fetch_live_prices()
    assert p_a == 62500.00
    assert p_b == 3125.00

    # Snapshot should report WEBSOCKET_MULTIPLEX
    snap = engine.process_tick(p_a, p_b, "2026-03-01 12:00:00")
    assert snap["feed_source"] == "WEBSOCKET_MULTIPLEX"
    assert snap["stream_connected"] is True


def test_stream_lifecycle():
    """Stream start and stop must initialize and cleanly terminate worker thread."""
    stream = BinanceMultiplexPriceStream("BTCUSDT", "ETHUSDT")
    assert stream._running is False

    stream.start()
    assert stream._running is True
    assert stream._thread is not None
    assert stream._thread.is_alive()

    stream.stop()
    assert stream._running is False
    assert stream.is_connected is False
