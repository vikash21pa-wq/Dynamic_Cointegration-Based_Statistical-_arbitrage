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

    def compute_risk_budgeted_notionals(
        self,
        equity: float,
        beta: float,
        spread_std: float,
        position_state: int,
        risk_budget_pct: float = 0.01,
        z_entry: float = trading_config.zscore_entry,
        z_stop: float = trading_config.zscore_emergency_stop,
        max_allocation_pct: float = trading_config.pair_gross_allocation,
        max_margin_utilization: float = 0.50
    ) -> Tuple[float, float, Dict[str, Any]]:
        """
        Calculates position sizes according to the Risk-Budget Sizing framework
        from Section 9 & 17 of the Research Blueprint:
            Position Size = Risk Budget / Estimated Loss per unit at stop
        
        Where:
            Risk Budget = Equity * risk_budget_pct (default: 1.0% maximum portfolio risk per trade)
            Estimated Loss at Stop = Delta Z_stop * spread_std + 2-leg round-trip friction
            Delta Z_stop = abs(z_stop - z_entry)
            
        Enforces:
            1. Risk Budget loss cap (loss at stop <= allowed portfolio risk)
            2. Gross capital ceiling (gross exposure <= max_allocation_pct * equity)
            3. Margin utilization cap (locked margin <= max_margin_utilization * equity)
            4. Beta-neutral leg distribution (N_A + N_B = G, N_A = G / (1 + |beta|))
        """
        if position_state == 0 or equity <= 0 or not np.isfinite(beta):
            return 0.0, 0.0, {}

        abs_beta = max(1e-4, abs(beta))

        # 1. Standard allocation ceiling
        max_gross_allowed = equity * max_allocation_pct

        # 2. Risk-budget sizing:
        # Loss at stop per dollar of spread notional:
        delta_z = max(0.5, abs(z_stop - z_entry))
        spread_loss_per_unit = (delta_z * max(1e-4, spread_std)) + (2.0 * self.total_cost_pct)
        risk_budget_dollars = equity * risk_budget_pct

        # Quantity / Gross notional derived from risk budget
        risk_budget_gross = risk_budget_dollars / spread_loss_per_unit

        # Final gross capital is constrained by the minimum of both bounds
        gross_capital = min(max_gross_allowed, risk_budget_gross, equity * max_margin_utilization)

        weight_a = 1.0 / (1.0 + abs_beta)
        weight_b = abs_beta / (1.0 + abs_beta)

        notional_a = gross_capital * weight_a
        notional_b = gross_capital * weight_b

        # Exposure diagnostics (Section 9)
        net_notional = notional_a - notional_b
        beta_adjusted_net = notional_a - (notional_b / abs_beta)

        meta = {
            "gross_notional": gross_capital,
            "risk_budget_dollars": risk_budget_dollars,
            "estimated_loss_at_stop": gross_capital * spread_loss_per_unit,
            "net_notional": net_notional,
            "beta_adjusted_net": beta_adjusted_net,
            "is_risk_budget_constrained": bool(risk_budget_gross < max_gross_allowed)
        }

        if position_state == 1:
            return notional_a, -notional_b, meta
        elif position_state == -1:
            return -notional_a, notional_b, meta
        return 0.0, 0.0, meta

    @staticmethod
    def compute_exposure_diagnostics(
        notional_a: float,
        notional_b: float,
        beta: float
    ) -> Dict[str, float]:
        """
        Calculates joint portfolio exposures as required by Section 9 of the Research Blueprint:
        - Gross notional: |N_A| + |N_B|
        - Dollar net notional: N_A + N_B
        - Beta-adjusted market net exposure: (beta * N_A) + N_B
        - Market neutrality ratio: |Beta Net| / Gross
        """
        gross = abs(notional_a) + abs(notional_b)
        dollar_net = notional_a + notional_b
        beta_net = (beta * notional_a) + notional_b
        neutrality_ratio = (abs(beta_net) / gross) if gross > 0 else 0.0
        return {
            "gross_notional": gross,
            "dollar_net": dollar_net,
            "beta_adjusted_net": beta_net,
            "market_neutrality_ratio": neutrality_ratio
        }

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
