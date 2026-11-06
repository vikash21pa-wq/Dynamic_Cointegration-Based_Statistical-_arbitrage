"""
Pair Selection Engine.
Performs log-return correlation screening, Engle-Granger two-step cointegration testing,
Augmented Dickey-Fuller stationarity validation, Ornstein-Uhlenbeck half-life estimation,
and Benjamini-Hochberg False Discovery Rate (FDR) multiple testing corrections.
"""

import itertools
import logging
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd
import numpy as np
import statsmodels.api as sm
from statsmodels.tsa.stattools import coint, adfuller

from config import PROCESSED_DATA_DIR, selection_config

logger = logging.getLogger(__name__)


def calculate_half_life(spread: np.ndarray) -> Tuple[float, float]:
    """
    Estimates the half-life of mean reversion using an Ornstein-Uhlenbeck / AR(1) process:
        Delta S_t = lambda * S_{t-1} + error_t
    Half-life = -ln(2) / lambda (for lambda < 0).

    Returns:
        (half_life_bars, lambda_coef)
    """
    if len(spread) < 10:
        return np.inf, 0.0

    s_lag = spread[:-1]
    s_diff = np.diff(spread)

    # Regress delta on lag with intercept
    X = sm.add_constant(s_lag)
    try:
        model = sm.OLS(s_diff, X).fit()
        lam = model.params[1]
        if lam < 0:
            half_life = -np.log(2.0) / lam
            return float(half_life), float(lam)
        else:
            return np.inf, float(lam)
    except Exception:
        return np.inf, 0.0


def benjamini_hochberg_correction(p_values: List[float], alpha: float = 0.10) -> Tuple[np.ndarray, np.ndarray]:
    """
    Benjamini-Hochberg False Discovery Rate (FDR) procedure for multiple hypothesis testing.

    Args:
        p_values: List of raw p-values from cointegration tests.
        alpha: Target FDR rate.

    Returns:
        adjusted_p_values: FDR adjusted p-values (q-values)
        reject: Boolean array where True indicates statistically significant rejection of null hypothesis.
    """
    m = len(p_values)
    if m == 0:
        return np.array([]), np.array([])

    p_vals = np.asarray(p_values)
    sorted_order = np.argsort(p_vals)
    sorted_p = p_vals[sorted_order]

    # Adjusted p-values (q-values)
    q_vals = np.zeros(m)
    for i in range(m - 1, -1, -1):
        rank = i + 1
        q_val = sorted_p[i] * m / rank
        if i == m - 1:
            q_vals[i] = min(1.0, q_val)
        else:
            q_vals[i] = min(1.0, min(q_val, q_vals[i + 1]))

    # Unsort back to original order
    adjusted_p_values = np.zeros(m)
    adjusted_p_values[sorted_order] = q_vals

    reject = adjusted_p_values <= alpha
    return adjusted_p_values, reject


