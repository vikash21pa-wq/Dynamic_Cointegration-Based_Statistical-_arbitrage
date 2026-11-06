"""
Unit & Integration Tests for the Research Blueprint Validation Framework.
Verifies the complete validation specifications from the PDF blueprint:
  1. Section 4: Dual Cointegration & Stationarity (ADF + complementary KPSS)
  2. Section 7: 6-Tier Stop-Loss Architecture
  3. Section 8 & 17: Net Trade Expectancy (EV) and Profit Factor
  4. Section 14: 7 Suggested Research Gates Evaluation
"""

import pytest
import numpy as np
import pandas as pd

from config import selection_config, trading_config
from src.pair_selection import PairSelectionEngine
from src.risk_management import RiskManager
from src.performance import PerformanceAnalyzer


def test_dual_stationarity_adf_and_kpss():
    """
    Confirms complementary ADF + KPSS stationarity testing:
    - ADF rejects unit root (p < 0.05)
    - KPSS fails to reject stationarity (p >= 0.05)
    - Conflicting KPSS (p < 0.01) is flagged.
    """
    engine = PairSelectionEngine()

    # Generate synthetic stationary AR(1) mean-reverting series
    np.random.seed(42)
    n = 500
    eps = np.random.randn(n)
    log_b = np.cumsum(np.random.randn(n) * 0.01) + 4.0
    spread = np.zeros(n)
    for i in range(1, n):
        spread[i] = 0.6 * spread[i - 1] + eps[i] * 0.005

    log_a = spread + 1.2 * log_b + 0.5
    s_a = pd.Series(log_a)
    s_b = pd.Series(log_b)
    r_a = s_a.diff().fillna(0)
    r_b = s_b.diff().fillna(0)

    metrics = engine.analyze_pair(s_a, s_b, r_a, r_b)

    assert "adf_p_value" in metrics
    assert "kpss_p_value" in metrics
    assert "durbin_watson" in metrics

    # The stationary residual should pass ADF (p < 0.05) and KPSS (p >= 0.05)
    assert metrics["adf_p_value"] < 0.05
    assert metrics["kpss_p_value"] >= 0.05
    assert 0.5 < metrics["durbin_watson"] < 3.5

    # Test spread quality validation with conflicting KPSS
    ok, msg = PairSelectionEngine.validate_spread_quality(
        spread_std=0.015,
        half_life_hours=4.0,
        p_value=0.01,
        kpss_p_value=0.005  # Severe conflict
    )
    assert ok is False
    assert "KPSS rejects stationarity" in msg


