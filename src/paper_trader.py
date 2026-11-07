"""
Real-Time Paper Trading Engine for Cryptocurrency Statistical Arbitrage.
Manages virtual portfolio, order execution simulation with fees/slippage,
5-minute candle accumulator (Kline builder), real-time spread Z-score state machine,
and ledger persistence.
"""

import asyncio
import json
import logging
import math
import threading
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
    delta_config,
    active_exchange,
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
    "DOTUSDT": SymbolRules(step_size=0.1, min_qty=0.1, min_notional=5.0, qty_precision=1, price_precision=3),
}

# Delta Exchange India / Global Perpetual Futures Specifications
DELTA_FUTURES_RULES: Dict[str, SymbolRules] = {
    "BTCUSD": SymbolRules(step_size=0.001, min_qty=0.001, min_notional=5.0, qty_precision=3, price_precision=1),
    "ETHUSD": SymbolRules(step_size=0.01, min_qty=0.01, min_notional=5.0, qty_precision=2, price_precision=2),
    "SOLUSD": SymbolRules(step_size=1.0, min_qty=1.0, min_notional=5.0, qty_precision=0, price_precision=4),
    "AVAXUSD": SymbolRules(step_size=1.0, min_qty=1.0, min_notional=5.0, qty_precision=0, price_precision=4),
    "BNBUSD": SymbolRules(step_size=0.1, min_qty=0.1, min_notional=5.0, qty_precision=1, price_precision=3),
    "XRPUSD": SymbolRules(step_size=1.0, min_qty=1.0, min_notional=5.0, qty_precision=0, price_precision=4),
    "ADAUSD": SymbolRules(step_size=1.0, min_qty=1.0, min_notional=5.0, qty_precision=0, price_precision=5),
    "DOGEUSD": SymbolRules(step_size=100.0, min_qty=100.0, min_notional=5.0, qty_precision=0, price_precision=6),
    "LINKUSD": SymbolRules(step_size=1.0, min_qty=1.0, min_notional=5.0, qty_precision=0, price_precision=3),
    "LTCUSD": SymbolRules(step_size=0.1, min_qty=0.1, min_notional=5.0, qty_precision=1, price_precision=2),
}


class BinanceMultiplexPriceStream:
    """
    Real-Time WebSocket Client connecting to Binance USDT-M Futures multiplex stream:
        wss://fstream.binance.com/ws/<asset_a>@bookTicker/<asset_b>@bookTicker
    Receives simultaneous, zero-latency bid/ask updates for both legs with automatic
    reconnection, keepalive handling, and thread-safe price caching.
    """

    def __init__(self, asset_a: str, asset_b: str):
        self.asset_a = asset_a.upper()
        self.asset_b = asset_b.upper()
        self.stream_url = (
            f"wss://fstream.binance.com/ws/"
            f"{self.asset_a.lower()}@bookTicker/{self.asset_b.lower()}@bookTicker"
        )
        self.prices: Dict[str, float] = {}
        self.bids: Dict[str, float] = {}
        self.asks: Dict[str, float] = {}
        self.last_updated: Dict[str, float] = {}
        self.is_connected: bool = False
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def handle_message(self, raw_msg: str):
        """Parses incoming multiplex bookTicker JSON and updates thread-safe price cache."""
        try:
            data = json.loads(raw_msg)
            payload = data.get("data", data)
            sym = payload.get("s")
            if sym in (self.asset_a, self.asset_b):
                bid = float(payload["b"])
                ask = float(payload["a"])
                mid = (bid + ask) / 2.0
                now = time.time()
                with self._lock:
                    self.prices[sym] = mid
                    self.bids[sym] = bid
                    self.asks[sym] = ask
                    self.last_updated[sym] = now
                    self.is_connected = True
        except Exception as e:
            logger.debug(f"Error parsing Binance WS multiplex bookTicker payload: {e}")

    def get_latest_prices(self, max_staleness_seconds: float = 10.0) -> Tuple[Optional[float], Optional[float]]:
        """
        Returns (price_a, price_b) from live WebSocket stream if both are within staleness limit.
        """
        now = time.time()
        with self._lock:
            p_a = self.prices.get(self.asset_a)
            p_b = self.prices.get(self.asset_b)
            t_a = self.last_updated.get(self.asset_a, 0.0)
            t_b = self.last_updated.get(self.asset_b, 0.0)

            if p_a is not None and p_b is not None:
                if (now - t_a) <= max_staleness_seconds and (now - t_b) <= max_staleness_seconds:
                    return p_a, p_b
        return None, None

    async def _async_run(self):
        """Asynchronous listener with exponential backoff auto-reconnect."""
        try:
            import websockets
        except ImportError:
            logger.warning("websockets package not installed; multiplex stream unavailable.")
            return

        backoff = 1.0
        while self._running:
            try:
                async with websockets.connect(self.stream_url, ping_interval=20, ping_timeout=10) as ws:
                    self.is_connected = True
                    backoff = 1.0
                    logger.info(f"Connected to Binance Multiplex WebSocket: {self.stream_url}")
                    while self._running:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=15.0)
                            self.handle_message(msg)
                        except asyncio.TimeoutError:
                            pong_waiter = await ws.ping()
                            await asyncio.wait_for(pong_waiter, timeout=5.0)
            except Exception as e:
                self.is_connected = False
                if not self._running:
                    break
                logger.debug(f"Binance Multiplex WS stream disconnected: {e}. Reconnecting in {backoff:.1f}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)

    def _thread_worker(self):
        """Worker thread executing private event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._async_run())
        finally:
            loop.close()

    def start(self):
        """Spawns background daemon thread for streaming."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._thread_worker, daemon=True, name="BinanceMultiplexStream")
        self._thread.start()

    def stop(self):
        """Gracefully halts WebSocket stream and joins worker thread."""
        self._running = False
        self.is_connected = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)


