"""
Configuration parameters for Experiment 001:
Dynamic Cointegration-Based Statistical Arbitrage in Cryptocurrency Markets.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# Base Directory Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
RESULTS_DIR = BASE_DIR / "results"

load_dotenv(BASE_DIR / ".env")

for d in [RAW_DATA_DIR, PROCESSED_DATA_DIR, RESULTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class MarketConfig:
    exchange: str = "binance"
    market_type: str = "future"  # USDT-M Perpetual Futures
    base_currency: str = "USDT"
    timeframe: str = "5m"
    candle_minutes: int = 5
    annualization_factor: int = 365 * 24 * 12  # 105,120 5-min bars per year

    universe: List[str] = field(default_factory=lambda: [
        "BTCUSDT",
        "ETHUSDT",
        "BNBUSDT",
        "SOLUSDT",
        "XRPUSDT",
        "ADAUSDT",
        "LINKUSDT",
        "DOGEUSDT",
        "AVAXUSDT",
        "LTCUSDT"
    ])


@dataclass(frozen=True)
class SelectionConfig:
    # Lookback windows
    training_days: int = 30
    validation_days: int = 7
    test_days: int = 7

    # Bars per day for 5-minute candles = 24 * 12 = 288
    bars_per_day: int = 288
    training_bars: int = 30 * 288  # 8,640 bars
    reselection_bars: int = 7 * 288  # 2,016 bars

    # Screening criteria
    min_correlation: float = 0.70  # Log return Pearson correlation
    cointegration_alpha: float = 0.05  # Raw p-value threshold
    fdr_alpha: float = 0.10  # Benjamini-Hochberg False Discovery Rate threshold
    require_positive_beta: bool = True
    max_half_life_bars: int = 288 * 5  # Max half-life ~5 days for mean reversion
    max_selected_pairs: int = 2  # Hard validation ceiling: never pick more than 2 pairs at once


@dataclass(frozen=True)
class TradingConfig:
    # Capital and leverage
    initial_capital: float = 10000.0
    leverage: float = 1.0
    maintenance_margin_pct: float = 0.05  # 5% maintenance margin rate for perpetual futures
    max_active_pairs: int = 2  # Hard validation ceiling: strictly at most 2 active pairs concurrently
    pair_gross_allocation: float = 0.10  # 10% of portfolio equity per active pair
    max_portfolio_drawdown: float = 0.10  # 10% portfolio drawdown circuit breaker

    # Signal thresholds
    zscore_window: int = 288  # 24 hours rolling spread stats
    zscore_entry: float = 2.0  # Open signal
    zscore_exit: float = 0.25  # Mean convergence exit
    zscore_emergency_stop: float = 3.5  # Divergence emergency stop
    max_holding_period_bars: int = 288  # 24 hours time-based exit

    # Costs (Binance USDT-M Futures simulation defaults)
    taker_fee_pct: float = 0.0005  # 0.05% per leg per transaction
    slippage_pct: float = 0.0002   # 0.02% per leg per transaction
    default_funding_rate_8h: float = 0.0001  # 0.01% baseline 8-hour funding rate
    min_order_notional: float = 5.0  # Binance USDT-M Futures minimum notional $5.00


@dataclass(frozen=True)
class KalmanConfig:
    # State transition noise (w_t covariance Q)
    delta: float = 1e-4
    # Measurement noise variance (v_t variance R)
    observation_noise: float = 1e-3
    # Initial covariance scale
    initial_covariance: float = 1.0


@dataclass
class PaperTradingConfig:
    api_key: str = field(default_factory=lambda: os.getenv("BINANCE_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.getenv("BINANCE_API_SECRET", ""))
    testnet: bool = field(default_factory=lambda: os.getenv("BINANCE_TESTNET", "True").lower() == "true")
    base_url: str = field(
        default_factory=lambda: "https://testnet.binancefuture.com"
        if os.getenv("BINANCE_TESTNET", "True").lower() == "true"
        else "https://fapi.binance.com"
    )
    initial_balance: float = 10000.0
    pair: str = "BTCUSDT/ETHUSDT"
    allocation_pct: float = 0.10
    poll_interval_seconds: int = 5


@dataclass
class DeltaConfig:
    api_key: str = field(default_factory=lambda: os.getenv("DELTA_API_KEY", "5QtWt22iUBsBawMj8uIrtJezs8YUjT"))
    api_secret: str = field(default_factory=lambda: os.getenv("DELTA_API_SECRET", "NTjv3v9Z0xWPQ8PGBUParbEaYc3pHPrmvzc9ogqjt6Z6nwARfqqVNPLQCCce"))
    environment: str = field(default_factory=lambda: os.getenv("DELTA_ENVIRONMENT", "india").lower())
    default_pair: str = "BTCUSD/ETHUSD"
    universe: List[str] = field(default_factory=lambda: [
        "BTCUSD",
        "ETHUSD",
        "SOLUSD",
        "AVAXUSD",
        "BNBUSD",
        "XRPUSD",
        "ADAUSD",
        "DOGEUSD",
        "LINKUSD",
        "LTCUSD"
    ])

    @property
    def rest_url(self) -> str:
        if self.environment == "testnet":
            return "https://testnet-api.delta.exchange"
        elif self.environment == "global":
            return "https://api.delta.exchange"
        return "https://api.india.delta.exchange"

    @property
    def ws_url(self) -> str:
        if self.environment == "testnet":
            return "wss://testnet-socket.delta.exchange"
        elif self.environment == "global":
            return "wss://socket.delta.exchange"
        return "wss://socket.india.delta.exchange"


market_config = MarketConfig()
selection_config = SelectionConfig()
trading_config = TradingConfig()
kalman_config = KalmanConfig()
paper_config = PaperTradingConfig()
delta_config = DeltaConfig()
active_exchange = os.getenv("ACTIVE_EXCHANGE", "delta").lower()