def test_six_tier_stop_loss_architecture():
    """
    Confirms all 6 exit mechanisms defined in Section 7 of the blueprint:
    1. EXIT_STATISTICAL_STOP (|Z| >= 3.5)
    2. EXIT_STRUCTURAL_BREAK (p-value > 0.15 or vol jump)
    3. EXIT_TIME_STOP (bars held >= max holding horizon)
    4. EXIT_VOLATILITY_STOP (spread std > 15%)
    5. EXIT_PORTFOLIO_STOP (drawdown <= -5%)
    6. EXIT_LEGGING_STOP (timeout on single unhedged leg)
    """
    rm = RiskManager()

    # 1. Legging stop
    exit_1, stop_1, _ = rm.validate_multi_stop(
        zscore=0.5, rolling_p_value=0.01, current_spread_std=0.01,
        baseline_spread_std=0.01, current_half_life_bars=10, bars_held=5,
        leg_mismatch_timeout=True
    )
    assert exit_1 is True
    assert stop_1 == "EXIT_LEGGING_STOP"

    # 2. Portfolio loss stop (-5% limit)
    exit_2, stop_2, _ = rm.validate_multi_stop(
        zscore=1.5, rolling_p_value=0.01, current_spread_std=0.01,
        baseline_spread_std=0.01, current_half_life_bars=10, bars_held=5,
        pair_unrealized_pnl_pct=-0.055
    )
    assert exit_2 is True
    assert stop_2 == "EXIT_PORTFOLIO_STOP"

    # 3. Statistical Z-score stop (|Z| >= 3.5)
    exit_3, stop_3, _ = rm.validate_multi_stop(
        zscore=3.6, rolling_p_value=0.01, current_spread_std=0.01,
        baseline_spread_std=0.01, current_half_life_bars=10, bars_held=5
    )
    assert exit_3 is True
    assert stop_3 == "EXIT_STATISTICAL_STOP"

    # 4. Volatility stop (spread std > 15%)
    exit_4, stop_4, _ = rm.validate_multi_stop(
        zscore=1.0, rolling_p_value=0.01, current_spread_std=0.18,
        baseline_spread_std=0.01, current_half_life_bars=10, bars_held=5
    )
    assert exit_4 is True
    assert stop_4 == "EXIT_VOLATILITY_STOP"

    # 5. Structural break stop (p-value deteriorated + vol expanded)
    exit_5, stop_5, _ = rm.validate_multi_stop(
        zscore=1.0, rolling_p_value=0.25, current_spread_std=0.035,
        baseline_spread_std=0.01, current_half_life_bars=10, bars_held=5
    )
    assert exit_5 is True
    assert stop_5 == "EXIT_STRUCTURAL_BREAK"

    # 6. Time stop (bars held >= 3 * half_life)
    exit_6, stop_6, _ = rm.validate_multi_stop(
        zscore=1.0, rolling_p_value=0.01, current_spread_std=0.01,
        baseline_spread_std=0.01, current_half_life_bars=10, bars_held=35
    )
    assert exit_6 is True
    assert stop_6 == "EXIT_TIME_STOP"

    # Nominal healthy hold
    exit_nom, stop_nom, _ = rm.validate_multi_stop(
        zscore=1.0, rolling_p_value=0.01, current_spread_std=0.01,
        baseline_spread_std=0.01, current_half_life_bars=10, bars_held=5
    )
    assert exit_nom is False
    assert stop_nom == "HOLD"


def test_net_trade_expectancy_and_profit_factor():
    """
    Confirms net trade expectancy formula from Section 8 & 17:
    EV = P(win) * mean(win) - P(loss) * mean(loss) - cost_per_trade
    """
    analyzer = PerformanceAnalyzer()

    # Mock 10 trades: 6 wins of +$100, 4 losses of -$60, $20 total fees
    trades = pd.DataFrame([
        {"pnl": 100.0, "holding_bars": 12},
        {"pnl": 100.0, "holding_bars": 15},
        {"pnl": 100.0, "holding_bars": 8},
        {"pnl": 100.0, "holding_bars": 20},
        {"pnl": 100.0, "holding_bars": 10},
        {"pnl": 100.0, "holding_bars": 14},
        {"pnl": -60.0, "holding_bars": 25},
        {"pnl": -60.0, "holding_bars": 30},
        {"pnl": -60.0, "holding_bars": 18},
        {"pnl": -60.0, "holding_bars": 22},
    ])
    equity = pd.Series([10000.0 + i * 20 for i in range(100)])
    returns = equity.pct_change().dropna()

    res = analyzer.calculate_metrics(
        equity_series=equity,
        bar_returns=returns,
        trades_df=trades,
        total_costs=20.0,
        initial_capital=10000.0
    )

    assert res["total_trades_completed"] == 10
    assert res["win_rate_pct"] == 60.0
    assert res["avg_win"] == 100.0
    assert res["avg_loss"] == 60.0

    # Profit Factor = Gross Wins (600) / Gross Losses (240) = 2.50
    assert round(res["profit_factor"], 2) == 2.50

    # EV = 0.6 * 100 - 0.4 * 60 - (20 / 10) = 60 - 24 - 2 = 34.0
    assert round(res["trade_expectancy"], 2) == 34.0


