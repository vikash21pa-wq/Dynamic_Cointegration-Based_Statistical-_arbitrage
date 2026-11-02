import pytest
import numpy as np
import pandas as pd

from src.pair_selection import (
    calculate_half_life,
    benjamini_hochberg_correction,
    PairSelectionEngine
)
from src.data_loader import generate_synthetic_futures_data
from src.preprocessing import DataPreprocessor


def test_calculate_half_life():
    np.random.seed(42)
    # Generate stationary AR(1) process with lambda = -0.1
    # Theoretical Half-Life = -ln(2)/(-0.1) ~ 6.93
    n = 2000
    spread = np.zeros(n)
    for t in range(1, n):
        spread[t] = spread[t - 1] * 0.90 + np.random.normal(0, 0.1)  # Delta S = -0.10 * S_{t-1} + e

    hl, lam = calculate_half_life(spread)
    assert np.isfinite(hl)
    assert 5.0 <= hl <= 9.0
    assert lam < 0.0


def test_benjamini_hochberg_correction():
    # 5 tests, 2 truly significant
    raw_p = [0.001, 0.008, 0.04, 0.25, 0.70]
    adj_p, reject = benjamini_hochberg_correction(raw_p, alpha=0.05)

    assert len(adj_p) == 5
    assert len(reject) == 5
    assert reject[0] == True  # 0.001 should reject
    assert reject[1] == True  # 0.008 should reject
    assert reject[4] == False  # 0.70 should not reject
    # Monotonicity check
    assert np.all(np.diff(np.sort(adj_p)) >= 0)


def test_pair_selection_synthetic_cointegration():
    # Synthetic data has ETH cointegrated with BTC
    raw_data = generate_synthetic_futures_data(symbols=["BTCUSDT", "ETHUSDT"], n_bars=1500, seed=123)
    pre = DataPreprocessor()
    aligned_close, aligned_log, aligned_ret = pre.synchronize_universe(raw_data, save_csv=False)

    engine = PairSelectionEngine(min_correlation=0.50, coint_alpha=0.05)
    results_df = engine.screen_universe(aligned_log, aligned_ret)

    assert len(results_df) == 1
    row = results_df.iloc[0]
    assert row["pair"] == "BTCUSDT/ETHUSDT"
    assert row["p_value"] < 0.05
    assert row["beta"] > 0
    assert row["half_life_bars"] > 0