class DeltaMultiplexPriceStream:
    """
    Real-Time WebSocket Client connecting to Delta Exchange WebSocket:
        wss://socket.india.delta.exchange (or configured delta_config.ws_url)
    Subscribes to 'v2/ticker' channel for both legs with automatic
    reconnection, keepalive handling, and thread-safe price caching.
    """

    def __init__(self, asset_a: str, asset_b: str, ws_url: Optional[str] = None):
        self.asset_a = asset_a.upper().replace("USDT", "USD")
        self.asset_b = asset_b.upper().replace("USDT", "USD")
        self.ws_url = ws_url or getattr(delta_config, "ws_url", "wss://socket.india.delta.exchange")
        self.prices: Dict[str, float] = {}
        self.bids: Dict[str, float] = {}
        self.asks: Dict[str, float] = {}
        self.mark_prices: Dict[str, float] = {}
        self.funding_rates: Dict[str, float] = {}
        self.last_updated: Dict[str, float] = {}
        self.is_connected: bool = False
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def handle_message(self, raw_msg: str):
        """Parses incoming Delta v2/ticker JSON and updates thread-safe price cache."""
        try:
            data = json.loads(raw_msg)
            msg_type = data.get("type")
            if msg_type == "v2/ticker":
                sym = data.get("symbol")
                if sym in (self.asset_a, self.asset_b):
                    mark = data.get("mark_price")
                    close = data.get("close")
                    bid = data.get("best_bid")
                    ask = data.get("best_ask")
                    fr = data.get("funding_rate")

                    price = None
                    if bid is not None and ask is not None and float(bid) > 0 and float(ask) > 0:
                        price = (float(bid) + float(ask)) / 2.0
                    elif mark is not None and float(mark) > 0:
                        price = float(mark)
                    elif close is not None and float(close) > 0:
                        price = float(close)

                    now = time.time()
                    if price is not None:
                        with self._lock:
                            self.prices[sym] = float(price)
                            if mark is not None:
                                self.mark_prices[sym] = float(mark)
                            if bid is not None:
                                self.bids[sym] = float(bid)
                            if ask is not None:
                                self.asks[sym] = float(ask)
                            if fr is not None:
                                self.funding_rates[sym] = float(fr)
                            self.last_updated[sym] = now
                            self.is_connected = True
        except Exception as e:
            logger.debug(f"Error parsing Delta WS ticker payload: {e}")

    def get_latest_prices(self, max_staleness_seconds: float = 10.0) -> Tuple[Optional[float], Optional[float]]:
        now = time.time()
        with self._lock:
            p_a = self.prices.get(self.asset_a)
            p_b = self.prices.get(self.asset_b)
            t_a = self.last_updated.get(self.asset_a, 0.0)
            t_b = self.last_updated.get(self.asset_b, 0.0)

            if p_a is not None and p_b is not None:
                if (now - t_a) <= max_staleness_seconds and (now - t_b) <= max_staleness_seconds:
                    return p_a, p_b
        return None, None

    async def _async_run(self):
        try:
            import websockets
        except ImportError:
            logger.warning("websockets package not available for DeltaMultiplexPriceStream.")
            return

        backoff = 1.0
        while self._running:
            try:
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=10) as ws:
                    sub_msg = {
                        "type": "subscribe",
                        "payload": {
                            "channels": [
                                {
                                    "name": "v2/ticker",
                                    "symbols": [self.asset_a, self.asset_b]
                                }
                            ]
                        }
                    }
                    await ws.send(json.dumps(sub_msg))
                    with self._lock:
                        self.is_connected = True
                    backoff = 1.0
                    logger.info(f"Connected to Delta WebSocket at {self.ws_url} for {self.asset_a}, {self.asset_b}")

                    while self._running:
                        msg = await ws.recv()
                        self.handle_message(msg)
            except Exception as e:
                with self._lock:
                    self.is_connected = False
                if not self._running:
                    break
                logger.debug(f"Delta WebSocket disconnected: {e}. Reconnecting in {backoff:.1f}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 30.0)

    def _thread_worker(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._async_run())
        finally:
            loop.close()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._thread_worker, daemon=True, name="DeltaMultiplexStream")
        self._thread.start()

    def stop(self):
        self._running = False
        self.is_connected = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)