class PairSelectionEngine:
    """
    Identifies, screens, and statistically validates cryptocurrency pairs.
    """

    def __init__(
        self,
        min_correlation: float = selection_config.min_correlation,
        coint_alpha: float = selection_config.cointegration_alpha,
        fdr_alpha: float = selection_config.fdr_alpha,
        require_positive_beta: bool = selection_config.require_positive_beta,
        max_half_life_bars: int = selection_config.max_half_life_bars,
        processed_dir: Path = PROCESSED_DATA_DIR
    ):
        self.min_correlation = min_correlation
        self.coint_alpha = coint_alpha
        self.fdr_alpha = fdr_alpha
        self.require_positive_beta = require_positive_beta
        self.max_half_life_bars = max_half_life_bars
        self.processed_dir = Path(processed_dir)

    def analyze_pair(
        self,
        log_price_a: pd.Series,
        log_price_b: pd.Series,
        log_returns_a: pd.Series,
        log_returns_b: pd.Series
    ) -> Dict[str, Any]:
        """
        Executes complete statistical battery for a single pair (A, B):
        - Return Pearson correlation
        - OLS cointegrating regression: log_A = alpha + beta * log_B + eps
        - Engle-Granger Cointegration test (t-stat, p-value, critical values)
        - Stationarity of spread residuals
        - Half-life of mean reversion
        """
        # 1. Pearson return correlation
        corr = float(log_returns_a.corr(log_returns_b))

        # 2. OLS regression for hedge ratio beta and intercept
        X = sm.add_constant(log_price_b.values)
        ols_model = sm.OLS(log_price_a.values, X).fit()
        alpha = float(ols_model.params[0])
        beta = float(ols_model.params[1])
        r_squared = float(ols_model.rsquared)

        # Spread residual
        spread = log_price_a.values - alpha - beta * log_price_b.values

        # 3. Engle-Granger cointegration test (10 lags max for 5m intraday)
        coint_t, p_val, crit_vals = coint(log_price_a.values, log_price_b.values, trend="c", maxlag=10, autolag="aic")

        # 4. ADF test on spread residuals directly
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=FutureWarning)
            adf_result = adfuller(spread, maxlag=10, autolag="aic")
        adf_stat = float(adf_result[0])
        adf_p = float(adf_result[1])

        # 5. Ornstein-Uhlenbeck Half-Life
        half_life_bars, lambda_coef = calculate_half_life(spread)
        half_life_hours = half_life_bars * 5.0 / 60.0 if np.isfinite(half_life_bars) else np.inf

        return {
            "correlation": corr,
            "beta": beta,
            "alpha": alpha,
            "r_squared": r_squared,
            "coint_t_stat": float(coint_t),
            "p_value": float(p_val),
            "crit_value_1%": float(crit_vals[0]),
            "crit_value_5%": float(crit_vals[1]),
            "crit_value_10%": float(crit_vals[2]),
            "adf_t_stat": adf_stat,
            "adf_p_value": adf_p,
            "half_life_bars": half_life_bars,
            "half_life_hours": half_life_hours,
            "spread_std": float(np.std(spread)),
            "spread_mean": float(np.mean(spread))
        }

    def screen_universe(
        self,
        aligned_log_prices: pd.DataFrame,
        aligned_log_returns: pd.DataFrame,
        lookback_bars: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Screens all unique asset combinations in the universe.
        Applies Benjamini-Hochberg FDR correction and labels eligible pairs.
        """
        symbols = list(aligned_log_prices.columns)
        if len(symbols) < 2:
            raise ValueError("Need at least 2 assets to perform pair screening.")

        if lookback_bars is not None and len(aligned_log_prices) > lookback_bars:
            lp_window = aligned_log_prices.iloc[-lookback_bars:]
            lr_window = aligned_log_returns.iloc[-lookback_bars:]
        else:
            lp_window = aligned_log_prices
            lr_window = aligned_log_returns

        total_pairs = len(list(itertools.combinations(symbols, 2)))
        logger.info(f"Screening {len(symbols)} assets ({total_pairs} pairs) over {len(lp_window)} bars...")

        results = []
        for idx, (sym_a, sym_b) in enumerate(itertools.combinations(symbols, 2), 1):
            if idx % 10 == 0 or idx == total_pairs:
                logger.info(f"Screening progress: [{idx}/{total_pairs}] pairs evaluated...")
            try:
                metrics = self.analyze_pair(
                    log_price_a=lp_window[sym_a],
                    log_price_b=lp_window[sym_b],
                    log_returns_a=lr_window[sym_a],
                    log_returns_b=lr_window[sym_b]
                )
                metrics["asset_A"] = sym_a
                metrics["asset_B"] = sym_b
                metrics["pair"] = f"{sym_a}/{sym_b}"
                results.append(metrics)
            except Exception as e:
                logger.warning(f"Error analyzing pair {sym_a}/{sym_b}: {e}")

        if not results:
            return pd.DataFrame()

        df_results = pd.DataFrame(results)

        # Benjamini-Hochberg FDR correction on cointegration p-values
        adj_p, fdr_reject = benjamini_hochberg_correction(df_results["p_value"].tolist(), alpha=self.fdr_alpha)
        df_results["fdr_q_value"] = adj_p
        df_results["fdr_significant"] = fdr_reject

        # Evaluate eligibility criteria
        corr_pass = df_results["correlation"].abs() >= self.min_correlation
        coint_pass = df_results["p_value"] < self.coint_alpha
        beta_pass = df_results["beta"] > 0 if self.require_positive_beta else True
        hl_pass = (df_results["half_life_bars"] > 1.0) & (df_results["half_life_bars"] <= self.max_half_life_bars)

        df_results["eligible"] = corr_pass & coint_pass & beta_pass & hl_pass

        # Sort primarily by eligible (descending), then p-value (ascending)
        df_results.sort_values(by=["eligible", "p_value"], ascending=[False, True], inplace=True)
        df_results.reset_index(drop=True, inplace=True)

        output_path = self.processed_dir / "pair_screening_results.csv"
        df_results.to_csv(output_path, index=False)
        logger.info(f"Screening complete. Total pairs tested: {len(df_results)}. Eligible pairs: {df_results['eligible'].sum()}. Results saved to {output_path}")

        return df_results

    @staticmethod
    def validate_pair_count(pairs: Any) -> int:
        """
        Validates that no more than 2 pairs are ever picked or selected at once.
        Raises ValueError if the count exceeds 2.
        """
        if isinstance(pairs, int):
            count = pairs
        elif isinstance(pairs, (list, tuple, set)):
            count = len(pairs)
        elif isinstance(pairs, pd.DataFrame):
            count = len(pairs)
        else:
            try:
                count = int(pairs)
            except (TypeError, ValueError):
                count = 1

        if count > selection_config.max_selected_pairs:
            raise ValueError(
                f"Validation Error: Cannot pick more than {selection_config.max_selected_pairs} pairs at once (requested {count}). "
                f"Portfolio statistical risk policy strictly restricts concurrent pair selection to a maximum of 2 pairs."
            )
        return count

    def select_pairs(
        self,
        df_results: pd.DataFrame,
        max_pairs: int = selection_config.max_selected_pairs
    ) -> pd.DataFrame:
        """
        Picks the top cointegrated candidate pairs subject to a strict 2-pair validation ceiling.
        Raises ValueError if max_pairs > 2.
        """
        self.validate_pair_count(max_pairs)

        if df_results.empty:
            return pd.DataFrame()

        # Prioritize statistically eligible pairs
        if "eligible" in df_results.columns and df_results["eligible"].any():
            candidates = df_results[df_results["eligible"] == True].copy()
        else:
            candidates = df_results.copy()

        # Sort by cointegration strength (lowest p-value / highest absolute t-stat)
        if "p_value" in candidates.columns:
            candidates.sort_values(by="p_value", ascending=True, inplace=True)

        selected = candidates.head(max_pairs).copy()
        selected.reset_index(drop=True, inplace=True)
        return selected
