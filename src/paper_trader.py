"""
Real-Time Paper Trading Engine for Cryptocurrency Statistical Arbitrage.
Manages virtual portfolio, order execution simulation with fees/slippage,
real-time spread Z-score state machine, and ledger persistence.
"""

import json
import logging
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd
import requests

from config import (
    paper_config,
    trading_config,
    PROCESSED_DATA_DIR,
    RESULTS_DIR
)

logger = logging.getLogger("PaperTrader")


@dataclass
class Position:
    symbol: str
    side: str  # "LONG" or "SHORT"
    contracts: float
    entry_price: float
    notional: float
    entry_time: str


class PaperAccount:
    """
    Virtual margin account tracking balances, margin requirements,
    open positions, and trade history.
    """

    def __init__(
        self,
        initial_balance: float = 10000.0,
        fee_pct: float = trading_config.taker_fee_pct,
        slippage_pct: float = trading_config.slippage_pct
    ):
        self.initial_balance = initial_balance
        self.cash_balance = initial_balance
        self.fee_pct = fee_pct
        self.slippage_pct = slippage_pct
        self.positions: Dict[str, Position] = {}
        self.closed_trades: List[Dict[str, Any]] = []
        self.total_fees_paid: float = 0.0
        self.realized_pnl: float = 0.0

    def get_unrealized_pnl(self, current_prices: Dict[str, float]) -> float:
        """Calculates mark-to-market unrealized PnL across all open legs."""
        unrealized = 0.0
        for symbol, pos in self.positions.items():
            if symbol not in current_prices:
                continue
            curr_p = current_prices[symbol]
            if pos.side == "LONG":
                leg_pnl = pos.contracts * (curr_p - pos.entry_price)
            else:
                leg_pnl = pos.contracts * (pos.entry_price - curr_p)
            unrealized += leg_pnl
        return unrealized

    def get_total_equity(self, current_prices: Dict[str, float]) -> float:
        return self.cash_balance + self.get_unrealized_pnl(current_prices)

    def execute_fill(
        self,
        symbol: str,
        side: str,
        contracts: float,
        market_price: float,
        timestamp_str: str
    ) -> Dict[str, Any]:
        """
        Executes a simulated fill including slippage and taker fees.
        """
        slip_direction = 1.0 if side == "BUY" else -1.0
        fill_price = market_price * (1.0 + slip_direction * self.slippage_pct)
        fill_notional = contracts * fill_price
        fee = fill_notional * self.fee_pct

        self.cash_balance -= fee
        self.total_fees_paid += fee

        return {
            "symbol": symbol,
            "side": side,
            "contracts": contracts,
            "requested_price": market_price,
            "fill_price": fill_price,
            "notional": fill_notional,
            "fee": fee,
            "timestamp": timestamp_str
        }


