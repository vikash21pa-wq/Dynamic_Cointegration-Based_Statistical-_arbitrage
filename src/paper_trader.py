"""
Real-Time Paper Trading Engine for Cryptocurrency Statistical Arbitrage.
Manages virtual portfolio, order execution simulation with fees/slippage,
5-minute candle accumulator (Kline builder), real-time spread Z-score state machine,
and ledger persistence.
"""

import json
import logging
import math
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
    market_config,
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


@dataclass
class CandleBar:
    bar_id: int
    start_time: str
    close_time: str
    open_a: float
    high_a: float
    low_a: float
    close_a: float
    open_b: float
    high_b: float
    low_b: float
    close_b: float
    ticks: int
    close_spread: float


@dataclass(frozen=True)
class SymbolRules:
    step_size: float
    min_qty: float
    min_notional: float
    qty_precision: int
    price_precision: int


# Official Binance USDT-M Perpetual Futures Specifications for the Universe
BINANCE_FUTURES_RULES: Dict[str, SymbolRules] = {
    "BTCUSDT": SymbolRules(step_size=0.001, min_qty=0.001, min_notional=5.0, qty_precision=3, price_precision=1),
    "ETHUSDT": SymbolRules(step_size=0.001, min_qty=0.001, min_notional=5.0, qty_precision=3, price_precision=2),
    "BNBUSDT": SymbolRules(step_size=0.01, min_qty=0.01, min_notional=5.0, qty_precision=2, price_precision=2),
    "SOLUSDT": SymbolRules(step_size=0.01, min_qty=0.01, min_notional=5.0, qty_precision=2, price_precision=2),
    "XRPUSDT": SymbolRules(step_size=0.1, min_qty=0.1, min_notional=5.0, qty_precision=1, price_precision=4),
    "ADAUSDT": SymbolRules(step_size=1.0, min_qty=1.0, min_notional=5.0, qty_precision=0, price_precision=4),
    "DOGEUSDT": SymbolRules(step_size=1.0, min_qty=1.0, min_notional=5.0, qty_precision=0, price_precision=5),
    "LINKUSDT": SymbolRules(step_size=0.01, min_qty=0.01, min_notional=5.0, qty_precision=2, price_precision=3),
    "AVAXUSDT": SymbolRules(step_size=0.01, min_qty=0.01, min_notional=5.0, qty_precision=2, price_precision=3),
    "LTCUSDT": SymbolRules(step_size=0.001, min_qty=0.001, min_notional=5.0, qty_precision=3, price_precision=2),
}


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
    Operates a 5-minute candle accumulator (Kline builder) and online state machine
    using Engle-Granger / OLS spread parameters.
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
        candle_minutes: int = market_config.candle_minutes,
        alpha: Optional[float] = None,
        beta: Optional[float] = None,
        results_dir: Path = RESULTS_DIR,
        recover_state: bool = True
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
        self.candle_minutes = candle_minutes
        self.candle_seconds = candle_minutes * 60
        self.min_order_notional: float = trading_config.min_order_notional
        self.symbol_rules: Dict[str, SymbolRules] = dict(BINANCE_FUTURES_RULES)
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)

        self.account = PaperAccount(initial_balance=initial_capital)
        self.spread_history: List[float] = []
        self.current_position_state: int = 0  # 0: Flat, +1: Long spread, -1: Short spread
        self.bars_in_trade: int = 0
        self.current_trade_meta: Optional[Dict[str, Any]] = None

        # 5-Minute Candle Accumulator state
        self.current_bar_id: Optional[int] = None
        self.current_candle: Optional[Dict[str, Any]] = None
        self.last_completed_candle: Optional[CandleBar] = None

        # Stable rolling statistical baseline (anchored to 30 5m bars = 2.5 hours)
        self.rolling_mean: float = 0.0
        self.rolling_std: float = 0.005

        # Load calibrated parameters from summary if not specified
        if alpha is None or beta is None:
            self.alpha, self.beta = self._load_calibrated_parameters()
        else:
            self.alpha = alpha
            self.beta = beta

        # Warm up spread history with recent aligned matrix if present
        self._warmup_spread_history()
        self._update_rolling_statistics()

        # Re-hydrate persistent state, open positions & trade history from disk
        if recover_state:
            self._recover_state_from_disk()

    @staticmethod
    def _parse_timestamp(ts_str: Optional[str]) -> datetime:
        """Parses arbitrary timestamp string into timezone-aware UTC datetime."""
        if ts_str is None:
            return datetime.now(timezone.utc)
        for fmt in (
            "%Y-%m-%d %H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d"
        ):
            try:
                clean_str = ts_str.replace("+00:00", "+0000").replace("Z", "+0000")
                dt = datetime.strptime(clean_str, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                pass
        return datetime.now(timezone.utc)

    def _update_rolling_statistics(self):
        """
        Computes reference mean and std from completed historical 5m bars.
        Preserves the 2.5-hour equilibrium baseline regardless of high-frequency polling.
        """
        if len(self.spread_history) >= 2:
            arr = np.array(self.spread_history)
            self.rolling_mean = float(np.mean(arr))
            self.rolling_std = max(float(np.std(arr)), 1e-6)
        elif len(self.spread_history) == 1:
            self.rolling_mean = float(self.spread_history[0])
            self.rolling_std = 0.005
        else:
            self.rolling_mean = 0.0
            self.rolling_std = 0.005

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
        """Initializes rolling spread buffer with the most recent completed 5-minute bars."""
        aligned_path = PROCESSED_DATA_DIR / "aligned_close_prices.csv"
        if aligned_path.exists():
            try:
                df = pd.read_csv(aligned_path)
                if self.asset_a in df.columns and self.asset_b in df.columns:
                    p_a = df[self.asset_a].values[-self.zscore_window:]
                    p_b = df[self.asset_b].values[-self.zscore_window:]
                    spreads = np.log(p_a) - self.alpha - self.beta * np.log(p_b)
                    self.spread_history = list(spreads)
                    self._update_rolling_statistics()
                    logger.info(f"Warmed up spread buffer with {len(self.spread_history)} historical 5m bars. Baseline Mean={self.rolling_mean:.6f}, Std={self.rolling_std:.6f}")
            except Exception as e:
                logger.warning(f"Could not warm up spread history: {e}")

    def fetch_live_prices(self) -> Tuple[Optional[float], Optional[float]]:
        """
        Fetches current market mid-prices for Asset A and Asset B from Binance.
        Uses public REST ticker endpoints (no authentication required).
        Fetches all tickers in a single batch roundtrip to eliminate inter-leg latency skew.
        """
        url = "https://fapi.binance.com/fapi/v1/ticker/bookTicker"
        try:
            resp = requests.get(url, timeout=3.5)
            if resp.status_code == 200:
                tickers = resp.json()
                price_map = {}
                for item in tickers:
                    sym = item.get("symbol")
                    if sym in (self.asset_a, self.asset_b):
                        bid = float(item["bidPrice"])
                        ask = float(item["askPrice"])
                        price_map[sym] = (bid + ask) / 2.0
                if self.asset_a in price_map and self.asset_b in price_map:
                    return price_map[self.asset_a], price_map[self.asset_b]
        except Exception:
            pass

        # Fallback to individual requests if batch fails
        prices = {}
        for sym in [self.asset_a, self.asset_b]:
            try:
                resp = requests.get(url, params={"symbol": sym}, timeout=2.5)
                if resp.status_code == 200:
                    data = resp.json()
                    prices[sym] = (float(data["bidPrice"]) + float(data["askPrice"])) / 2.0
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
        Ingests a new market price tick for Asset A & Asset B.
        Accumulates ticks into 5-minute candles to preserve statistical baseline integrity,
        calculates mark-to-market Z-score, updates state machine, and executes paper orders.
        """
        dt = self._parse_timestamp(timestamp_str)
        canonical_ts_str = dt.strftime("%Y-%m-%d %H:%M:%S")

        current_prices = {self.asset_a: price_a, self.asset_b: price_b}
        bar_id = int(dt.timestamp()) // self.candle_seconds
        bar_elapsed_seconds = int(dt.timestamp()) % self.candle_seconds

        candle_closed = False

        # --- 1. 5-Minute Candle Accumulator (Kline Builder) ---
        if self.current_bar_id is None:
            # First tick initialization
            self.current_bar_id = bar_id
            self.current_candle = {
                "bar_id": bar_id,
                "start_time": canonical_ts_str,
                "open_a": price_a, "high_a": price_a, "low_a": price_a, "close_a": price_a,
                "open_b": price_b, "high_b": price_b, "low_b": price_b, "close_b": price_b,
                "ticks": 1
            }
        elif bar_id > self.current_bar_id:
            # PREVIOUS 5-MINUTE CANDLE HAS COMPLETED!
            completed_close_a = self.current_candle["close_a"]
            completed_close_b = self.current_candle["close_b"]
            completed_spread = float(np.log(completed_close_a) - self.alpha - self.beta * np.log(completed_close_b))

            self.last_completed_candle = CandleBar(
                bar_id=self.current_bar_id,
                start_time=self.current_candle["start_time"],
                close_time=canonical_ts_str,
                open_a=self.current_candle["open_a"],
                high_a=self.current_candle["high_a"],
                low_a=self.current_candle["low_a"],
                close_a=completed_close_a,
                open_b=self.current_candle["open_b"],
                high_b=self.current_candle["high_b"],
                low_b=self.current_candle["low_b"],
                close_b=completed_close_b,
                ticks=self.current_candle["ticks"],
                close_spread=completed_spread
            )

            # Append completed 5m bar spread into rolling buffer
            self.spread_history.append(completed_spread)
            if len(self.spread_history) > self.zscore_window:
                self.spread_history.pop(0)

            # Recompute 2.5-hour equilibrium baseline
            self._update_rolling_statistics()

            # Increment bars_in_trade once per completed 5m candle
            if self.current_position_state != 0:
                self.bars_in_trade += 1

            candle_closed = True

            # Reset accumulator for the new 5m candle
            self.current_bar_id = bar_id
            self.current_candle = {
                "bar_id": bar_id,
                "start_time": canonical_ts_str,
                "open_a": price_a, "high_a": price_a, "low_a": price_a, "close_a": price_a,
                "open_b": price_b, "high_b": price_b, "low_b": price_b, "close_b": price_b,
                "ticks": 1
            }
        else:
            # Intra-candle tick: update High, Low, Close and tick counter
            self.current_candle["high_a"] = max(self.current_candle["high_a"], price_a)
            self.current_candle["low_a"] = min(self.current_candle["low_a"], price_a)
            self.current_candle["close_a"] = price_a

            self.current_candle["high_b"] = max(self.current_candle["high_b"], price_b)
            self.current_candle["low_b"] = min(self.current_candle["low_b"], price_b)
            self.current_candle["close_b"] = price_b
            self.current_candle["ticks"] += 1

        # --- 2. Instantaneous Spread & Mark-to-Market Z-Score ---
        current_spread = float(np.log(price_a) - self.alpha - self.beta * np.log(price_b))
        zscore = float((current_spread - self.rolling_mean) / self.rolling_std)

        # --- 3. State Machine Logic ---
        action_taken = "HOLD"
        reason = ""

        if self.current_position_state == 0:
            # Check entry conditions
            if zscore <= -self.entry_threshold:
                # Undervalued spread -> Long spread (Buy A, Sell B)
                success = self._open_spread_position(target_state=1, price_a=price_a, price_b=price_b, timestamp_str=canonical_ts_str)
                if success:
                    action_taken = "OPEN_LONG_SPREAD"
                    reason = f"Z-score {zscore:.2f} <= -{self.entry_threshold}"
                else:
                    action_taken = "REJECTED_ORDER"
                    reason = "Exchange lot size / minimum notional check failed"
            elif zscore >= self.entry_threshold:
                # Overvalued spread -> Short spread (Sell A, Buy B)
                success = self._open_spread_position(target_state=-1, price_a=price_a, price_b=price_b, timestamp_str=canonical_ts_str)
                if success:
                    action_taken = "OPEN_SHORT_SPREAD"
                    reason = f"Z-score {zscore:.2f} >= +{self.entry_threshold}"
                else:
                    action_taken = "REJECTED_ORDER"
                    reason = "Exchange lot size / minimum notional check failed"
        else:
            # Check exit conditions
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
                self._close_spread_position(price_a=price_a, price_b=price_b, timestamp_str=canonical_ts_str, reason=exit_reason)
                action_taken = "CLOSE_SPREAD"
                reason = exit_reason

        # --- 4. Portfolio Metrics & Live Snapshot ---
        unrealized = self.account.get_unrealized_pnl(current_prices)
        total_equity = self.account.get_total_equity(current_prices)
        total_pnl = total_equity - self.account.initial_balance
        pnl_pct = (total_pnl / self.account.initial_balance) * 100.0
        candle_progress = round((bar_elapsed_seconds / self.candle_seconds) * 100.0, 1)

        # Serialize active positions
        positions_dict = {
            sym: {
                "symbol": pos.symbol,
                "side": pos.side,
                "contracts": pos.contracts,
                "entry_price": pos.entry_price,
                "notional": pos.notional,
                "entry_time": pos.entry_time
            }
            for sym, pos in self.account.positions.items()
        }

        snapshot = {
            "timestamp": canonical_ts_str,
            "pair": self.pair_name,
            "price_a": price_a,
            "price_b": price_b,
            "spread": current_spread,
            "rolling_mean": self.rolling_mean,
            "rolling_std": self.rolling_std,
            "zscore": zscore,
            "position_state": self.current_position_state,
            "action": action_taken,
            "reason": reason,
            "initial_balance": self.account.initial_balance,
            "cash_balance": self.account.cash_balance,
            "unrealized_pnl": unrealized,
            "realized_pnl": self.account.realized_pnl,
            "total_equity": total_equity,
            "pnl_pct": pnl_pct,
            "total_trades": len(self.account.closed_trades),
            "fees_paid": self.account.total_fees_paid,
            # Position & Trade Lifecycle State
            "positions": positions_dict,
            "current_trade_meta": self.current_trade_meta,
            # 5-Minute Candle Accumulator Telemetry
            "candle_minutes": self.candle_minutes,
            "candle_progress_pct": candle_progress,
            "candle_elapsed_seconds": bar_elapsed_seconds,
            "candle_closed": candle_closed,
            "ticks_in_candle": self.current_candle["ticks"] if self.current_candle else 1,
            "candle_open_a": self.current_candle["open_a"] if self.current_candle else price_a,
            "candle_open_b": self.current_candle["open_b"] if self.current_candle else price_b,
            "bars_in_trade": self.bars_in_trade
        }

        self._save_state(snapshot)
        return snapshot

    def get_symbol_rules(self, symbol: str) -> SymbolRules:
        """Returns exchange sizing rules for symbol, with safe fallback defaults."""
        sym = symbol.upper()
        if sym in self.symbol_rules:
            return self.symbol_rules[sym]
        return SymbolRules(
            step_size=0.001,
            min_qty=0.001,
            min_notional=self.min_order_notional,
            qty_precision=3,
            price_precision=2
        )

    def round_lot_size(
        self,
        symbol: str,
        raw_qty: float,
        price: float
    ) -> Tuple[float, Optional[str]]:
        """
        Rounds/truncates raw contract quantity to exchange step size (flooring to
        prevent exceeding margin allocation) and validates minimum quantity and
        minimum notional limits.
        Returns (valid_contracts, None) or (0.0, error_reason).
        """
        rules = self.get_symbol_rules(symbol)
        step = rules.step_size
        prec = rules.qty_precision

        if raw_qty <= 0:
            return 0.0, f"{symbol} calculated raw quantity is non-positive ({raw_qty})"

        # Floor by step size to prevent over-allocation of margin
        steps = math.floor((raw_qty + 1e-12) / step)
        rounded_qty = round(steps * step, prec)
        if prec == 0:
            rounded_qty = float(int(rounded_qty))

        if rounded_qty < rules.min_qty:
            return 0.0, (
                f"{symbol} floored qty {rounded_qty} is below exchange minQty {rules.min_qty} "
                f"(raw: {raw_qty:.6f})"
            )

        notional = rounded_qty * price
        min_notional = max(rules.min_notional, self.min_order_notional)
        if notional < min_notional:
            return 0.0, (
                f"{symbol} order notional ${notional:.2f} is below minNotional ${min_notional:.2f} "
                f"(qty: {rounded_qty}, price: ${price:,.2f})"
            )

        return rounded_qty, None

    def update_exchange_info(self) -> bool:
        """
        Attempts to fetch live exchange filters from Binance Futures API to update
        step sizes, minimum quantities, and minimum notionals dynamically.
        Falls back cleanly to hardcoded constants if network is unavailable.
        """
        url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
        try:
            resp = requests.get(url, timeout=4.0)
            if resp.status_code == 200:
                data = resp.json()
                for s in data.get("symbols", []):
                    sym = s.get("symbol")
                    if sym in self.symbol_rules or sym in (self.asset_a, self.asset_b):
                        step_size = None
                        min_qty = None
                        min_notional = self.min_order_notional
                        qty_precision = int(s.get("quantityPrecision", 3))
                        price_precision = int(s.get("pricePrecision", 2))
                        for f in s.get("filters", []):
                            ftype = f.get("filterType")
                            if ftype == "LOT_SIZE":
                                step_size = float(f.get("stepSize", 0.001))
                                min_qty = float(f.get("minQty", 0.001))
                            elif ftype in ("MIN_NOTIONAL", "NOTIONAL"):
                                notional_val = f.get("notional") or f.get("minNotional")
                                if notional_val:
                                    min_notional = float(notional_val)
                        if step_size is not None and min_qty is not None:
                            self.symbol_rules[sym] = SymbolRules(
                                step_size=step_size,
                                min_qty=min_qty,
                                min_notional=min_notional,
                                qty_precision=qty_precision,
                                price_precision=price_precision
                            )
                logger.info("Successfully refreshed Binance Futures exchange rules from API.")
                return True
        except Exception as e:
            logger.debug(f"Could not fetch live Binance exchange rules (using defaults): {e}")
        return False

    def _open_spread_position(self, target_state: int, price_a: float, price_b: float, timestamp_str: str) -> bool:
        """
        Sizes and fills both legs for spread entry, enforcing exchange lot step size
        and minimum notional constraints. Returns True if successfully opened, False if rejected.
        """
        gross_budget = self.account.cash_balance * self.allocation_pct
        notional_a_target = gross_budget / (1.0 + abs(self.beta))
        notional_b_target = (abs(self.beta) * gross_budget) / (1.0 + abs(self.beta))

        raw_contracts_a = notional_a_target / price_a
        raw_contracts_b = notional_b_target / price_b

        contracts_a, err_a = self.round_lot_size(self.asset_a, raw_contracts_a, price_a)
        contracts_b, err_b = self.round_lot_size(self.asset_b, raw_contracts_b, price_b)

        if err_a or err_b or contracts_a <= 0 or contracts_b <= 0:
            logger.warning(
                f"[{timestamp_str}] Order rejected by exchange lot filters: "
                f"{self.asset_a}: {err_a or 'OK'} | {self.asset_b}: {err_b or 'OK'}"
            )
            return False

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
                    f"{self.asset_a}: {side_a} {contracts_a} @ ${fill_a['fill_price']:,.2f} | "
                    f"{self.asset_b}: {side_b} {contracts_b} @ ${fill_b['fill_price']:,.2f}")
        return True

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

    def _recover_state_from_disk(self) -> bool:
        """
        Re-hydrates portfolio state from disk upon engine startup or server reboot.
        Restores:
          - account.cash_balance
          - account.realized_pnl
          - account.total_fees_paid
          - account.positions (reconstructed Position dataclasses)
          - current_position_state (+1, -1, 0)
          - bars_in_trade
          - current_trade_meta
          - account.closed_trades (loaded from paper_trades.csv)
        Returns:
          True if state was successfully recovered from disk, False otherwise.
        """
        state_file = self.results_dir / "paper_trading_state.json"
        trades_file = self.results_dir / "paper_trades.csv"

        # 1. Recover completed trades ledger if available
        if trades_file.exists():
            try:
                trades_df = pd.read_csv(trades_file)
                if not trades_df.empty:
                    self.account.closed_trades = trades_df.to_dict(orient="records")
                    logger.info(f"Loaded {len(self.account.closed_trades)} historical trades from {trades_file}")
            except Exception as e:
                logger.warning(f"Could not load historical trades from {trades_file}: {e}")

        # 2. Recover live state snapshot if available
        if not state_file.exists():
            return False

        try:
            with open(state_file, "r") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                return False

            # Verify target pair matches
            saved_pair = data.get("pair")
            if saved_pair and saved_pair != self.pair_name:
                logger.info(f"State file is for different pair ({saved_pair} vs {self.pair_name}), skipping recovery.")
                return False

            if "initial_balance" in data:
                self.account.initial_balance = float(data["initial_balance"])
            if "cash_balance" in data:
                self.account.cash_balance = float(data["cash_balance"])
            if "realized_pnl" in data:
                self.account.realized_pnl = float(data["realized_pnl"])
            if "fees_paid" in data:
                self.account.total_fees_paid = float(data["fees_paid"])
            if "position_state" in data:
                self.current_position_state = int(data["position_state"])
            if "bars_in_trade" in data:
                self.bars_in_trade = int(data["bars_in_trade"])
            if "current_trade_meta" in data:
                self.current_trade_meta = data.get("current_trade_meta")

            # Re-hydrate open positions
            raw_positions = data.get("positions", {})
            self.account.positions = {}
            for sym, pos_data in raw_positions.items():
                self.account.positions[sym] = Position(
                    symbol=pos_data["symbol"],
                    side=pos_data["side"],
                    contracts=float(pos_data["contracts"]),
                    entry_price=float(pos_data["entry_price"]),
                    notional=float(pos_data["notional"]),
                    entry_time=str(pos_data.get("entry_time", ""))
                )

            # Fallback re-hydration for older state files without explicit "positions" dict
            if self.current_position_state != 0 and not self.account.positions and self.current_trade_meta:
                meta = self.current_trade_meta
                side_a = "LONG" if self.current_position_state == 1 else "SHORT"
                side_b = "SHORT" if self.current_position_state == 1 else "LONG"
                entry_time = meta.get("entry_time", data.get("timestamp", ""))

                if "contracts_a" in meta and "entry_price_a" in meta:
                    self.account.positions[self.asset_a] = Position(
                        symbol=self.asset_a,
                        side=side_a,
                        contracts=float(meta["contracts_a"]),
                        entry_price=float(meta["entry_price_a"]),
                        notional=float(meta["contracts_a"]) * float(meta["entry_price_a"]),
                        entry_time=entry_time
                    )
                if "contracts_b" in meta and "entry_price_b" in meta:
                    self.account.positions[self.asset_b] = Position(
                        symbol=self.asset_b,
                        side=side_b,
                        contracts=float(meta["contracts_b"]),
                        entry_price=float(meta["entry_price_b"]),
                        notional=float(meta["contracts_b"]) * float(meta["entry_price_b"]),
                        entry_time=entry_time
                    )

            logger.info(
                f"Recovered state for {self.pair_name}: Cash=${self.account.cash_balance:,.2f}, "
                f"Realized PnL=${self.account.realized_pnl:+,.2f}, PositionState={self.current_position_state}, "
                f"OpenLegs={list(self.account.positions.keys())}, ClosedTrades={len(self.account.closed_trades)}"
            )
            return True
        except Exception as e:
            logger.warning(f"Error during state recovery from {state_file}: {e}")
            return False
