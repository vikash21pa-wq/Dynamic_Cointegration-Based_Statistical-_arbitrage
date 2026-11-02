"""
Execution and Position Sizing Engine.
Handles dollar notional gross exposure allocation, contract sizing,
realistic turnover calculation, fee accounting, slippage, and funding rate deductions.
"""

from dataclasses import dataclass
from typing import Tuple, Dict, Any
import numpy as np
import pandas as pd

from config import trading_config


@dataclass
class TradeRecord:
    timestamp: Any
    pair: str
    action: str  # ENTER_LONG, ENTER_SHORT, EXIT
    price_a: float
    price_b: float
    units_a: float
    units_b: float
    notional_a: float
    notional_b: float
    costs: float
    reason: str


class ExecutionEngine:
    """
    Computes exact trade executions, notional allocations, and cost penalties.
    """

    def __init__(
        self,
        fee_pct: float = trading_config.taker_fee_pct,
        slippage_pct: float = trading_config.slippage_pct,
        funding_rate_8h: float = trading_config.default_funding_rate_8h
    ):
        self.fee_pct = fee_pct
        self.slippage_pct = slippage_pct
        self.total_cost_pct = fee_pct + slippage_pct
        self.funding_rate_8h = funding_rate_8h

    def compute_leg_notionals(
        self,
        gross_capital: float,
        beta: float,
        position_state: int
    ) -> Tuple[float, float]:
        """
        Calculates constrained gross exposure notionals for both legs:
            N_A = G / (1 + |beta|)
            N_B = |beta| * G / (1 + |beta|)
            N_A + N_B = G

        Returns:
            (signed_notional_A, signed_notional_B)
        """
        if position_state == 0 or gross_capital <= 0 or not np.isfinite(beta):
            return 0.0, 0.0

        abs_beta = max(1e-4, abs(beta))
        weight_a = 1.0 / (1.0 + abs_beta)
        weight_b = abs_beta / (1.0 + abs_beta)

        notional_a = gross_capital * weight_a
        notional_b = gross_capital * weight_b

        if position_state == 1:
            # Long spread: Long A, Short B
            return notional_a, -notional_b
        elif position_state == -1:
            # Short spread: Short A, Long B
            return -notional_a, notional_b
        else:
            return 0.0, 0.0

    def calculate_turnover_and_costs(
        self,
        prev_notional_a: float,
        curr_notional_a: float,
        prev_notional_b: float,
        curr_notional_b: float
    ) -> Tuple[float, float]:
        """
        Computes total traded turnover in dollars and associated trading fees + slippage.

        Returns:
            (total_turnover, total_cost_dollars)
        """
        turnover_a = abs(curr_notional_a - prev_notional_a)
        turnover_b = abs(curr_notional_b - prev_notional_b)
        total_turnover = turnover_a + turnover_b
        cost = total_turnover * self.total_cost_pct
        return total_turnover, cost

    def calculate_funding_cost(
        self,
        notional_a: float,
        notional_b: float,
        is_funding_bar: bool
    ) -> float:
        """
        Computes 8-hour perpetual funding payment:
            Funding Paid = (Long Notional - Short Notional) * funding_rate
        A negative value represents a cost/drain on capital.
        """
        if not is_funding_bar or (notional_a == 0.0 and notional_b == 0.0):
            return 0.0

        # Long positions pay funding rate (if rate > 0); short positions receive funding
        funding_a = -notional_a * self.funding_rate_8h
        funding_b = -notional_b * self.funding_rate_8h
        return funding_a + funding_b
