"""
Data Preprocessing and Synchronization Module.
Ensures rigorous alignment of multi-asset 5-minute candles, missing candle detection,
log-transformation, and statistical quality audit reporting.
"""

import logging
from pathlib import Path
from typing import Dict, Tuple, List, Optional

import pandas as pd
import numpy as np

from config import PROCESSED_DATA_DIR, market_config

logger = logging.getLogger(__name__)


class DataPreprocessor:
    """
    Cleans, verifies, and synchronizes multi-asset high-frequency OHLCV datasets.
    """

    def __init__(self, processed_dir: Path = PROCESSED_DATA_DIR):
        self.processed_dir = Path(processed_dir)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def audit_single_asset(symbol: str, df: pd.DataFrame, expected_step_ms: int = 300000) -> Dict:
        """
        Calculates quality diagnostics for a single asset's time series.
        expected_step_ms: 5 minutes = 300,000 ms.
        """
        n_rows = len(df)
        if n_rows == 0:
            return {
                "symbol": symbol,
                "row_count": 0,
                "missing_candles": 0,
                "zero_prices": 0,
                "zero_volume": 0,
                "outlier_returns": 0,
                "status": "EMPTY"
            }

        # Check timestamp continuity
        ts_diff = df["timestamp"].diff().dropna()
        gaps = (ts_diff > expected_step_ms).sum()
        missing_candles_approx = int(((ts_diff - expected_step_ms) / expected_step_ms).clip(lower=0).sum())

        zero_prices = (df["close"] <= 0).sum()
        zero_vol = (df["volume"] <= 0).sum()

        # Log returns and outliers (> 5 rolling sigma)
        log_ret = np.log(df["close"] / df["close"].shift(1)).dropna()
        sigma = log_ret.std()
        outliers = (np.abs(log_ret - log_ret.mean()) > 5 * sigma).sum() if sigma > 0 else 0

        return {
            "symbol": symbol,
            "row_count": n_rows,
            "start_time": str(df["datetime"].iloc[0]),
            "end_time": str(df["datetime"].iloc[-1]),
            "missing_gaps_count": int(gaps),
            "estimated_missing_candles": missing_candles_approx,
            "zero_or_negative_prices": int(zero_prices),
            "zero_volume_bars": int(zero_vol),
            "outlier_5sigma_returns": int(outliers),
            "status": "PASSED" if (zero_prices == 0 and missing_candles_approx < n_rows * 0.05) else "WARNING"
        }

    def generate_quality_report(self, raw_data_dict: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """
        Creates a comprehensive data quality report across all universe assets.
        """
        reports = []
        for symbol, df in raw_data_dict.items():
            rep = self.audit_single_asset(symbol, df)
            reports.append(rep)

        report_df = pd.DataFrame(reports)
        report_path = self.processed_dir / "data_quality_report.csv"
        report_df.to_csv(report_path, index=False)
        logger.info(f"Saved data quality report to {report_path}")
        return report_df

    def synchronize_universe(
        self,
        raw_data_dict: Dict[str, pd.DataFrame],
        save_csv: bool = True
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Synchronizes timestamps across all assets via strict intersection.
        Returns:
            aligned_close: DataFrame of close prices with datetime index
            aligned_log_prices: DataFrame of natural log prices
            aligned_log_returns: DataFrame of log return changes
        """
        if not raw_data_dict:
            raise ValueError("No raw asset DataFrames provided for synchronization.")

        # Extract close prices indexed by UTC datetime
        close_series_list = []
        for symbol, df in raw_data_dict.items():
            if df.empty:
                continue
            cleaned = df[(df["close"] > 0) & (df["volume"] > 0)].copy()
            cleaned.set_index("datetime", inplace=True)
            s = cleaned["close"].rename(symbol)
            s = s[~s.index.duplicated(keep="first")]
            close_series_list.append(s)

        if not close_series_list:
            raise ValueError("All asset DataFrames were empty or invalid.")

        # Inner join to guarantee exact timestamp concurrence
        aligned_close = pd.concat(close_series_list, axis=1, join="inner")
        aligned_close.sort_index(inplace=True)

        # Drop any remaining NaNs
        aligned_close.dropna(inplace=True)

        if len(aligned_close) == 0:
            raise ValueError("Timestamp synchronization resulted in 0 overlapping candles across assets.")

        # Compute log prices and log returns
        aligned_log_prices = np.log(aligned_close)
        aligned_log_returns = aligned_log_prices.diff().dropna()

        logger.info(f"Synchronized {aligned_close.shape[1]} assets across {len(aligned_close)} bars. Range: {aligned_close.index[0]} to {aligned_close.index[-1]}")

        if save_csv:
            close_path = self.processed_dir / "aligned_close_prices.csv"
            aligned_close.to_csv(close_path)
            log_path = self.processed_dir / "aligned_log_prices.csv"
            aligned_log_prices.to_csv(log_path)
            logger.info(f"Saved synchronized datasets to {self.processed_dir}")

        return aligned_close, aligned_log_prices, aligned_log_returns
