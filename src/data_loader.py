"""
Data Loader Module for Binance USDT-M Perpetual Futures.
Supports direct public REST API fetching, CCXT integration, local caching,
and synthetic test data generation.
"""

import os
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

import pandas as pd
import numpy as np
import requests

from config import RAW_DATA_DIR, market_config

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BINANCE_FAPI_URL = "https://fapi.binance.com/fapi/v1/klines"


class BinanceFuturesDataLoader:
    """
    Downloads and caches historical 5m OHLCV data for Binance USDT-M Perpetual Futures.
    No API keys are required for historical public market data.
    """

    def __init__(self, raw_dir: Path = RAW_DATA_DIR):
        self.raw_dir = Path(raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "QuantResearch-CryptoStatisticalArbitrage/1.0"
        })

    def fetch_klines_chunk(
        self,
        symbol: str,
        interval: str = "5m",
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
        limit: int = 1000,
        retries: int = 2
    ) -> List[List[Any]]:
        """
        Fetches up to 1000 klines from Binance USDT-M Futures REST API.
        """
        params = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": limit
        }
        if start_time_ms is not None:
            params["startTime"] = int(start_time_ms)
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)

        for attempt in range(1, retries + 1):
            try:
                resp = self.session.get(BINANCE_FAPI_URL, params=params, timeout=4)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 10))
                    logger.warning(f"Rate limited (429) for {symbol}. Sleeping {retry_after}s...")
                    time.sleep(retry_after)
                else:
                    logger.warning(f"Binance API status {resp.status_code} for {symbol}: {resp.text}")
                    time.sleep(attempt * 1)
            except Exception as e:
                logger.warning(f"Attempt {attempt}/{retries} failed for {symbol}: {e}")
                time.sleep(attempt * 1)

        raise RuntimeError(f"Failed to fetch data from Binance for {symbol} after {retries} retries.")

    def download_symbol_history(
        self,
        symbol: str,
        days: int = 30,
        interval: str = "5m",
        end_time: Optional[datetime] = None
    ) -> pd.DataFrame:
        """
        Paginates historical candles backwards or forwards to collect continuous data.
        Returns a validated pandas DataFrame.
        """
        if end_time is None:
            end_time = datetime.now(timezone.utc)
        elif end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)

        end_ms = int(end_time.timestamp() * 1000)
        start_ms = end_ms - (days * 24 * 3600 * 1000)

        logger.info(f"Downloading {symbol} ({interval}) from {datetime.fromtimestamp(start_ms/1000, tz=timezone.utc)} to {datetime.fromtimestamp(end_ms/1000, tz=timezone.utc)}")

        all_klines = []
        current_start = start_ms

        while current_start < end_ms:
            chunk = self.fetch_klines_chunk(
                symbol=symbol,
                interval=interval,
                start_time_ms=current_start,
                end_time_ms=end_ms,
                limit=1000
            )
            if not chunk:
                break

            all_klines.extend(chunk)
            last_open_time = chunk[-1][0]
            if len(chunk) < 1000 or last_open_time <= current_start:
                break
            current_start = last_open_time + 1
            time.sleep(0.1)  # Respect Binance public IP rate limits (~1200 weight/min)

        if not all_klines:
            raise ValueError(f"No klines retrieved for {symbol}.")

        df = self._parse_klines(all_klines)
        # Filter exact date boundaries
        df = df[(df["timestamp"] >= start_ms) & (df["timestamp"] <= end_ms)]
        df.drop_duplicates(subset=["timestamp"], inplace=True)
        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    @staticmethod
    def _parse_klines(raw_klines: List[List[Any]]) -> pd.DataFrame:
        """
        Parses Binance Futures kline format:
        [
          0: Open time, 1: Open, 2: High, 3: Low, 4: Close, 5: Volume,
          6: Close time, 7: Quote asset volume, 8: Number of trades,
          9: Taker buy base asset volume, 10: Taker buy quote asset volume, 11: Ignore
        ]
        """
        cols = [
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "count",
            "taker_buy_volume", "taker_buy_quote_volume", "ignore"
        ]
        df = pd.DataFrame(raw_klines, columns=cols)
        df["timestamp"] = df["open_time"].astype(np.int64)
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        for num_col in ["open", "high", "low", "close", "volume", "quote_volume"]:
            df[num_col] = df[num_col].astype(np.float64)
        df["count"] = df["count"].astype(np.int64)

        return df[["timestamp", "datetime", "open", "high", "low", "close", "volume", "quote_volume", "count"]]

    def get_or_download(
        self,
        symbol: str,
        days: int = 30,
        interval: str = "5m",
        force_refresh: bool = False
    ) -> pd.DataFrame:
        """
        Retrieves data from local cache if present and sufficient, or downloads and saves.
        """
        filepath = self.raw_dir / f"{symbol}_{interval}.csv"
        if filepath.exists() and not force_refresh:
            try:
                df = pd.read_csv(filepath)
                df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
                # Check if data spans enough days
                span_days = (df["datetime"].iloc[-1] - df["datetime"].iloc[0]).total_seconds() / 86400.0
                if span_days >= (days - 1):
                    logger.info(f"Loaded {symbol} from cache ({len(df)} rows, ~{span_days:.1f} days).")
                    return df
            except Exception as e:
                logger.warning(f"Could not load cache for {symbol}: {e}. Re-downloading.")

        df = self.download_symbol_history(symbol=symbol, days=days, interval=interval)
        df.to_csv(filepath, index=False)
        logger.info(f"Cached {symbol} to {filepath} ({len(df)} rows).")
        return df

    def download_universe(
        self,
        symbols: Optional[List[str]] = None,
        days: int = 30,
        interval: str = "5m",
        force_refresh: bool = False
    ) -> Dict[str, pd.DataFrame]:
        """
        Downloads the entire specified or configured crypto universe.
        """
        if symbols is None:
            symbols = market_config.universe

        data_dict = {}
        for s in symbols:
            try:
                df = self.get_or_download(s, days=days, interval=interval, force_refresh=force_refresh)
                data_dict[s] = df
            except Exception as e:
                logger.error(f"Error fetching data for {s}: {e}")
                logger.warning("Network connection to Binance unavailable. Halting remote queries immediately.")
                break
        return data_dict


