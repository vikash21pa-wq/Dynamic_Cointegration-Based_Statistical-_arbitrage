"""
Backtesting Engine for Statistical Arbitrage Strategies.
Simulates execution bar-by-bar with zero lookahead bias, realistic notional sizing,
taker fees, slippage, and perpetual funding costs.
"""

from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pandas as pd

from config import trading_config, selection_config, market_config
from src.signals import SignalGenerator
from src.execution import ExecutionEngine
from src.kalman_filter import KalmanHedgeRatioFilter
from src.performance import PerformanceAnalyzer


class PairsBacktester:
    """
    Simulates statistical arbitrage on paired cryptocurrency time series.
    Supports both static OLS and dynamic Kalman Filter models.
    """

    def __init__(
        self,
        initial_capital: float = trading_config.initial_capital,
        pair_allocation: float = trading_config.pair_gross_allocation,
        fee_pct: float = trading_config.taker_fee_pct,
        slippage_pct: float = trading_config.slippage_pct,
        funding_rate_8h: float = trading_config.default_funding_rate_8h,
        zscore_window: int = trading_config.zscore_window,
        entry_threshold: float = trading_config.zscore_entry,
        exit_threshold: float = trading_config.zscore_exit,
        emergency_threshold: float = trading_config.zscore_emergency_stop,
        max_holding_bars: int = trading_config.max_holding_period_bars
    ):
        self.initial_capital = initial_capital
        self.pair_allocation = pair_allocation
        self.signal_generator = SignalGenerator(
            window=zscore_window,
            entry_threshold=entry_threshold,
            exit_threshold=exit_threshold,
            emergency_threshold=emergency_threshold,
            max_holding_bars=max_holding_bars
        )
        self.execution_engine = ExecutionEngine(
            fee_pct=fee_pct,
            slippage_pct=slippage_pct,
            funding_rate_8h=funding_rate_8h
        )
        self.performance_analyzer = PerformanceAnalyzer()

    def run_pair_simulation(
        self,
        price_a: pd.Series,
        price_b: pd.Series,
        alpha: float,
        beta: float,
        pair_name: str = "A/B",
        use_kalman: bool = False
    ) -> Dict[str, Any]:
        """
        Runs detailed simulation for a single pair.

        Args:
            price_a: Close prices of Asset A
            price_b: Close prices of Asset B
            alpha: Initial or static intercept
            beta: Initial or static hedge ratio
            use_kalman: If True, uses dynamic Kalman Filter to track alpha and beta
        """
        log_a = np.log(price_a)
        log_b = np.log(price_b)
        n = len(price_a)

        # 1. Spread Calculation
        if use_kalman:
            kf = KalmanHedgeRatioFilter(initial_state=np.array([alpha, beta]))
            alphas, betas, spreads = kf.filter_series(log_a.values, log_b.values)
            spread_series = pd.Series(spreads, index=price_a.index)
            beta_series = pd.Series(betas, index=price_a.index)
            alpha_series = pd.Series(alphas, index=price_a.index)
        else:
            spread_values = log_a.values - alpha - beta * log_b.values
            spread_series = pd.Series(spread_values, index=price_a.index)
            beta_series = pd.Series(beta, index=price_a.index)
            alpha_series = pd.Series(alpha, index=price_a.index)

        # 2. Rolling Z-Score
        zscore, rolling_mean, rolling_std = self.signal_generator.compute_zscore(spread_series)

        # 3. Position Signals (calculated at close of bar t)
        signal_df = self.signal_generator.generate_positions(zscore)
        signals = signal_df["position"]

        # 4. Simulation tracking arrays
        equity = np.zeros(n)
        equity[0] = self.initial_capital
        cash = self.initial_capital

        notional_a = np.zeros(n)
        notional_b = np.zeros(n)
        costs_paid = np.zeros(n)
        funding_paid = np.zeros(n)
        bar_pnl = np.zeros(n)

        p_a = price_a.values
        p_b = price_b.values
        betas_val = beta_series.values

        trades = []
        current_trade = None

        # 5. Bar-by-bar execution loop (Zero lookahead: signal at t-1 dictates execution at t)
        for t in range(1, n):
            target_pos = signals.iloc[t - 1]  # Signal generated at close of previous candle
            curr_beta = betas_val[t - 1]
            gross_cap = equity[t - 1] * self.pair_allocation

            # Desired notionals
            target_notional_a, target_notional_b = self.execution_engine.compute_leg_notionals(
                gross_capital=gross_cap,
                beta=curr_beta,
                position_state=target_pos
            )

            # Execution turnover and transaction costs
            turnover, cost = self.execution_engine.calculate_turnover_and_costs(
                prev_notional_a=notional_a[t - 1],
                curr_notional_a=target_notional_a,
                prev_notional_b=notional_b[t - 1],
                curr_notional_b=target_notional_b
            )
            costs_paid[t] = cost

            # Funding rate (every 8 hours = every 96 5-minute bars)
            is_funding_bar = (t % 96 == 0)
            fund = self.execution_engine.calculate_funding_cost(
                target_notional_a, target_notional_b, is_funding_bar=is_funding_bar
            )
            funding_paid[t] = fund

            # PnL from price movements of existing position held over interval [t-1, t]
            ret_a = (p_a[t] - p_a[t - 1]) / p_a[t - 1]
            ret_b = (p_b[t] - p_b[t - 1]) / p_b[t - 1]
            pnl_gross = (notional_a[t - 1] * ret_a) + (notional_b[t - 1] * ret_b)
            pnl_net = pnl_gross - cost + fund
            bar_pnl[t] = pnl_net

            # Update equity
            equity[t] = equity[t - 1] + pnl_net

            # Update active notionals
            notional_a[t] = target_notional_a
            notional_b[t] = target_notional_b

            # Trade bookkeeping
            prev_pos = signals.iloc[t - 2] if t >= 2 else 0
            if prev_pos == 0 and target_pos != 0:
                current_trade = {
                    "entry_bar": t,
                    "entry_time": price_a.index[t],
                    "pair": pair_name,
                    "side": "LONG_SPREAD" if target_pos == 1 else "SHORT_SPREAD",
                    "entry_price_a": p_a[t],
                    "entry_price_b": p_b[t],
                    "beta": curr_beta,
                    "pnl": -cost + fund,
                    "costs": cost
                }
            elif prev_pos != 0 and target_pos == 0 and current_trade is not None:
                current_trade["exit_bar"] = t
                current_trade["exit_time"] = price_a.index[t]
                current_trade["exit_price_a"] = p_a[t]
                current_trade["exit_price_b"] = p_b[t]
                current_trade["holding_bars"] = t - current_trade["entry_bar"]
                current_trade["pnl"] += pnl_gross - cost + fund
                current_trade["costs"] += cost
                trades.append(current_trade)
                current_trade = None
            elif current_trade is not None:
                current_trade["pnl"] += pnl_gross - cost + fund
                current_trade["costs"] += cost

        equity_series = pd.Series(equity, index=price_a.index)
        bar_returns = equity_series.pct_change().fillna(0.0)
        trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()

        metrics = self.performance_analyzer.calculate_metrics(
            equity_series=equity_series,
            bar_returns=bar_returns,
            trades_df=trades_df,
            total_costs=float(costs_paid.sum()),
            initial_capital=self.initial_capital
        )

        history_df = pd.DataFrame({
            "close_a": price_a,
            "close_b": price_b,
            "spread": spread_series,
            "zscore": zscore,
            "beta": beta_series,
            "signal": signals,
            "notional_a": notional_a,
            "notional_b": notional_b,
            "costs": costs_paid,
            "funding": funding_paid,
            "bar_pnl": bar_pnl,
            "equity": equity_series
        }, index=price_a.index)

        return {
            "metrics": metrics,
            "history": history_df,
            "trades": trades_df,
            "pair": pair_name
        }
