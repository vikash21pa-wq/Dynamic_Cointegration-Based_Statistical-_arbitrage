"""
Risk Management and Breakdown Detection Engine.
Monitors statistical degradation, portfolio drawdown circuit breakers,
and relationship stability for pairs.
"""

from typing import Dict, Any, Optional, Tuple
import numpy as np
import pandas as pd

from config import trading_config, selection_config


class RiskManager:
    """
    Supervises portfolio health, pair-level drawdown limits, and statistical degradation.
    """

    def __init__(
        self,
        max_portfolio_drawdown: float = trading_config.max_portfolio_drawdown,
        max_active_pairs: int = trading_config.max_active_pairs,
        coint_pvalue_breakdown: float = 0.15,
        spread_vol_expansion_factor: float = 2.5
    ):
        self.max_portfolio_drawdown = max_portfolio_drawdown
        self.max_active_pairs = min(max_active_pairs, trading_config.max_active_pairs)
        self.coint_pvalue_breakdown = coint_pvalue_breakdown
        self.spread_vol_expansion_factor = spread_vol_expansion_factor

    def validate_active_pairs(self, active_pairs: Any) -> Tuple[bool, str]:
        """
        Validates that the number of active pairs does not exceed the strict limit of 2 pairs.
        Returns:
            (is_valid, message)
        """
        if isinstance(active_pairs, (list, tuple, set, dict)):
            count = len(active_pairs)
        else:
            try:
                count = int(active_pairs)
            except (TypeError, ValueError):
                count = 1

        if count > self.max_active_pairs:
            return (
                False,
                f"Risk Validation Breach: Cannot pick or trade {count} active pairs simultaneously. "
                f"Maximum allowed limit is {self.max_active_pairs} pairs at once."
            )
        return True, "OK"

    def validate_pair_correlation(self, corr: float) -> Tuple[bool, str]:
        """
        Validates that a pair's correlation falls within the target range [0.89, 0.97].
        """
        min_c = getattr(trading_config, "target_correlation_min", 0.89)
        max_c = getattr(trading_config, "target_correlation_max", 0.97)
        abs_c = abs(float(corr))
        if abs_c < min_c or abs_c > max_c:
            return False, f"Pair correlation {abs_c:.4f} outside policy window [{min_c:.2f}, {max_c:.2f}]."
        return True, "OK"

    def validate_spread_quality(
        self,
        spread_std: float,
        half_life_hours: float,
        p_value: float = 0.01
    ) -> Tuple[bool, str]:
        """
        Validates spread quality between pair assets:
        1. Volatility floor (>= 0.0020 or 0.20%) to guarantee edge exceeds round-trip fee friction.
        2. Volatility ceiling (<= 0.1500 or 15.0%) to prevent trading in diverging/exploding spreads.
        3. Finite mean-reversion speed (0 < half_life_hours <= 36.0h).
        4. Cointegration stationarity (p_value < 0.05).
        """
        min_std = getattr(trading_config, "min_spread_std", 0.0020)
        max_std = getattr(selection_config, "max_spread_std", 0.1500)
        max_hl = getattr(selection_config, "max_half_life_hours", 36.0)
        coint_alpha = getattr(selection_config, "cointegration_alpha", 0.05)

        if np.isnan(spread_std) or np.isinf(spread_std) or spread_std < min_std:
            return False, f"Spread volatility too low ({spread_std:.5f} < {min_std:.4f}); insufficient to cover friction."
        if spread_std > max_std:
            return False, f"Spread volatility too high ({spread_std:.4f} > {max_std:.4f}); structural instability."
        if np.isnan(half_life_hours) or np.isinf(half_life_hours) or half_life_hours <= 0:
            return False, f"Invalid or non-reverting half-life ({half_life_hours})."
        if half_life_hours > max_hl:
            return False, f"Half-life too slow ({half_life_hours:.1f}h > {max_hl:.1f}h)."
        if p_value >= coint_alpha:
            return False, f"Cointegration p-value ({p_value:.4f}) does not meet stationarity threshold (< {coint_alpha:.2f})."
        return True, "GOOD_SPREAD"

    def can_open_new_pair(self, current_active_count: int) -> Tuple[bool, str]:
        """
        Validates whether a new pair can be opened or picked without exceeding the 2-pair limit.
        """
        if current_active_count >= self.max_active_pairs:
            return (
                False,
                f"Cannot pick or open new pair: currently {current_active_count} active pairs open. "
                f"Hard ceiling is {self.max_active_pairs} pairs at once."
            )
        return True, "OK"

    def check_portfolio_drawdown(self, equity_curve: pd.Series) -> Tuple[bool, float]:
        """
        Calculates high-water mark and current drawdown.
        Returns:
            (is_breached, current_drawdown)
        """
        if len(equity_curve) < 2:
            return False, 0.0

        peak = equity_curve.cummax()
        drawdown = (equity_curve - peak) / peak
        curr_dd = float(drawdown.iloc[-1])

        is_breached = curr_dd <= -self.max_portfolio_drawdown
        return is_breached, curr_dd

    def detect_relationship_breakdown(
        self,
        rolling_p_value: float,
        current_spread_std: float,
        baseline_spread_std: float,
        current_half_life: float,
        pair_unrealized_pnl_pct: float = 0.0
    ) -> Tuple[bool, str]:
        """
        Evaluates whether a pair's statistical relationship has deteriorated.

        Returns:
            (is_broken, reason)
        """
        reasons = []

        if rolling_p_value > self.coint_pvalue_breakdown:
            reasons.append(f"Cointegration p-value deteriorated to {rolling_p_value:.3f}")

        if baseline_spread_std > 0 and (current_spread_std > baseline_spread_std * self.spread_vol_expansion_factor):
            reasons.append(f"Spread volatility expanded {current_spread_std / baseline_spread_std:.1f}x")

        if np.isinf(current_half_life) or current_half_life > selection_config.max_half_life_bars * 1.5:
            reasons.append("Spread lost mean-reverting property (infinite or excessive half-life)")

        if pair_unrealized_pnl_pct <= -0.05:  # -5% single-pair stop loss
            reasons.append(f"Pair drawdown breached stop loss ({pair_unrealized_pnl_pct*100:.1f}%)")

        is_broken = len(reasons) >= 2 or pair_unrealized_pnl_pct <= -0.05
        return is_broken, "; ".join(reasons) if reasons else "STABLE"
