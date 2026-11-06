"""
Unit and Integration Test Suite for Delta Exchange.
Verifies:
  1. Delta Exchange configuration and URL routing (India, Global, Testnet).
  2. Delta Exchange data loader and 5m candle parsing.
  3. Delta real-time WebSocket multiplex stream handling and price caching.
  4. Delta contract specifications, lot sizing, and minimum notionals.
  5. Full paper trading round-trip execution using Delta Exchange market specifications.
  6. Live price and funding rate queries for Delta Exchange.
"""

import json
import time
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

from config import delta_config, DeltaConfig
from src.data_loader import DeltaExchangeDataLoader
from src.paper_trader import (
    PaperTradingEngine,
    DeltaMultiplexPriceStream,
    DELTA_FUTURES_RULES,
    SymbolRules
)


@pytest.fixture
def isolated_results_dir(tmp_path):
    results_dir = tmp_path / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    return results_dir


def test_delta_config_and_urls():
    """Validates Delta Exchange configuration and environment URL routing."""
    cfg_india = DeltaConfig(environment="india")
    assert cfg_india.rest_url == "https://api.india.delta.exchange"
    assert cfg_india.ws_url == "wss://socket.india.delta.exchange"

    cfg_global = DeltaConfig(environment="global")
    assert cfg_global.rest_url == "https://api.delta.exchange"
    assert cfg_global.ws_url == "wss://socket.delta.exchange"

    cfg_testnet = DeltaConfig(environment="testnet")
    assert cfg_testnet.rest_url == "https://testnet-api.delta.exchange"
    assert cfg_testnet.ws_url == "wss://testnet-socket.delta.exchange"

    assert "BTCUSD" in cfg_india.universe
    assert "ETHUSD" in cfg_india.universe


def test_delta_futures_lot_sizing_and_rules():
    """Validates contract specifications for Delta perpetual futures universe."""
    required_symbols = ["BTCUSD", "ETHUSD", "SOLUSD", "AVAXUSD", "BNBUSD"]
    for sym in required_symbols:
        assert sym in DELTA_FUTURES_RULES
        rules = DELTA_FUTURES_RULES[sym]
        assert isinstance(rules, SymbolRules)
        assert rules.step_size > 0
        assert rules.min_notional >= 5.0
        assert rules.qty_precision >= 0


def test_delta_multiplex_stream_message_handling():
    """Tests DeltaMultiplexPriceStream parsing of incoming v2/ticker WebSocket payloads."""
    stream = DeltaMultiplexPriceStream("BTCUSD", "ETHUSD")

    # Ingest BTCUSD tick payload
    btc_payload = json.dumps({
        "type": "v2/ticker",
        "symbol": "BTCUSD",
        "mark_price": 75500.5,
        "close": 75500.0,
        "best_bid": 75499.0,
        "best_ask": 75501.0,
        "funding_rate": 0.00015
    })
    stream.handle_message(btc_payload)

    # Ingest ETHUSD tick payload
    eth_payload = json.dumps({
        "type": "v2/ticker",
        "symbol": "ETHUSD",
        "mark_price": 2225.0,
        "close": 2224.5,
        "best_bid": 2224.0,
        "best_ask": 2226.0,
        "funding_rate": 0.00012
    })
    stream.handle_message(eth_payload)

    p_a, p_b = stream.get_latest_prices(max_staleness_seconds=10.0)
    assert p_a == 75500.0  # mid-price of 75499 and 75501
    assert p_b == 2225.0   # mid-price of 2224 and 2226
    assert stream.is_connected is True
    assert stream.funding_rates.get("BTCUSD") == 0.00015
    assert stream.funding_rates.get("ETHUSD") == 0.00012