def test_seven_research_gates_evaluation():
    """
    Confirms the 7 Suggested Research Gates evaluation (Section 14):
    Data, Statistical, Economic, Risk, Robustness, Operational, Pilot.
    """
    pair_metrics_pass = {
        "correlation": 0.93,
        "p_value": 0.005,
        "kpss_p_value": 0.10,
        "half_life_hours": 3.2,
        "spread_std": 0.015
    }
    perf_metrics_pass = {
        "trade_expectancy": 45.0,
        "profit_factor": 2.2,
        "max_drawdown_pct": 4.5
    }
    op_status_pass = {
        "stream_connected": True
    }

    gates_res = RiskManager.evaluate_research_gates(
        pair_metrics=pair_metrics_pass,
        performance_metrics=perf_metrics_pass,
        operational_status=op_status_pass
    )

    assert gates_res["all_gates_passed"] is True
    assert gates_res["gates_passed_count"] == 7
    assert len(gates_res["failed_gates"]) == 0

    # Test with failing statistical gate (correlation too low, e.g. 0.80)
    pair_metrics_fail = dict(pair_metrics_pass)
    pair_metrics_fail["correlation"] = 0.80

    gates_fail = RiskManager.evaluate_research_gates(
        pair_metrics=pair_metrics_fail,
        performance_metrics=perf_metrics_pass,
        operational_status=op_status_pass
    )

    assert gates_fail["all_gates_passed"] is False
    assert "statistical_gate" in gates_fail["failed_gates"]


def test_risk_budget_position_sizing_and_neutrality():
    """
    Confirms Risk-Budget Sizing and Exposure Diagnostics from Section 9 & 17 of the Research Blueprint:
    1. Quantity = Risk Budget / Estimated Loss at Stop.
    2. Beta-neutral sizing: N_A = G / (1 + |beta|), N_B = |beta| * G / (1 + |beta|).
    3. Market neutrality: beta-adjusted net exposure cancels out to ~0.
    4. Sizing scales down when spread volatility expands.
    """
    from src.execution import ExecutionEngine

    exec_engine = ExecutionEngine(fee_pct=0.0005, slippage_pct=0.0002)

    equity = 10000.0
    beta = 1.25

    # Case A: Low spread volatility (0.005) -> allocation is capped by standard 10% budget ($1,000)
    notional_a_low, notional_b_low, meta_low = exec_engine.compute_risk_budgeted_notionals(
        equity=equity,
        beta=beta,
        spread_std=0.005,
        position_state=1,
        risk_budget_pct=0.01,
        max_allocation_pct=0.10
    )

    assert np.isclose(abs(notional_a_low) + abs(notional_b_low), 1000.0)
    assert meta_low["is_risk_budget_constrained"] is False
    # Beta-neutrality: notional_a - notional_b / beta == 0
    assert np.isclose(abs(notional_a_low) - (abs(notional_b_low) / beta), 0.0)

    # Case B: High spread volatility (0.080) -> risk budget (1% = $100) forces gross capital to scale down
    notional_a_high, notional_b_high, meta_high = exec_engine.compute_risk_budgeted_notionals(
        equity=equity,
        beta=beta,
        spread_std=0.080,
        position_state=1,
        risk_budget_pct=0.01,
        max_allocation_pct=0.10
    )

    gross_high = abs(notional_a_high) + abs(notional_b_high)
    assert gross_high < 1000.0  # Scaled down to protect portfolio stop!
    assert meta_high["is_risk_budget_constrained"] is True
    # The maximum loss at the emergency stop is strictly <= the $100 risk budget
    assert meta_high["estimated_loss_at_stop"] <= 100.0001

    # Diagnostics verification
    diag = ExecutionEngine.compute_exposure_diagnostics(notional_a_low, notional_b_low, beta=beta)
    assert diag["gross_notional"] == 1000.0
    assert np.isclose(diag["beta_adjusted_net"], 0.0)