class PaperTradingEngine:
    """
    Automated pairs statistical arbitrage paper trading bot.
    Operates an online state machine using Engle-Granger / OLS spread parameters.
    """

    def __init__(
        self,
        pair: str = "BTCUSDT/ETHUSDT",
        initial_capital: float = 10000.0,
        allocation_pct: float = trading_config.pair_gross_allocation,
        zscore_window: int = trading_config.zscore_window,
        entry_threshold: float = trading_config.zscore_entry,
        exit_threshold: float = trading_config.zscore_exit,
        emergency_threshold: float = trading_config.zscore_emergency_stop,
        alpha: Optional[float] = None,
        beta: Optional[float] = None,
        results_dir: Path = RESULTS_DIR
    ):
        parts = pair.replace("-", "/").split("/")
        self.asset_a = parts[0].upper()
        self.asset_b = parts[1].upper()
        self.pair_name = f"{self.asset_a}/{self.asset_b}"
        self.allocation_pct = allocation_pct
        self.zscore_window = zscore_window
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.emergency_threshold = emergency_threshold
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)

        self.account = PaperAccount(initial_balance=initial_capital)
        self.spread_history: List[float] = []
        self.current_position_state: int = 0  # 0: Flat, +1: Long spread, -1: Short spread
        self.bars_in_trade: int = 0
        self.current_trade_meta: Optional[Dict[str, Any]] = None

        # Load calibrated parameters from summary if not specified
        if alpha is None or beta is None:
            self.alpha, self.beta = self._load_calibrated_parameters()
        else:
            self.alpha = alpha
            self.beta = beta

        # Warm up spread history with recent aligned matrix if present
        self._warmup_spread_history()

    def _load_calibrated_parameters(self) -> Tuple[float, float]:
        """Loads static cointegration alpha and beta from previous screening."""
        screening_file = self.results_dir / "pair_screening_results.csv"
        if not screening_file.exists():
            screening_file = PROCESSED_DATA_DIR / "pair_screening_results.csv"

        if screening_file.exists():
            try:
                df = pd.read_csv(screening_file)
                match = df[df["pair"] == self.pair_name]
                if not match.empty:
                    alpha = float(match.iloc[0]["alpha"])
                    beta = float(match.iloc[0]["beta"])
                    logger.info(f"Loaded calibrated parameters for {self.pair_name}: Alpha={alpha:.4f}, Beta={beta:.4f}")
                    return alpha, beta
            except Exception as e:
                logger.warning(f"Could not load screening parameters: {e}")

        # Default fallback calibrated parameters for BTC/ETH
        logger.info(f"Using default parameters for {self.pair_name}: Alpha=1.4648, Beta=1.1678")
        return 1.4648, 1.1678

    def _warmup_spread_history(self):
        """Initializes rolling spread buffer with the most recent bars."""
        aligned_path = PROCESSED_DATA_DIR / "aligned_close_prices.csv"
        if aligned_path.exists():
            try:
                df = pd.read_csv(aligned_path)
                if self.asset_a in df.columns and self.asset_b in df.columns:
                    p_a = df[self.asset_a].values[-self.zscore_window:]
                    p_b = df[self.asset_b].values[-self.zscore_window:]
                    spreads = np.log(p_a) - self.alpha - self.beta * np.log(p_b)
                    self.spread_history = list(spreads)
                    logger.info(f"Warmed up spread buffer with {len(self.spread_history)} historical bars.")
            except Exception as e:
                logger.warning(f"Could not warm up spread history: {e}")

    def fetch_live_prices(self) -> Tuple[Optional[float], Optional[float]]:
        """
        Fetches current market mid-prices for Asset A and Asset B from Binance.
        Uses public REST ticker endpoints (no authentication required).
        """
        url = "https://fapi.binance.com/fapi/v1/ticker/bookTicker"
        prices = {}
        for sym in [self.asset_a, self.asset_b]:
            try:
                resp = requests.get(url, params={"symbol": sym}, timeout=3)
                if resp.status_code == 200:
                    data = resp.json()
                    bid = float(data["bidPrice"])
                    ask = float(data["askPrice"])
                    prices[sym] = (bid + ask) / 2.0
            except Exception:
                pass

        return prices.get(self.asset_a), prices.get(self.asset_b)

    def process_tick(
        self,
        price_a: float,
        price_b: float,
        timestamp_str: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Ingests a new market price tick for Asset A & Asset B,
        calculates Z-score, updates state machine, and executes paper orders.
        """
        if timestamp_str is None:
            timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        current_prices = {self.asset_a: price_a, self.asset_b: price_b}

        # 1. Compute spread
        current_spread = float(np.log(price_a) - self.alpha - self.beta * np.log(price_b))
        self.spread_history.append(current_spread)
        if len(self.spread_history) > self.zscore_window:
            self.spread_history.pop(0)

        # 2. Compute rolling Z-score
        spread_arr = np.array(self.spread_history)
        rolling_mean = float(np.mean(spread_arr))
        rolling_std = float(np.std(spread_arr))
        zscore = float((current_spread - rolling_mean) / rolling_std) if rolling_std > 1e-8 else 0.0

        # 3. State machine logic
        action_taken = "HOLD"
        reason = ""

        if self.current_position_state == 0:
            # Check entry
            if zscore <= -self.entry_threshold:
                # Undervalued spread -> Long spread (Buy A, Sell B)
                self._open_spread_position(target_state=1, price_a=price_a, price_b=price_b, timestamp_str=timestamp_str)
                action_taken = "OPEN_LONG_SPREAD"
                reason = f"Z-score {zscore:.2f} <= -{self.entry_threshold}"
            elif zscore >= self.entry_threshold:
                # Overvalued spread -> Short spread (Sell A, Buy B)
                self._open_spread_position(target_state=-1, price_a=price_a, price_b=price_b, timestamp_str=timestamp_str)
                action_taken = "OPEN_SHORT_SPREAD"
                reason = f"Z-score {zscore:.2f} >= +{self.entry_threshold}"
        else:
            self.bars_in_trade += 1
            # Check exit
            should_exit = False
            exit_reason = ""

            if self.current_position_state == 1:
                if zscore >= -self.exit_threshold:
                    should_exit = True
                    exit_reason = f"Mean convergence reached (Z={zscore:.2f} >= -{self.exit_threshold})"
                elif zscore <= -self.emergency_threshold:
                    should_exit = True
                    exit_reason = f"Emergency stop triggered (Z={zscore:.2f} <= -{self.emergency_threshold})"
            elif self.current_position_state == -1:
                if zscore <= self.exit_threshold:
                    should_exit = True
                    exit_reason = f"Mean convergence reached (Z={zscore:.2f} <= {self.exit_threshold})"
                elif zscore >= self.emergency_threshold:
                    should_exit = True
                    exit_reason = f"Emergency stop triggered (Z={zscore:.2f} >= {self.emergency_threshold})"

            if should_exit:
                self._close_spread_position(price_a=price_a, price_b=price_b, timestamp_str=timestamp_str, reason=exit_reason)
                action_taken = "CLOSE_SPREAD"
                reason = exit_reason

        # 4. Compile live snapshot
        unrealized = self.account.get_unrealized_pnl(current_prices)
        total_equity = self.account.get_total_equity(current_prices)
        total_pnl = total_equity - self.account.initial_balance
        pnl_pct = (total_pnl / self.account.initial_balance) * 100.0

        snapshot = {
            "timestamp": timestamp_str,
            "pair": self.pair_name,
            "price_a": price_a,
            "price_b": price_b,
            "spread": current_spread,
            "rolling_mean": rolling_mean,
            "rolling_std": rolling_std,
            "zscore": zscore,
            "position_state": self.current_position_state,
            "action": action_taken,
            "reason": reason,
            "cash_balance": self.account.cash_balance,
            "unrealized_pnl": unrealized,
            "realized_pnl": self.account.realized_pnl,
            "total_equity": total_equity,
            "pnl_pct": pnl_pct,
            "total_trades": len(self.account.closed_trades),
            "fees_paid": self.account.total_fees_paid
        }

        self._save_state(snapshot)
        return snapshot

    def _open_spread_position(self, target_state: int, price_a: float, price_b: float, timestamp_str: str):
        """Sizes and fills both legs for spread entry."""
        gross_budget = self.account.cash_balance * self.allocation_pct
        notional_a_target = gross_budget / (1.0 + abs(self.beta))
        notional_b_target = (abs(self.beta) * gross_budget) / (1.0 + abs(self.beta))

        contracts_a = notional_a_target / price_a
        contracts_b = notional_b_target / price_b

        side_a = "BUY" if target_state == 1 else "SELL"
        side_b = "SELL" if target_state == 1 else "BUY"

        fill_a = self.account.execute_fill(self.asset_a, side_a, contracts_a, price_a, timestamp_str)
        fill_b = self.account.execute_fill(self.asset_b, side_b, contracts_b, price_b, timestamp_str)

        self.account.positions[self.asset_a] = Position(
            symbol=self.asset_a,
            side="LONG" if side_a == "BUY" else "SHORT",
            contracts=contracts_a,
            entry_price=fill_a["fill_price"],
            notional=fill_a["notional"],
            entry_time=timestamp_str
        )
        self.account.positions[self.asset_b] = Position(
            symbol=self.asset_b,
            side="LONG" if side_b == "BUY" else "SHORT",
            contracts=contracts_b,
            entry_price=fill_b["fill_price"],
            notional=fill_b["notional"],
            entry_time=timestamp_str
        )

        self.current_position_state = target_state
        self.bars_in_trade = 0
        self.current_trade_meta = {
            "entry_time": timestamp_str,
            "position_state": target_state,
            "entry_price_a": fill_a["fill_price"],
            "entry_price_b": fill_b["fill_price"],
            "contracts_a": contracts_a,
            "contracts_b": contracts_b,
            "entry_fees": fill_a["fee"] + fill_b["fee"]
        }
        logger.info(f"[{timestamp_str}] OPENED {('LONG' if target_state==1 else 'SHORT')} SPREAD | "
                    f"{self.asset_a}: {side_a} {contracts_a:.4f} @ ${fill_a['fill_price']:,.2f} | "
                    f"{self.asset_b}: {side_b} {contracts_b:.4f} @ ${fill_b['fill_price']:,.2f}")

    def _close_spread_position(self, price_a: float, price_b: float, timestamp_str: str, reason: str):
        """Liquidates both legs for spread exit and records trade PnL."""
        pos_a = self.account.positions.pop(self.asset_a)
        pos_b = self.account.positions.pop(self.asset_b)

        close_side_a = "SELL" if pos_a.side == "LONG" else "BUY"
        close_side_b = "SELL" if pos_b.side == "LONG" else "BUY"

        fill_a = self.account.execute_fill(self.asset_a, close_side_a, pos_a.contracts, price_a, timestamp_str)
        fill_b = self.account.execute_fill(self.asset_b, close_side_b, pos_b.contracts, price_b, timestamp_str)

        if pos_a.side == "LONG":
            gross_pnl_a = pos_a.contracts * (fill_a["fill_price"] - pos_a.entry_price)
        else:
            gross_pnl_a = pos_a.contracts * (pos_a.entry_price - fill_a["fill_price"])

        if pos_b.side == "LONG":
            gross_pnl_b = pos_b.contracts * (fill_b["fill_price"] - pos_b.entry_price)
        else:
            gross_pnl_b = pos_b.contracts * (pos_b.entry_price - fill_b["fill_price"])

        total_gross_pnl = gross_pnl_a + gross_pnl_b
        exit_fees = fill_a["fee"] + fill_b["fee"]
        entry_fees = self.current_trade_meta["entry_fees"] if self.current_trade_meta else 0.0
        total_trade_fees = entry_fees + exit_fees
        net_trade_pnl = total_gross_pnl - total_trade_fees

        self.account.cash_balance += total_gross_pnl
        self.account.realized_pnl += net_trade_pnl

        trade_record = {
            "pair": self.pair_name,
            "direction": "LONG_SPREAD" if self.current_position_state == 1 else "SHORT_SPREAD",
            "entry_time": self.current_trade_meta["entry_time"] if self.current_trade_meta else "N/A",
            "exit_time": timestamp_str,
            "exit_reason": reason,
            "holding_ticks": self.bars_in_trade,
            "gross_pnl": total_gross_pnl,
            "fees_paid": total_trade_fees,
            "net_pnl": net_trade_pnl,
            "account_equity": self.account.cash_balance
        }
        self.account.closed_trades.append(trade_record)

        self.current_position_state = 0
        self.bars_in_trade = 0
        self.current_trade_meta = None

        logger.info(f"[{timestamp_str}] CLOSED SPREAD ({reason}) | Net PnL: ${net_trade_pnl:+,.2f} | Equity: ${self.account.cash_balance:,.2f}")

    def _save_state(self, snapshot: Dict[str, Any]):
        """Persists live state and trade logs to disk."""
        state_file = self.results_dir / "paper_trading_state.json"
        with open(state_file, "w") as f:
            json.dump(snapshot, f, indent=4)

        if self.account.closed_trades:
            trades_df = pd.DataFrame(self.account.closed_trades)
            trades_df.to_csv(self.results_dir / "paper_trades.csv", index=False)

