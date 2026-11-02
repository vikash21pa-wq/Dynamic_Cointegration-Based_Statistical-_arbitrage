import pytest
import pandas as pd
import numpy as np

from src.preprocessing import DataPreprocessor
from src.data_loader import generate_synthetic_futures_data


def test_audit_single_asset():
    raw_data = generate_synthetic_futures_data(symbols=["BTCUSDT"], n_bars=300, seed=1)
    df = raw_data["BTCUSDT"]
    audit = DataPreprocessor.audit_single_asset("BTCUSDT", df)

    assert audit["symbol"] == "BTCUSDT"
    assert audit["row_count"] == 300
    assert audit["zero_or_negative_prices"] == 0
    assert audit["status"] == "PASSED"


def test_synchronize_universe():
    raw_data = generate_synthetic_futures_data(symbols=["BTCUSDT", "ETHUSDT"], n_bars=500, seed=2)
    preprocessor = DataPreprocessor()
    aligned_close, aligned_log, aligned_ret = preprocessor.synchronize_universe(raw_data, save_csv=False)

    assert "BTCUSDT" in aligned_close.columns
    assert "ETHUSDT" in aligned_close.columns
    assert len(aligned_close) == 500
    assert len(aligned_log) == 500
    assert len(aligned_ret) == 499

    # Verify log prices match natural log of close prices
    np.testing.assert_allclose(aligned_log["BTCUSDT"].values, np.log(aligned_close["BTCUSDT"].values))