class PaperAccount:
    """
    Virtual margin account tracking balances, margin requirements,
    open positions, leverage, and trade history with liquidation risk monitoring.
    """

    def __init__(
        self,
        initial_balance: float = 10000.0,
        fee_pct: float = trading_config.taker_fee_pct,
        slippage_pct: float = trading_config.slippage_pct,
        leverage: float = trading_config.leverage,
        maintenance_margin_pct: Optional[float] = None
    ):
        self.initial_balance = initial_balance
        self.cash_balance = initial_balance
        self.fee_pct = fee_pct
        self.slippage_pct = slippage_pct
        self.leverage = max(1.0, float(leverage))
        if maintenance_margin_pct is not None:
            self.maintenance_margin_pct = float(maintenance_margin_pct)
        else:
            self.maintenance_margin_pct = getattr(trading_config, "maintenance_margin_pct", 0.05)
        self.positions: Dict[str, Position] = {}
        self.closed_trades: List[Dict[str, Any]] = []
        self.total_fees_paid: float = 0.0
        self.total_funding_paid: float = 0.0
        self.funding_history: List[Dict[str, Any]] = []
        self.realized_pnl: float = 0.0

    def apply_funding_payment(
        self,
        symbol: str,
        side: str,
        contracts: float,
        mark_price: float,
        funding_rate: float,
        timestamp_str: str
    ) -> Dict[str, Any]:
        """
        Settles 8-hour perpetual funding payment:
            Funding payment = contracts * mark_price * funding_rate
        Long positions pay positive funding (cash deduction); short positions receive positive funding.
        Negative funding rate flips the cashflow direction.
        """
        notional = contracts * mark_price
        gross_payment = notional * funding_rate

        # Long pays positive funding (+funding_rate -> negative cash delta)
        # Short receives positive funding (+funding_rate -> positive cash delta)
        cash_change = -gross_payment if side == "LONG" else gross_payment

        self.cash_balance += cash_change
        self.total_funding_paid -= cash_change  # Cumulative net funding cost

        record = {
            "timestamp": timestamp_str,
            "symbol": symbol,
            "side": side,
            "contracts": contracts,
            "mark_price": mark_price,
            "notional": notional,
            "funding_rate": funding_rate,
            "payment": gross_payment,
            "cash_change": cash_change,
            "account_cash": self.cash_balance
        }
        self.funding_history.append(record)
        return record

    @property
    def initial_margin_locked(self) -> float:
        """
        Total initial margin locked to support open positions.
        At leverage L, initial margin locked is (1 / L) of total position notional.
        For example, at 5x leverage, 20% margin is locked.
        """
        if not self.positions:
            return 0.0
        return sum(pos.notional / self.leverage for pos in self.positions.values())

    @property
    def free_margin(self) -> float:
        """Available unencumbered cash balance for new position margin."""
        return max(0.0, self.cash_balance - self.initial_margin_locked)

    def get_maintenance_margin(self, current_prices: Optional[Dict[str, float]] = None) -> float:
        """
        Calculates maintenance margin threshold to maintain open positions.
        Uses mark-to-market notional if current prices are supplied, otherwise entry notional.
        """
        if not self.positions:
            return 0.0
        mm = 0.0
        for sym, pos in self.positions.items():
            if current_prices and sym in current_prices:
                notional = pos.contracts * current_prices[sym]
            else:
                notional = pos.notional
            mm += notional * self.maintenance_margin_pct
        return mm

    def get_margin_ratio(self, current_prices: Dict[str, float]) -> float:
        """
        Binance Futures Margin Ratio = maintenance_margin / total_equity.
        Forced liquidation is triggered when margin_ratio >= 1.0 (or total_equity < maintenance_margin).
        """
        equity = self.get_total_equity(current_prices)
        if equity <= 0.0:
            return float("inf")
        return self.get_maintenance_margin(current_prices) / equity

    def is_liquidatable(self, current_prices: Dict[str, float]) -> bool:
        """
        Returns True if open positions exist and total equity has fallen below maintenance margin.
        """
        if not self.positions:
            return False
        total_equity = self.get_total_equity(current_prices)
        maintenance_margin = self.get_maintenance_margin(current_prices)
        return total_equity < maintenance_margin

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
        recover_state: bool = True,
        leverage: float = trading_config.leverage,
        maintenance_margin_pct: Optional[float] = None,
        exchange: Optional[str] = None,
        account: Optional[PaperAccount] = None
    ):
        parts = pair.replace("-", "/").split("/")
        self.asset_a = parts[0].upper()
        self.asset_b = parts[1].upper()
        self.pair_name = f"{self.asset_a}/{self.asset_b}"

        # Determine exchange platform (Delta Exchange vs Binance)
        if exchange is not None:
            self.exchange = exchange.lower()
        elif ("USD" in self.asset_a and not self.asset_a.endswith("USDT")) or ("USD" in self.asset_b and not self.asset_b.endswith("USDT")):
            self.exchange = "delta"
        elif self.asset_a.endswith("USDT") or self.asset_b.endswith("USDT"):
            self.exchange = "binance"
        else:
            self.exchange = getattr(paper_config, "exchange", active_exchange).lower()

        self.allocation_pct = allocation_pct
        self.zscore_window = zscore_window
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.emergency_threshold = emergency_threshold
        self.candle_minutes = candle_minutes
        self.candle_seconds = candle_minutes * 60
        self.min_order_notional: float = trading_config.min_order_notional
        self.symbol_rules: Dict[str, SymbolRules] = dict(BINANCE_FUTURES_RULES)
        self.symbol_rules.update(DELTA_FUTURES_RULES)
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)

        if account is not None:
            self.account = account
        else:
            self.account = PaperAccount(
                initial_balance=initial_capital,
                leverage=leverage,
                maintenance_margin_pct=maintenance_margin_pct
            )
        self.leverage = self.account.leverage
        self.last_rejection_reason: Optional[str] = None
        self.last_funding_period_id: Optional[int] = None
        if self.exchange == "delta":
            self.price_stream = DeltaMultiplexPriceStream(self.asset_a, self.asset_b)
        else:
            self.price_stream = BinanceMultiplexPriceStream(self.asset_a, self.asset_b)
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
        """
        Loads static cointegration alpha and beta from previous screening,
        or dynamically fits an OLS regression if the pair assets exist in aligned data.
        """
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

                # Check reverse pair: A/B vs B/A
                rev_pair = f"{self.asset_b}/{self.asset_a}"
                match_rev = df[df["pair"] == rev_pair]
                if not match_rev.empty:
                    b_rev = float(match_rev.iloc[0]["beta"])
                    a_rev = float(match_rev.iloc[0]["alpha"])
                    if abs(b_rev) > 1e-6:
                        beta = 1.0 / b_rev
                        alpha = -a_rev / b_rev
                        logger.info(f"Derived inverted parameters for {self.pair_name} from {rev_pair}: Alpha={alpha:.4f}, Beta={beta:.4f}")
                        return alpha, beta
            except Exception as e:
                logger.warning(f"Could not load screening parameters: {e}")

        # Check if assets exist in historical aligned data and fit dynamic OLS
        aligned_path = PROCESSED_DATA_DIR / "aligned_close_prices.csv"
        if aligned_path.exists():
            try:
                df_prices = pd.read_csv(aligned_path)
                col_a = self._resolve_column_name(self.asset_a, df_prices.columns)
                col_b = self._resolve_column_name(self.asset_b, df_prices.columns)
                if col_a and col_b:
                    import statsmodels.api as sm
                    y = np.log(df_prices[col_a].dropna().values)
                    x = np.log(df_prices[col_b].dropna().values)
                    min_len = min(len(y), len(x))
                    y = y[-min_len:]
                    x = x[-min_len:]
                    X = sm.add_constant(x)
                    ols_fit = sm.OLS(y, X).fit()
                    alpha = float(ols_fit.params[0])
                    beta = float(ols_fit.params[1])
                    logger.info(f"Dynamically fitted OLS parameters for {self.pair_name}: Alpha={alpha:.4f}, Beta={beta:.4f}")
                    return alpha, beta
            except Exception as e:
                logger.warning(f"Dynamic OLS calibration failed for {self.pair_name}: {e}")

        # Default fallback calibrated parameters for BTC/ETH or general pair
        if self.pair_name in ["BTCUSDT/ETHUSDT", "BTCUSD/ETHUSD"]:
            logger.info(f"Using default parameters for {self.pair_name}: Alpha=1.4648, Beta=1.1678")
            return 1.4648, 1.1678
        if self.pair_name in ["SOLUSDT/AVAXUSDT", "SOLUSD/AVAXUSD"]:
            logger.info(f"Using default parameters for {self.pair_name}: Alpha=6.9580, Beta=0.7412")
            return 6.9580, 0.7412
        logger.info(f"Using standard default parameters for {self.pair_name}: Alpha=0.0, Beta=1.0")
        return 0.0, 1.0

    @staticmethod
    def _resolve_column_name(symbol: str, columns: Any) -> Optional[str]:
        """Resolves symbol against dataframe columns, supporting USDT <-> USD alias matching."""
        if symbol in columns:
            return symbol
        if symbol.endswith("USDT"):
            usd_equiv = symbol[:-1]
            if usd_equiv in columns:
                return usd_equiv
        elif symbol.endswith("USD"):
            usdt_equiv = symbol + "T"
            if usdt_equiv in columns:
                return usdt_equiv
        return None

    def _warmup_spread_history(self):
        """Initializes rolling spread buffer with the most recent completed 5-minute bars."""
        aligned_path = PROCESSED_DATA_DIR / "aligned_close_prices.csv"
        if aligned_path.exists():
            try:
                df = pd.read_csv(aligned_path)
                col_a = self._resolve_column_name(self.asset_a, df.columns)
                col_b = self._resolve_column_name(self.asset_b, df.columns)
                if col_a and col_b:
                    p_a = df[col_a].values[-self.zscore_window:]
                    p_b = df[col_b].values[-self.zscore_window:]
                    spreads = np.log(p_a) - self.alpha - self.beta * np.log(p_b)
                    self.spread_history = list(spreads)
                    self._update_rolling_statistics()
                    logger.info(f"Warmed up spread buffer with {len(self.spread_history)} historical 5m bars. Baseline Mean={self.rolling_mean:.6f}, Std={self.rolling_std:.6f}")
                else:
                    self.spread_history = []
                    self._update_rolling_statistics()
            except Exception as e:
                logger.warning(f"Could not warm up spread history: {e}")

    def switch_pair(
        self,
        new_pair: str,
        alpha: Optional[float] = None,
        beta: Optional[float] = None,
        clear_positions: bool = True
    ) -> Dict[str, Any]:
        """
        Dynamically transitions the engine to a new trading pair:
        - Halts the active WebSocket multiplex price stream.
        - Liquidates/clears previous open positions to avoid cross-pair margin confusion.
        - Reconfigures asset symbols, hedge ratio beta, and alpha intercept.
        - Re-initializes 5m candle accumulator and rolling spread history.
        - Reboots the Binance multiplex WebSocket stream for the new pair.
        - Returns transition summary metadata.
        """
        old_pair = self.pair_name
        clean_pair = new_pair.strip().upper()
        if "/" not in clean_pair:
            raise ValueError(f"Invalid pair format '{new_pair}'. Expected 'ASSET_A/ASSET_B' (e.g. 'SOLUSDT/AVAXUSDT').")

        parts = clean_pair.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError(f"Invalid pair format '{new_pair}'. Expected two non-empty symbols.")

        new_a, new_b = parts[0], parts[1]

        # 1. Stop current price stream
        was_streaming = bool(self.price_stream and self.price_stream.is_connected)
        self.stop_price_stream()

        # 2. Reset open positions to prevent cross-pair contamination
        if clear_positions:
            self.account.positions.clear()
            self.current_position_state = 0
            self.bars_in_trade = 0
            self.current_trade_meta = None

        # 3. Update symbols & exchange detection
        self.pair_name = clean_pair
        self.asset_a = new_a
        self.asset_b = new_b
        if ("USD" in new_a and not new_a.endswith("USDT")) or ("USD" in new_b and not new_b.endswith("USDT")):
            self.exchange = "delta"
        elif new_a.endswith("USDT") or new_b.endswith("USDT"):
            self.exchange = "binance"

        # 4. Load or fit cointegration parameters
        if alpha is not None and beta is not None:
            self.alpha = float(alpha)
            self.beta = float(beta)
        else:
            self.alpha, self.beta = self._load_calibrated_parameters()

        # 5. Reset candle accumulator
        self.current_bar_id = None
        self.current_candle = None
        self.last_completed_candle = None

        # 6. Warm up spread history for new pair
        self.spread_history = []
        self._warmup_spread_history()
        self._update_rolling_statistics()

        # 7. Re-initialize multiplex WebSocket price stream
        if self.exchange == "delta":
            self.price_stream = DeltaMultiplexPriceStream(self.asset_a, self.asset_b)
        else:
            self.price_stream = BinanceMultiplexPriceStream(self.asset_a, self.asset_b)
        if was_streaming:
            self.start_price_stream()

        self.last_rejection_reason = None
        logger.info(
            f"Successfully switched trading pair from {old_pair} to {self.pair_name} "
            f"(Alpha={self.alpha:.4f}, Beta={self.beta:.4f}, Baseline Mean={self.rolling_mean:.6f}, Std={self.rolling_std:.6f})"
        )

        return {
            "old_pair": old_pair,
            "new_pair": self.pair_name,
            "asset_a": self.asset_a,
            "asset_b": self.asset_b,
            "alpha": self.alpha,
            "beta": self.beta,
            "rolling_mean": self.rolling_mean,
            "rolling_std": self.rolling_std,
            "stream_started": was_streaming
        }

    def start_price_stream(self):
        """Initializes and connects zero-latency multiplex WebSocket price stream."""
        if self.price_stream is None:
            if self.exchange == "delta":
                self.price_stream = DeltaMultiplexPriceStream(self.asset_a, self.asset_b)
            else:
                self.price_stream = BinanceMultiplexPriceStream(self.asset_a, self.asset_b)
        self.price_stream.start()
        logger.info(f"Started multiplex WebSocket price stream for {self.pair_name} ({self.exchange.upper()})")

    def stop_price_stream(self):
        """Halts the multiplex WebSocket price stream."""
        if self.price_stream is not None:
            self.price_stream.stop()
            logger.info(f"Stopped multiplex WebSocket price stream for {self.pair_name}")

    def fetch_live_prices(self) -> Tuple[Optional[float], Optional[float]]:
        """
        Fetches current market mid-prices for Asset A and Asset B.
        Priority 1: Zero-latency WebSocket multiplex stream (Binance or Delta Exchange).
        Priority 2: Fallback to REST API tickers.
        """
        # 1. Attempt WebSocket multiplex stream read first
        if self.price_stream is not None and self.price_stream.is_connected:
            p_a, p_b = self.price_stream.get_latest_prices(max_staleness_seconds=10.0)
            if p_a is not None and p_b is not None:
                return p_a, p_b

        # 2. REST Fallback: Delta Exchange
        if self.exchange == "delta":
            prices = {}
            for sym in [self.asset_a, self.asset_b]:
                clean_sym = sym.replace("USDT", "USD")
                url = f"{delta_config.rest_url}/v2/tickers/{clean_sym}"
                try:
                    resp = requests.get(url, timeout=3.0)
                    if resp.status_code == 200:
                        res = resp.json().get("result", {})
                        p = res.get("mark_price") or res.get("close")
                        if p is not None:
                            prices[sym] = float(p)
                except Exception:
                    pass
            return prices.get(self.asset_a), prices.get(self.asset_b)

        # 2b. REST Fallback: Binance Batch
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

        # 3. Fallback to individual Binance requests if batch fails
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

    def fetch_live_funding_rates(self) -> Dict[str, float]:
        """
        Fetches current 8-hour perpetual funding rates from exchange API.
        Falls back to trading_config.default_funding_rate_8h (0.0001 = 0.01%) if network is unavailable.
        """
        rates = {
            self.asset_a: trading_config.default_funding_rate_8h,
            self.asset_b: trading_config.default_funding_rate_8h
        }

        # Delta Exchange funding rates
        if self.exchange == "delta":
            for sym in (self.asset_a, self.asset_b):
                clean_sym = sym.replace("USDT", "USD")
                url = f"{delta_config.rest_url}/v2/tickers/{clean_sym}"
                try:
                    resp = requests.get(url, timeout=3.0)
                    if resp.status_code == 200:
                        res = resp.json().get("result", {})
                        fr = res.get("funding_rate")
                        if fr is not None:
                            rates[sym] = float(fr)
                except Exception:
                    pass
            return rates

        # Binance Futures funding rates
        for sym in (self.asset_a, self.asset_b):
            try:
                url = "https://fapi.binance.com/fapi/v1/premiumIndex"
                resp = requests.get(url, params={"symbol": sym}, timeout=2.5)
                if resp.status_code == 200:
                    data = resp.json()
                    val = data.get("lastFundingRate")
                    if val is not None:
                        rates[sym] = float(val)
                        continue
            except Exception:
                pass

            try:
                url = "https://fapi.binance.com/fapi/v1/fundingRate"
                resp = requests.get(url, params={"symbol": sym, "limit": 1}, timeout=2.5)
                if resp.status_code == 200:
                    data = resp.json()
                    if data and isinstance(data, list) and "fundingRate" in data[-1]:
                        rates[sym] = float(data[-1]["fundingRate"])
            except Exception:
                pass

        return rates

    def settle_funding_fees(
        self,
        current_prices: Dict[str, float],
        timestamp_str: str,
        funding_rates: Optional[Dict[str, float]] = None
    ) -> List[Dict[str, Any]]:
        """
        Settles 8-hour perpetual funding payments across all active positions.
        """
        if not self.account.positions:
            return []
        if funding_rates is None:
            funding_rates = self.fetch_live_funding_rates()

        settlements = []
        for sym, pos in list(self.account.positions.items()):
            mark_price = current_prices.get(sym, pos.entry_price)
            fr = funding_rates.get(sym, trading_config.default_funding_rate_8h)
            payment_info = self.account.apply_funding_payment(
                symbol=sym,
                side=pos.side,
                contracts=pos.contracts,
                mark_price=mark_price,
                funding_rate=fr,
                timestamp_str=timestamp_str
            )
            settlements.append(payment_info)
            logger.info(
                f"[{timestamp_str}] 8-HOUR FUNDING SETTLED | {sym} ({pos.side}): "
                f"Rate={fr*100:.4f}% | Notional=${payment_info['notional']:,.2f} | "
                f"Cash Delta=${payment_info['cash_change']:+,.4f} | Cash Balance=${self.account.cash_balance:,.2f}"
            )
        return settlements

    def process_tick(
        self,
        price_a: float,
        price_b: float,
        timestamp_str: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Ingests a new market price tick for Asset A & Asset B.
        Accumulates ticks into 5-minute candles to preserve statistical baseline integrity,
        settles periodic 8-hour perpetual funding payments, calculates mark-to-market Z-score,
        updates state machine, and executes paper orders.
        """
        dt = self._parse_timestamp(timestamp_str)
        canonical_ts_str = dt.strftime("%Y-%m-%d %H:%M:%S")

        # Reject invalid/non-positive/infinite price ticks to prevent NaN corruption in statistics
        if (
            price_a is None or price_b is None
            or price_a <= 0 or price_b <= 0
            or not (math.isfinite(price_a) and math.isfinite(price_b))
        ):
            logger.warning(
                f"[{canonical_ts_str}] Rejected invalid market tick: {self.asset_a}={price_a}, {self.asset_b}={price_b}"
            )
            return {
                "timestamp": canonical_ts_str,
                "pair": self.pair_name,
                "price_a": price_a if (price_a is not None and math.isfinite(price_a)) else 0.0,
                "price_b": price_b if (price_b is not None and math.isfinite(price_b)) else 0.0,
                "spread": 0.0,
                "rolling_mean": self.rolling_mean,
                "rolling_std": self.rolling_std,
                "zscore": 0.0,
                "position_state": self.current_position_state,
                "action": "REJECTED_TICK",
                "reason": "Invalid price: values must be strictly positive and finite",
                "initial_balance": self.account.initial_balance,
                "cash_balance": self.account.cash_balance,
                "unrealized_pnl": 0.0,
                "realized_pnl": self.account.realized_pnl,
                "total_equity": self.account.cash_balance,
                "pnl_pct": 0.0,
                "total_trades": len(self.account.closed_trades),
                "fees_paid": self.account.total_fees_paid,
                "leverage": self.account.leverage,
                "initial_margin_locked": round(self.account.initial_margin_locked, 2),
                "maintenance_margin": 0.0,
                "free_margin": round(self.account.free_margin, 2),
                "margin_ratio": 0.0,
                "total_funding_paid": round(self.account.total_funding_paid, 4),
                "last_funding_period_id": self.last_funding_period_id,
                "funding_settled": False,
                "feed_source": "WEBSOCKET_MULTIPLEX" if (self.price_stream and self.price_stream.is_connected) else "REST_POLLING",
                "stream_connected": bool(self.price_stream and self.price_stream.is_connected),
                "positions": {},
                "current_trade_meta": self.current_trade_meta,
                "candle_minutes": self.candle_minutes,
                "candle_progress_pct": 0.0,
                "candle_elapsed_seconds": 0,
                "candle_closed": False,
                "ticks_in_candle": self.current_candle["ticks"] if self.current_candle else 0,
                "candle_open_a": self.current_candle["open_a"] if self.current_candle else 0.0,
                "candle_open_b": self.current_candle["open_b"] if self.current_candle else 0.0,
                "bars_in_trade": self.bars_in_trade
            }

        current_prices = {self.asset_a: price_a, self.asset_b: price_b}
        bar_id = int(dt.timestamp()) // self.candle_seconds
        bar_elapsed_seconds = int(dt.timestamp()) % self.candle_seconds

        candle_closed = False

        # --- 0. 8-Hour Perpetual Funding Rate Settlement (00:00, 08:00, 16:00 UTC) ---
        ts_sec = int(dt.timestamp())
        funding_period_id = ts_sec // (8 * 3600)  # 28,800 seconds per 8-hour window
        funding_settled = False
        funding_settlements = []

        if self.last_funding_period_id is None:
            self.last_funding_period_id = funding_period_id
        elif funding_period_id > self.last_funding_period_id:
            # 8-Hour boundary crossed: settle funding for open positions
            if self.account.positions:
                funding_settlements = self.settle_funding_fees(current_prices, canonical_ts_str)
                funding_settled = bool(funding_settlements)
            self.last_funding_period_id = funding_period_id

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

        # --- 3. State Machine Logic & Margin Liquidation Check ---
        action_taken = "HOLD"
        reason = ""

        # Priority 1: Check Forced Liquidation if positions are open
        if self.account.positions and self.account.is_liquidatable(current_prices):
            total_equity = self.account.get_total_equity(current_prices)
            mm = self.account.get_maintenance_margin(current_prices)
            mr = self.account.get_margin_ratio(current_prices)
            liq_reason = (
                f"Forced Liquidation: Total equity ${total_equity:,.2f} < "
                f"Maintenance margin ${mm:,.2f} (Margin ratio: {mr*100:.1f}%)"
            )
            self._close_spread_position(price_a=price_a, price_b=price_b, timestamp_str=canonical_ts_str, reason=liq_reason)
            action_taken = "LIQUIDATION"
            reason = liq_reason
        elif self.current_position_state == 0:
            # Check entry conditions
            if zscore <= -self.entry_threshold:
                # Undervalued spread -> Long spread (Buy A, Sell B)
                success = self._open_spread_position(target_state=1, price_a=price_a, price_b=price_b, timestamp_str=canonical_ts_str)
                if success:
                    action_taken = "OPEN_LONG_SPREAD"
                    reason = f"Z-score {zscore:.2f} <= -{self.entry_threshold}"
                else:
                    action_taken = "REJECTED_ORDER"
                    reason = self.last_rejection_reason or "Exchange lot size / minimum notional check failed"
            elif zscore >= self.entry_threshold:
                # Overvalued spread -> Short spread (Sell A, Buy B)
                success = self._open_spread_position(target_state=-1, price_a=price_a, price_b=price_b, timestamp_str=canonical_ts_str)
                if success:
                    action_taken = "OPEN_SHORT_SPREAD"
                    reason = f"Z-score {zscore:.2f} >= +{self.entry_threshold}"
                else:
                    action_taken = "REJECTED_ORDER"
                    reason = self.last_rejection_reason or "Exchange lot size / minimum notional check failed"
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

        # If funding was settled and no position trade action occurred on this tick, reflect in action telemetry
        if funding_settled and action_taken == "HOLD":
            action_taken = "FUNDING_SETTLED"
            reason = f"8-Hour Perpetual funding settled for {len(funding_settlements)} open position leg(s)"

        # --- 4. Portfolio Metrics & Live Snapshot ---
        unrealized = self.account.get_unrealized_pnl(current_prices)
        total_equity = self.account.get_total_equity(current_prices)
        total_pnl = total_equity - self.account.initial_balance
        pnl_pct = (total_pnl / self.account.initial_balance) * 100.0
        candle_progress = round((bar_elapsed_seconds / self.candle_seconds) * 100.0, 1)

        # Margin Risk Metrics
        init_margin_locked = self.account.initial_margin_locked
        maint_margin = self.account.get_maintenance_margin(current_prices)
        free_margin = self.account.free_margin
        raw_margin_ratio = self.account.get_margin_ratio(current_prices) if self.account.positions else 0.0
        margin_ratio_val = 999.9 if raw_margin_ratio == float("inf") else round(raw_margin_ratio, 4)

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
            "exchange": self.exchange.upper(),
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
            # Margin & Liquidation Risk Telemetry
            "leverage": self.account.leverage,
            "initial_margin_locked": round(init_margin_locked, 2),
            "maintenance_margin": round(maint_margin, 2),
            "free_margin": round(free_margin, 2),
            "margin_ratio": margin_ratio_val,
            # Perpetual Funding Telemetry
            "total_funding_paid": round(self.account.total_funding_paid, 4),
            "last_funding_period_id": self.last_funding_period_id,
            "funding_settled": funding_settled,
            # Data Feed & Stream Latency Telemetry
            "feed_source": "WEBSOCKET_MULTIPLEX" if (self.price_stream and self.price_stream.is_connected) else "REST_POLLING",
            "stream_connected": bool(self.price_stream and self.price_stream.is_connected),
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
        Sizes and fills both legs for spread entry, enforcing exchange lot step size,
        minimum notional constraints, and initial margin locking against free margin.
        Returns True if successfully opened, False if rejected.
        """
        available_margin = self.account.free_margin
        if available_margin <= 0:
            self.last_rejection_reason = "Insufficient free margin (free margin is $0.00)"
            logger.warning(f"[{timestamp_str}] Order rejected: {self.last_rejection_reason}")
            return False

        # Risk-Budget Position Sizing (Research Blueprint Section 9 & 17):
        # 1. Baseline allocation ceiling (10% of cash balance)
        alloc_ceiling = self.account.cash_balance * self.allocation_pct

        # 2. Risk-budget constraint (1% portfolio risk budget at emergency stop |Z|=3.5)
        delta_z = max(0.5, abs(self.emergency_threshold - self.entry_threshold))
        roundtrip_cost_pct = 2.0 * (self.account.fee_pct + self.account.slippage_pct)
        spread_loss_per_dollar = (delta_z * max(1e-4, self.rolling_std)) + roundtrip_cost_pct
        risk_budget_dollars = self.account.cash_balance * 0.01  # 1.0% maximum risk
        risk_budget_gross = risk_budget_dollars / spread_loss_per_dollar

        # Constrained gross exposure is the tighter of the risk budget and allocation ceiling
        gross_budget = min(alloc_ceiling, max(trading_config.min_order_notional * 2.5, risk_budget_gross))

        notional_a_target = gross_budget / (1.0 + abs(self.beta))
        notional_b_target = (abs(self.beta) * gross_budget) / (1.0 + abs(self.beta))

        raw_contracts_a = notional_a_target / price_a
        raw_contracts_b = notional_b_target / price_b

        contracts_a, err_a = self.round_lot_size(self.asset_a, raw_contracts_a, price_a)
        contracts_b, err_b = self.round_lot_size(self.asset_b, raw_contracts_b, price_b)

        if err_a or err_b or contracts_a <= 0 or contracts_b <= 0:
            self.last_rejection_reason = (
                f"Exchange lot size / minimum notional check failed: "
                f"{self.asset_a}: {err_a or 'OK'} | {self.asset_b}: {err_b or 'OK'}"
            )
            logger.warning(f"[{timestamp_str}] Order rejected by exchange lot filters: {self.last_rejection_reason}")
            return False

        # Margin requirement check: verify required initial margin <= free margin
        est_notional_a = contracts_a * price_a
        est_notional_b = contracts_b * price_b
        total_req_margin = (est_notional_a + est_notional_b) / self.account.leverage

        if total_req_margin > available_margin:
            self.last_rejection_reason = (
                f"Insufficient margin: Required initial margin ${total_req_margin:.2f} > "
                f"Available free margin ${available_margin:.2f}"
            )
            logger.warning(f"[{timestamp_str}] Order rejected: {self.last_rejection_reason}")
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
            "entry_fees": fill_a["fee"] + fill_b["fee"],
            "initial_margin_locked": (fill_a["notional"] + fill_b["notional"]) / self.account.leverage
        }
        logger.info(f"[{timestamp_str}] OPENED {('LONG' if target_state==1 else 'SHORT')} SPREAD | "
                    f"{self.asset_a}: {side_a} {contracts_a} @ ${fill_a['fill_price']:,.2f} | "
                    f"{self.asset_b}: {side_b} {contracts_b} @ ${fill_b['fill_price']:,.2f} | "
                    f"Margin Locked: ${self.account.initial_margin_locked:,.2f} ({self.account.leverage:.0f}x)")
        return True

    def _close_spread_position(self, price_a: float, price_b: float, timestamp_str: str, reason: str):
        """Liquidates both legs for spread exit and records trade PnL."""
        pos_a = self.account.positions.pop(self.asset_a, None)
        pos_b = self.account.positions.pop(self.asset_b, None)

        gross_pnl_a, fee_a = 0.0, 0.0
        gross_pnl_b, fee_b = 0.0, 0.0

        if pos_a is not None:
            close_side_a = "SELL" if pos_a.side == "LONG" else "BUY"
            fill_a = self.account.execute_fill(self.asset_a, close_side_a, pos_a.contracts, price_a, timestamp_str)
            fee_a = fill_a["fee"]
            if pos_a.side == "LONG":
                gross_pnl_a = pos_a.contracts * (fill_a["fill_price"] - pos_a.entry_price)
            else:
                gross_pnl_a = pos_a.contracts * (pos_a.entry_price - fill_a["fill_price"])

        if pos_b is not None:
            close_side_b = "SELL" if pos_b.side == "LONG" else "BUY"
            fill_b = self.account.execute_fill(self.asset_b, close_side_b, pos_b.contracts, price_b, timestamp_str)
            fee_b = fill_b["fee"]
            if pos_b.side == "LONG":
                gross_pnl_b = pos_b.contracts * (fill_b["fill_price"] - pos_b.entry_price)
            else:
                gross_pnl_b = pos_b.contracts * (pos_b.entry_price - fill_b["fill_price"])

        total_gross_pnl = gross_pnl_a + gross_pnl_b
        exit_fees = fee_a + fee_b
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
        """Persists live state and trade logs to disk with pair-specific namespacing."""
        state_file = self.results_dir / "paper_trading_state.json"
        pair_state_file = self.results_dir / f"paper_trading_state_{self.asset_a}_{self.asset_b}.json"
        try:
            with open(state_file, "w") as f:
                json.dump(snapshot, f, indent=4)
            with open(pair_state_file, "w") as f:
                json.dump(snapshot, f, indent=4)
        except Exception as e:
            logger.debug(f"Error persisting state snapshot for {self.pair_name}: {e}")

        if self.account.closed_trades:
            trades_df = pd.DataFrame(self.account.closed_trades)
            trades_df.to_csv(self.results_dir / "paper_trades.csv", index=False)

        if self.account.funding_history:
            funding_df = pd.DataFrame(self.account.funding_history)
            funding_df.to_csv(self.results_dir / "paper_funding.csv", index=False)

    def _recover_state_from_disk(self) -> bool:
        """
        Re-hydrates portfolio state from disk upon engine startup or server reboot.
        Restores:
          - account.cash_balance
          - account.realized_pnl
          - account.total_fees_paid
          - account.total_funding_paid
          - account.positions (reconstructed Position dataclasses)
          - current_position_state (+1, -1, 0)
          - bars_in_trade
          - current_trade_meta
          - account.closed_trades (loaded from paper_trades.csv)
          - account.funding_history (loaded from paper_funding.csv)
        Returns:
          True if state was successfully recovered from disk, False otherwise.
        """
        pair_state_file = self.results_dir / f"paper_trading_state_{self.asset_a}_{self.asset_b}.json"
        state_file = pair_state_file if pair_state_file.exists() else (self.results_dir / "paper_trading_state.json")
        trades_file = self.results_dir / "paper_trades.csv"
        funding_file = self.results_dir / "paper_funding.csv"

        # 1. Recover completed trades ledger if available
        if trades_file.exists():
            try:
                trades_df = pd.read_csv(trades_file)
                if not trades_df.empty:
                    self.account.closed_trades = trades_df.to_dict(orient="records")
                    logger.info(f"Loaded {len(self.account.closed_trades)} historical trades from {trades_file}")
            except Exception as e:
                logger.warning(f"Could not load historical trades from {trades_file}: {e}")

        # 1b. Recover historical funding records if available
        if funding_file.exists():
            try:
                funding_df = pd.read_csv(funding_file)
                if not funding_df.empty:
                    self.account.funding_history = funding_df.to_dict(orient="records")
                    logger.info(f"Loaded {len(self.account.funding_history)} historical funding records from {funding_file}")
            except Exception as e:
                logger.warning(f"Could not load historical funding records from {funding_file}: {e}")

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
            if "total_funding_paid" in data:
                self.account.total_funding_paid = float(data["total_funding_paid"])
            if "last_funding_period_id" in data and data["last_funding_period_id"] is not None:
                self.last_funding_period_id = int(data["last_funding_period_id"])
            if "leverage" in data:
                self.account.leverage = float(data["leverage"])
                self.leverage = self.account.leverage
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
