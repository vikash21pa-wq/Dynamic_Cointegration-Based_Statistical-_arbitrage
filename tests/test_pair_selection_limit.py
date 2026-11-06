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

    # 1. GET /api/pairs exposes max_active_pairs=2, selection_limit=2, and correlation targets
    res_pairs = client.get("/api/pairs")
    assert res_pairs.status_code == 200
    data_pairs = res_pairs.json()
    assert data_pairs["max_active_pairs"] == 2
    assert data_pairs["selection_limit"] == 2
    assert data_pairs["target_correlation_min"] == 0.94
    assert data_pairs["target_correlation_max"] == 0.97

    # 2. POST /api/pair with > 2 pairs is rejected with HTTP 400
    invalid_payload = {
        "pairs": ["BTCUSDT/ETHUSDT", "SOLUSDT/AVAXUSDT", "ADAUSDT/DOTUSDT"]
    }
    res_switch = client.post("/api/pair", json=invalid_payload)
    assert res_switch.status_code == 400
    detail = res_switch.json()["detail"]
    assert "Cannot pick more than 2 pairs at once" in detail


def test_pair_selection_engine_validate_pair_correlation():
    """Confirms validate_pair_correlation validates the [0.94, 0.97] band."""
    valid, msg = PairSelectionEngine.validate_pair_correlation(0.95)
    assert valid is True
    assert msg == "OK"

    valid_edge_low, _ = PairSelectionEngine.validate_pair_correlation(0.94)
    assert valid_edge_low is True

    valid_edge_high, _ = PairSelectionEngine.validate_pair_correlation(0.97)
    assert valid_edge_high is True

    # Below 0.94 must fail
    invalid_low, msg_low = PairSelectionEngine.validate_pair_correlation(0.93)
    assert invalid_low is False
    assert "outside required target range" in msg_low

    # Above 0.97 must fail
    invalid_high, msg_high = PairSelectionEngine.validate_pair_correlation(0.98)
    assert invalid_high is False
    assert "outside required target range" in msg_high


def test_pair_selection_engine_select_pairs_target_correlation_range():
    """
    Confirms select_pairs prioritizes candidate pairs strictly within [0.94, 0.97]
    and picks at most 2 with the highest correlation.
    """
    engine = PairSelectionEngine()
    mock_df = pd.DataFrame([
        {"pair": "PAIR_TOO_HIGH", "correlation": 0.99, "p_value": 0.0001, "eligible": True},
        {"pair": "PAIR_BEST", "correlation": 0.965, "p_value": 0.0010, "eligible": True},
        {"pair": "PAIR_SECOND_BEST", "correlation": 0.955, "p_value": 0.0015, "eligible": True},
        {"pair": "PAIR_THIRD_BEST", "correlation": 0.942, "p_value": 0.0020, "eligible": True},
        {"pair": "PAIR_TOO_LOW", "correlation": 0.880, "p_value": 0.0005, "eligible": True},
    ])

    selected = engine.select_pairs(mock_df, max_pairs=2)
    assert len(selected) == 2
    assert selected.iloc[0]["pair"] == "PAIR_BEST"
    assert selected.iloc[0]["correlation"] == 0.965
    assert selected.iloc[1]["pair"] == "PAIR_SECOND_BEST"
    assert selected.iloc[1]["correlation"] == 0.955


def test_pair_selection_engine_strict_correlation_rejection():
    """Confirms select_pairs raises ValueError when strict=True and no pair matches [0.94, 0.97]."""
    engine = PairSelectionEngine()
    low_corr_df = pd.DataFrame([
        {"pair": "LOW_A", "correlation": 0.85, "p_value": 0.001, "eligible": True},
        {"pair": "LOW_B", "correlation": 0.80, "p_value": 0.002, "eligible": True},
    ])

    with pytest.raises(ValueError, match="Target correlation policy strictly requires pairs in"):
        engine.select_pairs(low_corr_df, strict_correlation=True)


def test_risk_manager_correlation_validation():
    """Confirms RiskManager validate_pair_correlation checks [0.94, 0.97]."""
    rm = RiskManager()
    valid_ok, _ = rm.validate_pair_correlation(0.95)
    assert valid_ok is True

    valid_low, msg_low = rm.validate_pair_correlation(0.85)
    assert valid_low is False
    assert "outside policy window" in msg_low

    valid_high, msg_high = rm.validate_pair_correlation(0.99)
    assert valid_high is False
    assert "outside policy window" in msg_high


