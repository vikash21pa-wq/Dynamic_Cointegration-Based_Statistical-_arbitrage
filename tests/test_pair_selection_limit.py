"""
Unit & Integration Tests for Pair Selection Ceiling Validation.
Verifies the mandatory rule:
  "Never pick or activate more than 2 pairs at once"

Tests:
  1. Configuration limits: max_active_pairs == 2 and max_selected_pairs == 2.
  2. PairSelectionEngine.validate_pair_count rejects > 2 pairs.
  3. PairSelectionEngine.select_pairs rejects requests for > 2 pairs.
  4. PairSelectionEngine.select_pairs returns at most 2 top candidate pairs.
  5. RiskManager.validate_active_pairs flags active pair count > 2.
  6. RiskManager.can_open_new_pair blocks when active pairs count is 2.
  7. run_experiment pipeline rejects max_pairs > 2.
  8. Web API POST /api/pair rejects requests with > 2 pairs.
  9. Web API GET /api/pairs exposes max_active_pairs=2 and selection_limit=2.
"""

import pytest
import pandas as pd
from fastapi.testclient import TestClient

from config import trading_config, selection_config
from src.pair_selection import PairSelectionEngine
from src.risk_management import RiskManager
from main import run_experiment
from app import app


def test_config_limits():
    """Confirms configuration specifies exactly 2 pairs maximum."""
    assert trading_config.max_active_pairs == 2
    assert selection_config.max_selected_pairs == 2


def test_pair_selection_engine_validate_pair_count():
    """Confirms validate_pair_count accepts <= 2 and rejects > 2."""
    engine = PairSelectionEngine()

    # Valid counts
    assert engine.validate_pair_count(1) == 1
    assert engine.validate_pair_count(2) == 2
    assert engine.validate_pair_count(["BTC/ETH"]) == 1
    assert engine.validate_pair_count(["BTC/ETH", "SOL/AVAX"]) == 2

    # Invalid counts (> 2) must raise ValueError
    with pytest.raises(ValueError, match="Cannot pick more than 2 pairs at once"):
        engine.validate_pair_count(3)

    with pytest.raises(ValueError, match="Cannot pick more than 2 pairs at once"):
        engine.validate_pair_count(5)

    with pytest.raises(ValueError, match="Cannot pick more than 2 pairs at once"):
        engine.validate_pair_count(["BTC/ETH", "SOL/AVAX", "ADA/DOT"])


def test_pair_selection_engine_select_pairs_rejects_greater_than_2():
    """Confirms select_pairs raises ValueError when requesting max_pairs > 2."""
    engine = PairSelectionEngine()
    mock_df = pd.DataFrame([
        {"pair": "BTCUSDT/ETHUSDT", "p_value": 0.001, "eligible": True},
        {"pair": "SOLUSDT/AVAXUSDT", "p_value": 0.005, "eligible": True},
        {"pair": "ADAUSDT/DOTUSDT", "p_value": 0.010, "eligible": True},
    ])

    with pytest.raises(ValueError, match="Cannot pick more than 2 pairs at once"):
        engine.select_pairs(mock_df, max_pairs=3)


def test_pair_selection_engine_select_pairs_enforces_ceiling():
    """Confirms select_pairs returns strictly <= 2 candidate pairs sorted by cointegration strength."""
    engine = PairSelectionEngine()
    mock_df = pd.DataFrame([
        {"pair": "ADAUSDT/DOTUSDT", "p_value": 0.020, "eligible": True},
        {"pair": "BTCUSDT/ETHUSDT", "p_value": 0.001, "eligible": True},
        {"pair": "SOLUSDT/AVAXUSDT", "p_value": 0.005, "eligible": True},
        {"pair": "ETHUSDT/BNBUSDT", "p_value": 0.035, "eligible": True},
    ])

    # Default call must return top 2 pairs
    top_pairs = engine.select_pairs(mock_df)
    assert len(top_pairs) == 2
    assert top_pairs.iloc[0]["pair"] == "BTCUSDT/ETHUSDT"
    assert top_pairs.iloc[1]["pair"] == "SOLUSDT/AVAXUSDT"

    # Selecting 1 pair
    single_pair = engine.select_pairs(mock_df, max_pairs=1)
    assert len(single_pair) == 1
    assert single_pair.iloc[0]["pair"] == "BTCUSDT/ETHUSDT"


def test_risk_manager_active_pairs_validation():
    """Confirms RiskManager allows up to 2 active pairs and blocks > 2."""
    rm = RiskManager(max_active_pairs=2)

    # Validate active count
    valid_1, _ = rm.validate_active_pairs(1)
    assert valid_1 is True

    valid_2, _ = rm.validate_active_pairs(["BTC/ETH", "SOL/AVAX"])
    assert valid_2 is True

    valid_3, msg_3 = rm.validate_active_pairs(["BTC/ETH", "SOL/AVAX", "ADA/DOT"])
    assert valid_3 is False
    assert "Cannot pick or trade 3 active pairs simultaneously" in msg_3

    # Check whether new pair can be opened
    can_open_0, _ = rm.can_open_new_pair(0)
    assert can_open_0 is True

    can_open_1, _ = rm.can_open_new_pair(1)
    assert can_open_1 is True

    can_open_2, msg_open_2 = rm.can_open_new_pair(2)
    assert can_open_2 is False
    assert "Hard ceiling is 2 pairs at once" in msg_open_2


def test_main_pipeline_run_experiment_rejects_over_limit():
    """Confirms run_experiment raises ValueError if max_pairs > 2 is passed."""
    with pytest.raises(ValueError, match="Cannot pick more than 2 pairs at once"):
        run_experiment(max_pairs=3, screen_only=True)


def test_api_pair_selection_validation():
    """Confirms Web API rejects multi-pair payloads exceeding 2 pairs and advertises limit."""
    client = TestClient(app)

    # 1. GET /api/pairs exposes max_active_pairs=2 and selection_limit=2
    res_pairs = client.get("/api/pairs")
    assert res_pairs.status_code == 200
    data_pairs = res_pairs.json()
    assert data_pairs["max_active_pairs"] == 2
    assert data_pairs["selection_limit"] == 2

    # 2. POST /api/pair with > 2 pairs is rejected with HTTP 400
    invalid_payload = {
        "pairs": ["BTCUSDT/ETHUSDT", "SOLUSDT/AVAXUSDT", "ADAUSDT/DOTUSDT"]
    }
    res_switch = client.post("/api/pair", json=invalid_payload)
    assert res_switch.status_code == 400
    detail = res_switch.json()["detail"]
    assert "Cannot pick more than 2 pairs at once" in detail

