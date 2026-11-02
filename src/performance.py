"""
Performance Evaluation and Quantitative Metrics Module.
Calculates high-frequency annualized risk-adjusted ratios, drawdown analysis,
trade distribution statistics, and tear-sheet generation.
"""

from typing import Dict, Any, List
import numpy as np
import pandas as pd

from config import market_config


class PerformanceAnalyzer:
    """
    Computes rigorous quantitative finance metrics for high-frequency crypto trading systems.
    """

    def __init__(self, annualization_factor: int = market_config.annualization_factor, rf_rate: float = 0.0):
        self.annualization_factor = annualization_factor
        self.rf_rate = rf_rate

    def calculate_metrics(
        self,
        equity_series: pd.Series,
        bar_returns: pd.Series,
        trades_df: pd.DataFrame,
        total_costs: float = 0.0,
        initial_capital: float = 10000.0
    ) -> Dict[str, Any]:
        """
        Calculates all key statistical arbitrage research metrics.
        """
        if len(equity_series) < 2:
            return {"status": "INSUFFICIENT_DATA"}

        final_equity = float(equity_series.iloc[-1])
        total_net_return = (final_equity - initial_capital) / initial_capital

        n_bars = len(bar_returns)
        years = n_bars / self.annualization_factor
        ann_return = ((1.0 + total_net_return) ** (1.0 / max(years, 1e-4))) - 1.0 if total_net_return > -1.0 else -1.0

        # Mean and standard deviation of returns
        mean_ret = float(bar_returns.mean())
        std_ret = float(bar_returns.std())

        # Annualized Sharpe Ratio
        if std_ret > 1e-8:
            sharpe = np.sqrt(self.annualization_factor) * (mean_ret - (self.rf_rate / self.annualization_factor)) / std_ret
        else:
            sharpe = 0.0

        # Sortino Ratio (downside risk only)
        downside_returns = bar_returns[bar_returns < 0]
        downside_std = float(downside_returns.std()) if len(downside_returns) > 1 else 0.0
        if downside_std > 1e-8:
            sortino = np.sqrt(self.annualization_factor) * (mean_ret - (self.rf_rate / self.annualization_factor)) / downside_std
        else:
            sortino = 0.0

        # Maximum Drawdown
        peak = equity_series.cummax()
        drawdown_series = (equity_series - peak) / peak
        max_drawdown = float(drawdown_series.min())

        # Calmar Ratio
        calmar = (ann_return / abs(max_drawdown)) if abs(max_drawdown) > 1e-6 else 0.0

        # Trade analytics
        total_trades = len(trades_df) if trades_df is not None and not trades_df.empty else 0
        win_rate = 0.0
        profit_factor = 0.0
        avg_trade_pnl = 0.0
        avg_holding_bars = 0.0

        if total_trades > 0 and "pnl" in trades_df.columns:
            wins = trades_df[trades_df["pnl"] > 0]
            losses = trades_df[trades_df["pnl"] < 0]
            win_rate = len(wins) / total_trades
            gross_profit = float(wins["pnl"].sum())
            gross_loss = float(abs(losses["pnl"].sum()))
            profit_factor = (gross_profit / gross_loss) if gross_loss > 1e-6 else (np.inf if gross_profit > 0 else 0.0)
            avg_trade_pnl = float(trades_df["pnl"].mean())
            if "holding_bars" in trades_df.columns:
                avg_holding_bars = float(trades_df["holding_bars"].mean())

        return {
            "initial_capital": initial_capital,
            "final_equity": final_equity,
            "net_profit": final_equity - initial_capital,
            "total_net_return_pct": total_net_return * 100.0,
            "annualized_return_pct": ann_return * 100.0,
            "annualized_sharpe_ratio": float(sharpe),
            "annualized_sortino_ratio": float(sortino),
            "max_drawdown_pct": max_drawdown * 100.0,
            "calmar_ratio": float(calmar),
            "total_trades_completed": total_trades,
            "win_rate_pct": win_rate * 100.0,
            "profit_factor": float(profit_factor),
            "avg_trade_pnl": avg_trade_pnl,
            "avg_holding_bars": avg_holding_bars,
            "avg_holding_hours": avg_holding_bars * 5.0 / 60.0,
            "total_costs_paid": total_costs,
            "total_bars_simulated": n_bars
        }
