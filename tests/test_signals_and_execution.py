import pytest
import numpy as np
import pandas as pd

from src.signals import SignalGenerator
from src.execution import ExecutionEngine
from src.backtester import PairsBacktester
from src.data_loader import generate_synthetic_futures_data
from src.preprocessing import DataPreprocessor


def test_signal_generator_crossing_logic():
    np.random.seed(42)
    gen = SignalGenerator(window=30, entry_threshold=2.0, exit_threshold=0.25)
    # Construct spread with base noise and an excursion
    n = 150
    spread = np.random.normal(0, 0.2, n)
    # Add excursion exceeding 2.0 sigma between bars 50 and 65
    spread[50:65] += 1.5

    spread_series = pd.Series(spread)
    zscore, _, _ = gen.compute_zscore(spread_series)
    pos_df = gen.generate_positions(zscore)

    # Must contain short spread position (-1) during high excursion
    assert -1 in pos_df["position"].values
    # Must revert to 0 when excursion subsides
    assert pos_df["position"].iloc[-1] == 0


def test_execution_notional_weighting():
    engine = ExecutionEngine(fee_pct=0.0005, slippage_pct=0.0002)
    gross_cap = 1000.0
    beta = 1.5

    # For Long Spread: Long A, Short B
    notional_a, notional_b = engine.compute_leg_notionals(gross_cap, beta=beta, position_state=1)

    assert notional_a > 0
    assert notional_b < 0
    # Gross sum: |NA| + |NB| == gross_cap
    assert np.isclose(abs(notional_a) + abs(notional_b), gross_cap)

    # Cost calculation
    turnover, cost = engine.calculate_turnover_and_costs(0.0, notional_a, 0.0, notional_b)
    assert np.isclose(turnover, gross_cap)
    assert np.isclose(cost, gross_cap * 0.0007)


def test_pairs_backtester_end_to_end():
    raw_data = generate_synthetic_futures_data(symbols=["BTCUSDT", "ETHUSDT"], n_bars=800, seed=42)
    pre = DataPreprocessor()
    aligned_close, aligned_log, _ = pre.synchronize_universe(raw_data, save_csv=False)

    backtester = PairsBacktester(initial_capital=10000.0, pair_allocation=0.10)
    result = backtester.run_pair_simulation(
        price_a=aligned_close["BTCUSDT"],
        price_b=aligned_close["ETHUSDT"],
        alpha=0.5,
        beta=0.85,
        pair_name="BTCUSDT/ETHUSDT",
        use_kalman=False
    )

    metrics = result["metrics"]
    history = result["history"]

    assert "annualized_sharpe_ratio" in metrics
    assert "max_drawdown_pct" in metrics
    assert len(history) == 800
    assert history["equity"].iloc[0] == 10000.0
