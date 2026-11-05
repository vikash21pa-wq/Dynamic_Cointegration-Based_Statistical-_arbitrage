"""
Unit tests for Dynamic Trading Pair Switching in Engine and Web API.
Tests engine reconfiguration, alpha/beta parameter recalibration,
WebSocket price stream rebinding, and /api/pairs and /api/pair endpoints.
"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app import app, engine
from src.paper_trader import PaperTradingEngine


@pytest.fixture(scope="module")
def client():
    # Mock Binance network calls so tests run offline and deterministically
    with patch.object(engine, "fetch_live_prices", return_value=(105.0, 35.0)):
        with TestClient(app) as test_client:
            yield test_client
    # Restore default pair at end of test module
    engine.switch_pair("BTCUSDT/ETHUSDT", alpha=1.4648, beta=1.1678)


def test_engine_switch_pair_direct():
    """Verifies that PaperTradingEngine.switch_pair properly reconfigures state."""
    pe = PaperTradingEngine(pair="BTCUSDT/ETHUSDT", initial_capital=10000.0)
    assert pe.pair_name == "BTCUSDT/ETHUSDT"
    assert pe.asset_a == "BTCUSDT"
    assert pe.asset_b == "ETHUSDT"

    # Switch to SOLUSDT/AVAXUSDT
    meta = pe.switch_pair("SOLUSDT/AVAXUSDT")
    assert meta["new_pair"] == "SOLUSDT/AVAXUSDT"
    assert pe.pair_name == "SOLUSDT/AVAXUSDT"
    assert pe.asset_a == "SOLUSDT"
    assert pe.asset_b == "AVAXUSDT"
    assert pe.current_position_state == 0
    assert len(pe.account.positions) == 0
    assert pe.price_stream is not None
    assert pe.price_stream.asset_a == "SOLUSDT"
    assert pe.price_stream.asset_b == "AVAXUSDT"


def test_engine_switch_pair_custom_alpha_beta():
    """Verifies explicit alpha and beta override when switching pairs."""
    pe = PaperTradingEngine(pair="BTCUSDT/ETHUSDT")
    meta = pe.switch_pair("ADAUSDT/DOTUSDT", alpha=-1.452, beta=0.8841)
    assert meta["alpha"] == -1.452
    assert meta["beta"] == 0.8841
    assert pe.alpha == -1.452
    assert pe.beta == 0.8841


def test_engine_switch_pair_invalid_format():
    """Verifies error handling for improperly formatted pair strings."""
    pe = PaperTradingEngine(pair="BTCUSDT/ETHUSDT")
    with pytest.raises(ValueError, match="Invalid pair format"):
        pe.switch_pair("INVALID_NO_SLASH")

    with pytest.raises(ValueError, match="Expected two non-empty symbols"):
        pe.switch_pair("BTCUSDT/")


def test_api_list_available_pairs(client):
    """Verifies GET /api/pairs returns universe pairs with active state."""
    res = client.get("/api/pairs")
    assert res.status_code == 200
    data = res.json()
    assert "current_pair" in data
    assert "pairs" in data
    assert isinstance(data["pairs"], list)
    assert len(data["pairs"]) >= 5

    pairs_names = [p["pair"] for p in data["pairs"]]
    assert "BTCUSDT/ETHUSDT" in pairs_names
    assert "SOLUSDT/AVAXUSDT" in pairs_names

    # Check active flag matches current_pair
    active_items = [p for p in data["pairs"] if p["active"]]
    assert len(active_items) == 1
    assert active_items[0]["pair"] == data["current_pair"]


def test_api_switch_pair_endpoint(client):
    """Verifies POST /api/pair switches engine and returns updated snapshot."""
    res = client.post("/api/pair", json={"pair": "SOLUSDT/AVAXUSDT"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["pair"] == "SOLUSDT/AVAXUSDT"
    assert "snapshot" in data
    assert data["snapshot"]["pair"] == "SOLUSDT/AVAXUSDT"
    assert engine.pair_name == "SOLUSDT/AVAXUSDT"

    # Verify /api/status now reports the new pair
    status_res = client.get("/api/status")
    assert status_res.status_code == 200
    assert status_res.json()["pair"] == "SOLUSDT/AVAXUSDT"

    # Verify /api/history returns valid payload for the switched pair
    hist_res = client.get("/api/history")
    assert hist_res.status_code == 200
    hist_data = hist_res.json()
    assert "labels" in hist_data
    assert "spreads" in hist_data
    assert "zscores" in hist_data
    assert len(hist_data["spreads"]) > 0


def test_api_switch_pair_invalid_payload(client):
    """Verifies 400 Bad Request on invalid pair payload."""
    res = client.post("/api/pair", json={"pair": "MALFORMED"})
    assert res.status_code == 400

    res_empty = client.post("/api/pair", json={})
    assert res_empty.status_code == 400


def test_restore_default_pair(client):
    """Switches back to BTCUSDT/ETHUSDT to preserve clean baseline."""
    res = client.post("/api/pair", json={"pair": "BTCUSDT/ETHUSDT"})
    assert res.status_code == 200
    assert res.json()["pair"] == "BTCUSDT/ETHUSDT"
    assert engine.pair_name == "BTCUSDT/ETHUSDT"