def generate_synthetic_futures_data(
    symbols: Optional[List[str]] = None,
    n_bars: int = 288 * 35,  # 35 days of 5m bars
    seed: int = 42
) -> Dict[str, pd.DataFrame]:
    """
    Generates realistic synthetic 5-minute OHLCV data for testing.
    Constructs cointegrated pairs with mean-reverting spreads and geometric Brownian motion.
    """
    np.random.seed(seed)
    if symbols is None:
        symbols = market_config.universe[:4]

    start_time = pd.Timestamp("2024-01-01 00:00:00", tz="UTC")
    timestamps = [int((start_time + pd.Timedelta(minutes=5 * i)).timestamp() * 1000) for i in range(n_bars)]
    datetimes = pd.to_datetime(timestamps, unit="ms", utc=True)

    # Base common market factor (Crypto Market Index)
    drift = 0.00001
    vol = 0.003
    market_returns = np.random.normal(drift, vol, n_bars)
    market_log_price = np.cumsum(market_returns) + np.log(40000.0)

    data_dict = {}
    base_prices = {
        "BTCUSDT": 45000.0,
        "ETHUSDT": 2500.0,
        "BNBUSDT": 300.0,
        "SOLUSDT": 100.0,
        "XRPUSDT": 0.55,
        "ADAUSDT": 0.50,
        "LINKUSDT": 15.0,
        "DOGEUSDT": 0.08,
        "AVAXUSDT": 35.0,
        "LTCUSDT": 70.0,
    }

    # Generate BTC
    btc_noise = np.cumsum(np.random.normal(0, 0.0015, n_bars))
    btc_close = np.exp(market_log_price + btc_noise)

    # Cointegration link: ETH = alpha + beta * BTC + stationary Ornstein-Uhlenbeck spread
    theta_ou = 0.05  # Mean-reversion speed (Half-life = -ln(2)/(-0.05) ~ 14 bars)
    ou_spread = np.zeros(n_bars)
    for i in range(1, n_bars):
        ou_spread[i] = ou_spread[i - 1] * (1 - theta_ou) + np.random.normal(0, 0.002)

    for sym in symbols:
        p0 = base_prices.get(sym, 100.0)
        if sym == "BTCUSDT":
            close = btc_close
        elif sym == "ETHUSDT":
            # Cointegrated with BTC: log(ETH) = log(p0/45000) + 0.85 * log(BTC) + spread
            log_eth = np.log(p0) + 0.85 * (np.log(btc_close) - np.log(btc_close[0])) + ou_spread
            close = np.exp(log_eth)
        elif sym == "BNBUSDT":
            # Moderately cointegrated with BTC
            ou2 = np.zeros(n_bars)
            for i in range(1, n_bars):
                ou2[i] = ou2[i - 1] * (1 - 0.03) + np.random.normal(0, 0.003)
            log_bnb = np.log(p0) + 0.75 * (np.log(btc_close) - np.log(btc_close[0])) + ou2
            close = np.exp(log_bnb)
        else:
            # Random walk with independent noise (non-cointegrated)
            ind_noise = np.cumsum(np.random.normal(0, 0.004, n_bars))
            close = p0 * np.exp(0.4 * (market_log_price - market_log_price[0]) + ind_noise)

        high = close * (1 + np.abs(np.random.normal(0, 0.001, n_bars)))
        low = close * (1 - np.abs(np.random.normal(0, 0.001, n_bars)))
        open_p = close * (1 + np.random.normal(0, 0.0005, n_bars))
        volume = np.random.uniform(50, 500, n_bars)
        quote_vol = volume * close
        count = np.random.randint(50, 1000, n_bars)

        df = pd.DataFrame({
            "timestamp": timestamps,
            "datetime": datetimes,
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "quote_volume": quote_vol,
            "count": count
        })
        data_dict[sym] = df

    return data_dict
