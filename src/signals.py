"""
Signal Generation Module.
Computes rolling Z-scores, crossing-based entry and exit signals,
emergency stops, and time-based exits with strict next-bar execution guarantees.
"""

from typing import Tuple, Optional
import numpy as np
import pandas as pd

from config import trading_config


class SignalGenerator:
    """
    State-machine based signal generator for statistical arbitrage spreads.
    """

    def __init__(
        self,
        window: int = trading_config.zscore_window,
        entry_threshold: float = trading_config.zscore_entry,
        exit_threshold: float = trading_config.zscore_exit,
        emergency_threshold: float = trading_config.zscore_emergency_stop,
        max_holding_bars: int = trading_config.max_holding_period_bars
    ):
        self.window = window
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.emergency_threshold = emergency_threshold
        self.max_holding_bars = max_holding_bars

    def compute_zscore(self, spread: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Computes non-lookahead rolling mean, rolling std, and Z-score:
            Z_t = (S_t - mu_t) / sigma_t
        """
        rolling_mean = spread.rolling(window=self.window, min_periods=max(20, self.window // 4)).mean()
        rolling_std = spread.rolling(window=self.window, min_periods=max(20, self.window // 4)).std()

        # Handle zero or tiny std
        safe_std = rolling_std.replace(0, np.nan)
        zscore = (spread - rolling_mean) / safe_std
        return zscore, rolling_mean, rolling_std

    def generate_positions(self, zscore: pd.Series) -> pd.DataFrame:
        """
        State machine tracking position state bar-by-bar:
            0: Flat
           +1: Long spread (Long A, Short B)
           -1: Short spread (Short A, Long B)

        Returns DataFrame containing:
            position: finalized position at bar close
            action: 1 (open long), -1 (open short), 0 (hold), 2 (exit)
            holding_bars: bars elapsed in active position
        """
        n = len(zscore)
        positions = np.zeros(n, dtype=int)
        actions = np.zeros(n, dtype=int)
        holding_bars = np.zeros(n, dtype=int)
        exit_reasons = [""] * n

        z_vals = zscore.values
        current_pos = 0
        bars_held = 0

        for i in range(1, n):
            z_curr = z_vals[i]
            z_prev = z_vals[i - 1]

            if np.isnan(z_curr) or np.isnan(z_prev):
                positions[i] = 0
                continue

            target_pos = current_pos
            action = 0
            reason = ""

            if current_pos == 0:
                # Potential Entry
                if (z_prev < self.entry_threshold) and (z_curr >= self.entry_threshold):
                    # Spread too high -> Short Spread
                    target_pos = -1
                    action = -1
                    bars_held = 0
                    reason = "ENTER_SHORT_SPREAD"
                elif (z_prev > -self.entry_threshold) and (z_curr <= -self.entry_threshold):
                    # Spread too low -> Long Spread
                    target_pos = 1
                    action = 1
                    bars_held = 0
                    reason = "ENTER_LONG_SPREAD"

            elif current_pos == 1:
                bars_held += 1
                # Exit condition: Z converges back towards mean (>= -exit_threshold)
                if z_curr >= -self.exit_threshold:
                    target_pos = 0
                    action = 2
                    reason = "EXIT_MEAN_REVERSION"
                    bars_held = 0
                # Emergency Stop: Spread diverges further
                elif z_curr <= -self.emergency_threshold:
                    target_pos = 0
                    action = 2
                    reason = "EXIT_EMERGENCY_DIVERGENCE"
                    bars_held = 0
                # Time-based Exit: Held longer than max allowed bars
                elif bars_held >= self.max_holding_bars:
                    target_pos = 0
                    action = 2
                    reason = "EXIT_MAX_HOLDING_TIME"
                    bars_held = 0

            elif current_pos == -1:
                bars_held += 1
                # Exit condition: Z converges back towards mean (<= +exit_threshold)
                if z_curr <= self.exit_threshold:
                    target_pos = 0
                    action = 2
                    reason = "EXIT_MEAN_REVERSION"
                    bars_held = 0
                # Emergency Stop: Spread diverges further
                elif z_curr >= self.emergency_threshold:
                    target_pos = 0
                    action = 2
                    reason = "EXIT_EMERGENCY_DIVERGENCE"
                    bars_held = 0
                # Time-based Exit
                elif bars_held >= self.max_holding_bars:
                    target_pos = 0
                    action = 2
                    reason = "EXIT_MAX_HOLDING_TIME"
                    bars_held = 0

            current_pos = target_pos
            positions[i] = current_pos
            actions[i] = action
            holding_bars[i] = bars_held
            exit_reasons[i] = reason

        df_out = pd.DataFrame({
            "zscore": zscore,
            "position": positions,
            "action": actions,
            "holding_bars": holding_bars,
            "signal_reason": exit_reasons
        }, index=zscore.index)

        return df_out
