"""
Unit tests for FastAPI App Autonomous Background Worker and Real-Time Endpoints.
Verifies lifespan worker task startup, mode toggles, manual tick injection,
status reporting, and WebSocket streaming.
"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import app, worker_state, engine


@pytest.fixture(scope="module")
def client():
    # Mock network call to Binance so tests execute immediately and offline
    with patch.object(engine, "fetch_live_prices", return_value=(46500.0, 2800.0)):
        with TestClient(app) as test_client:
            yield test_client


def test_health_endpoint(client):
    """Verifies that health check includes worker diagnostic indicators."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "crypto-stat-arb-backend"
    assert "worker_running" in data
    assert "worker_mode" in data
    assert "ticks_processed" in data


def test_worker_status_and_mode_toggle(client):
    """Verifies worker inspection and mode toggling between LIVE and PAUSED."""
    # Check initial worker status
    res = client.get("/api/worker")
    assert res.status_code == 200
    status_data = res.json()
    assert status_data["status"] == "running"
    assert "interval_seconds" in status_data
    assert "ticks_processed" in status_data

    # Pause the worker
    pause_res = client.post("/api/worker/mode", json={"mode": "PAUSED"})
    assert pause_res.status_code == 200
    assert pause_res.json()["mode"] == "PAUSED"
    assert worker_state["mode"] == "PAUSED"

    # Resume the worker
    live_res = client.post("/api/worker/mode", json={"mode": "LIVE"})
    assert live_res.status_code == 200
    assert live_res.json()["mode"] == "LIVE"
    assert worker_state["mode"] == "LIVE"

    # Invalid mode rejection
    invalid_res = client.post("/api/worker/mode", json={"mode": "INVALID_MODE"})
    assert invalid_res.status_code == 400


def test_manual_tick_injection(client):
    """Verifies that injecting a tick processes through the engine and increments worker counts."""
    initial_ticks = worker_state["ticks_processed"]
    payload = {
        "price_a": 46500.0,
        "price_b": 2800.0,
        "timestamp": "2024-01-01 12:00:00"
    }
    res = client.post("/api/worker/tick", json=payload)
    assert res.status_code == 200
    snapshot = res.json()
    assert snapshot["price_a"] == 46500.0
    assert snapshot["price_b"] == 2800.0
    assert snapshot["pair"] == "BTCUSDT/ETHUSDT"
    assert "candle_progress_pct" in snapshot
    assert worker_state["ticks_processed"] == initial_ticks + 1


def test_trading_status_endpoint(client):
    """Verifies that /api/status returns live engine snapshot with worker telemetry."""
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert "pair" in data
    assert "cash_balance" in data
    assert "total_equity" in data
    assert "zscore" in data
    assert "worker" in data
    assert data["worker"]["running"] is True


def test_step_simulation(client):
    """Verifies that /api/step advances the historical bar simulation."""
    res = client.post("/api/step")
    assert res.status_code == 200
    data = res.json()
    assert "price_a" in data
    assert "price_b" in data
    assert "action" in data


def test_portfolio_reset(client):
    """Verifies that /api/reset returns portfolio to initial cash neutral state."""
    res = client.post("/api/reset")
    assert res.status_code == 200
    data = res.json()
    assert data["cash_balance"] == 10000.0
    assert data["total_equity"] == 10000.0
    assert data["position_state"] == 0
    assert data["action"] == "RESET"


def test_websocket_tick_stream(client):
    """Verifies WebSocket connection to /ws/ticks, initial snapshot push, and ping/pong."""
    with client.websocket_connect("/ws/ticks") as websocket:
        # Initial snapshot sent upon connect
        data = websocket.receive_json()
        assert "pair" in data
        assert "total_equity" in data

        # Ping pong test
        websocket.send_text("ping")
        reply = websocket.receive_text()
        assert reply == "pong"