def test_delta_data_loader_parse(tmp_path):
    """Tests DeltaExchangeDataLoader chunk parsing into standardized DataFrame."""
    loader = DeltaExchangeDataLoader(raw_dir=tmp_path)
    now_sec = int(time.time())
    mock_candles = [
        {"time": now_sec - 600, "open": 75000.0, "high": 75100.0, "low": 74900.0, "close": 75050.0, "volume": 12.5},
        {"time": now_sec - 300, "open": 75050.0, "high": 75200.0, "low": 75000.0, "close": 75150.0, "volume": 15.0}
    ]

    with patch.object(loader, "fetch_candles_chunk", return_value=mock_candles):
        df = loader.download_symbol_history(symbol="BTCUSD", days=1)
        assert len(df) == 2
        assert "timestamp" in df.columns
        assert "datetime" in df.columns
        assert "close" in df.columns
        assert "quote_volume" in df.columns
        assert df["close"].iloc[0] == 75050.0
        assert df["close"].iloc[1] == 75150.0


def test_delta_engine_full_trade_lifecycle(isolated_results_dir):
    """
    Validates end-to-end paper trading lifecycle on Delta Exchange:
    - Delta pair initialization (BTCUSD/ETHUSD)
    - Delta lot sizing and margin locking
    - Live spread Z-score execution
    - Funding settlement and convergence exit
    """
    pe = PaperTradingEngine(
        pair="BTCUSD/ETHUSD",
        initial_capital=10000.0,
        leverage=5.0,
        allocation_pct=0.10,
        entry_threshold=2.0,
        exit_threshold=0.25,
        exchange="delta",
        results_dir=isolated_results_dir,
        recover_state=False
    )
    assert pe.exchange == "delta"
    assert pe.pair_name == "BTCUSD/ETHUSD"
    assert "BTCUSD" in pe.symbol_rules
    assert isinstance(pe.price_stream, DeltaMultiplexPriceStream)

    # Ingest baseline ticks to calibrate
    pe.alpha = 1.4800
    pe.beta = 1.1520
    pe.rolling_mean = 0.0
    pe.rolling_std = 0.01

    # Enter Long Spread (Buy BTCUSD, Sell ETHUSD)
    entry_p_b = 2200.0
    entry_spread = pe.rolling_mean - 2.5 * pe.rolling_std
    entry_p_a = float(2.718281828 ** (entry_spread + pe.alpha + pe.beta * 7.696213))
    snap_entry = pe.process_tick(price_a=entry_p_a, price_b=entry_p_b, timestamp_str="2026-11-06 12:00:00")

    assert snap_entry["action"] == "OPEN_LONG_SPREAD"
    assert snap_entry["position_state"] == 1
    assert snap_entry["exchange"] == "DELTA"
    assert len(pe.account.positions) == 2
    assert "BTCUSD" in pe.account.positions
    assert "ETHUSD" in pe.account.positions

    # Delta funding settlement
    mock_funding = {"BTCUSD": 0.00015, "ETHUSD": 0.00012}
    with patch.object(pe, "fetch_live_funding_rates", return_value=mock_funding):
        snap_funding = pe.process_tick(price_a=entry_p_a, price_b=entry_p_b, timestamp_str="2026-11-06 16:00:00")
    assert snap_funding["funding_settled"] is True

    # Mean convergence exit
    exit_p_b = 2200.0
    exit_spread = pe.rolling_mean
    exit_p_a = float(2.718281828 ** (exit_spread + pe.alpha + pe.beta * 7.696213))
    snap_exit = pe.process_tick(price_a=exit_p_a, price_b=exit_p_b, timestamp_str="2026-11-06 16:05:00")

    assert snap_exit["action"] == "CLOSE_SPREAD"
    assert snap_exit["position_state"] == 0
    assert len(pe.account.closed_trades) == 1
    assert (isolated_results_dir / "paper_trades.csv").exists()


def test_delta_rest_live_price_fallback(isolated_results_dir):
    """Validates that engine correctly fetches live prices and funding rates via Delta REST API."""
    pe = PaperTradingEngine(
        pair="BTCUSD/ETHUSD",
        exchange="delta",
        results_dir=isolated_results_dir,
        recover_state=False
    )
    p_a, p_b = pe.fetch_live_prices()
    assert p_a is not None
    assert p_b is not None
    assert p_a > 10000.0  # BTCUSD price
    assert p_b > 500.0    # ETHUSD price

    rates = pe.fetch_live_funding_rates()
    assert "BTCUSD" in rates
    assert "ETHUSD" in rates
    assert isinstance(rates["BTCUSD"], float)

