"""
Paper Trading Terminal Dashboard for Cryptocurrency Statistical Arbitrage.
Connects with Binance API credentials, tracks real-time Z-scores,
and executes virtual pairs trading orders.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import numpy as np

from config import (
    paper_config,
    trading_config,
    PROCESSED_DATA_DIR,
    RESULTS_DIR
)
from src.paper_trader import PaperTradingEngine


def mask_key(key: str) -> str:
    """Masks API key for secure terminal display."""
    if not key or len(key) < 10:
        return "None Configured"
    return f"{key[:6]}...{key[-4:]}"


def print_dashboard(snapshot: dict, api_key: str, mode: str = "LIVE"):
    """Renders a real-time ASCII trading terminal dashboard."""
    if sys.stdout.isatty():
        os.system("cls" if os.name == "nt" else "clear")
    pos_desc = "FLAT (No Open Position)"
    if snapshot["position_state"] == 1:
        pos_desc = f"LONG SPREAD (Long {snapshot['pair'].split('/')[0]}, Short {snapshot['pair'].split('/')[1]})"
    elif snapshot["position_state"] == -1:
        pos_desc = f"SHORT SPREAD (Short {snapshot['pair'].split('/')[0]}, Long {snapshot['pair'].split('/')[1]})"

    print("=" * 76)
    print("      BINANCE USDT-M FUTURES STATISTICAL ARBITRAGE PAPER TRADER")
    print("=" * 76)
    print(f" Mode: {mode:<18} | API Key: {mask_key(api_key):<20} | Time: {snapshot['timestamp']}")
    print(f" Target Pair: {snapshot['pair']:<12} | Engine: Zero-Secret Virtual OMS | Alloc: {trading_config.pair_gross_allocation*100:.0f}%")
    print("-" * 76)
    print(f" Asset A Price       : ${snapshot['price_a']:,.2f}")
    print(f" Asset B Price       : ${snapshot['price_b']:,.2f}")
    print(f" Spread Value        : {snapshot['spread']:+.6f}")
    print(f" Rolling Mean / Std  : {snapshot['rolling_mean']:+.6f} / {snapshot['rolling_std']:.6f}")
    print(f" Current Z-Score     : {snapshot['zscore']:+.2f} (Entry: ±{trading_config.zscore_entry}, Exit: ±{trading_config.zscore_exit})")
    print("-" * 76)
    print(f" Position State      : {pos_desc}")
    print(f" Last Signal Action  : {snapshot['action']} {('('+snapshot['reason']+')' if snapshot['reason'] else '')}")
    print("-" * 76)
    print(f" Virtual Cash Balance: ${snapshot['cash_balance']:,.2f}")
    print(f" Unrealized PnL      : ${snapshot['unrealized_pnl']:+,.2f}")
    print(f" Realized PnL        : ${snapshot['realized_pnl']:+,.2f}")
    print(f" Total Net Equity    : ${snapshot['total_equity']:,.2f} ({snapshot['pnl_pct']:+.2f}%)")
    print(f" Completed Trades    : {snapshot['total_trades']:<6} | Total Fees Paid: ${snapshot['fees_paid']:,.2f}")
    print("=" * 76)


def run_live(engine: PaperTradingEngine, interval: int = 5):
    """Continuous live market price monitoring loop."""
    print("Starting Live Paper Trading Monitor... (Press Ctrl+C to stop)")
    try:
        while True:
            price_a, price_b = engine.fetch_live_prices()
            if price_a is None or price_b is None:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Live network tick unavailable. Retrying in {interval}s...")
                time.sleep(interval)
                continue

            snapshot = engine.process_tick(price_a, price_b)
            print_dashboard(snapshot, paper_config.api_key, mode="LIVE (POLLING)")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nPaper Trading stopped by user.")


def run_replay(engine: PaperTradingEngine, speed: float = 0.05, n_bars: int = 200):
    """
    Replays recent market bars to demonstrate live state machine transitions,
    order generation, fee deductions, and mark-to-market PnL updates.
    """
    aligned_file = PROCESSED_DATA_DIR / "aligned_close_prices.csv"
    if not aligned_file.exists():
        print(f"Aligned price data not found at {aligned_file}. Run 'python main.py' first.")
        return

    df = pd.read_csv(aligned_file)
    if engine.asset_a not in df.columns or engine.asset_b not in df.columns:
        print(f"Assets {engine.asset_a} or {engine.asset_b} not found in price matrix.")
        return

    sample = df.tail(n_bars)
    print(f"Starting Paper Trading Replay on last {len(sample)} bars...")
    time.sleep(1)

    for _, row in sample.iterrows():
        p_a = float(row[engine.asset_a])
        p_b = float(row[engine.asset_b])
        ts = str(row["datetime"])

        snapshot = engine.process_tick(p_a, p_b, timestamp_str=ts)
        print_dashboard(snapshot, paper_config.api_key, mode="REPLAY / DEMO")
        time.sleep(speed)

    print("\n Replay completed. Results persisted to 'results/paper_trading_state.json'")
    if engine.account.closed_trades:
        print(f" Completed {len(engine.account.closed_trades)} round-trip paper trades.")
        print(f" Final Realized Net PnL: ${engine.account.realized_pnl:+,.2f}")


def run_single_tick(engine: PaperTradingEngine):
    """Processes a single market tick and prints dashboard."""
    price_a, price_b = engine.fetch_live_prices()
    if price_a is None or price_b is None:
        # Fall back to latest known prices from aligned price matrix
        aligned_file = PROCESSED_DATA_DIR / "aligned_close_prices.csv"
        if aligned_file.exists():
            df = pd.read_csv(aligned_file)
            price_a = float(df[engine.asset_a].iloc[-1])
            price_b = float(df[engine.asset_b].iloc[-1])
            ts = str(df["datetime"].iloc[-1])
        else:
            print("Could not retrieve live or cached market prices.")
            return
        snapshot = engine.process_tick(price_a, price_b, timestamp_str=ts)
        print_dashboard(snapshot, paper_config.api_key, mode="SNAPSHOT (CACHED)")
    else:
        snapshot = engine.process_tick(price_a, price_b)
        print_dashboard(snapshot, paper_config.api_key, mode="SNAPSHOT (LIVE)")


def show_status():
    """Prints current paper trading portfolio status from disk."""
    state_file = RESULTS_DIR / "paper_trading_state.json"
    if not state_file.exists():
        print("No active paper trading state found. Run 'python paper_trade.py --replay' or '--live' first.")
        return

    import json
    with open(state_file, "r") as f:
        data = json.load(f)

    print("\n" + "=" * 60)
    print("  CURRENT PAPER TRADING PORTFOLIO STATUS")
    print("=" * 60)
    for k, v in data.items():
        if isinstance(v, float):
            print(f"  {k:<20}: {v:,.4f}")
        else:
            print(f"  {k:<20}: {v}")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Real-Time Paper Trading Terminal for Cryptocurrency Statistical Arbitrage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python paper_trade.py --replay              # Fast replay through recent bars (instant demo)
  python paper_trade.py --live                # Real-time polling live Binance market ticks
  python paper_trade.py --pair BTCUSDT/ETHUSDT # Custom target pair
  python paper_trade.py --status              # Display active virtual portfolio status
        """
    )
    parser.add_argument("--once", action="store_true", help="Process a single market tick, print dashboard, and exit")
    parser.add_argument("--replay", action="store_true", help="Replay recent historical bars to simulate live paper trading")
    parser.add_argument("--live", action="store_true", help="Run live real-time price monitoring and trading")
    parser.add_argument("--pair", type=str, default="BTCUSDT/ETHUSDT", help="Trading pair (default: BTCUSDT/ETHUSDT)")
    parser.add_argument("--capital", type=float, default=10000.0, help="Initial paper trading balance in USD")
    parser.add_argument("--speed", type=float, default=0.03, help="Replay delay per bar in seconds")
    parser.add_argument("--bars", type=int, default=200, help="Number of bars to replay in demo mode")
    parser.add_argument("--status", action="store_true", help="Display current paper trading status from disk")

    args = parser.parse_args()

    if args.status:
        show_status()
        sys.exit(0)

    engine = PaperTradingEngine(
        pair=args.pair,
        initial_capital=args.capital
    )

    if args.once:
        run_single_tick(engine)
    elif args.live:
        run_live(engine)
    else:
        # Default to replay / demo mode for immediate testing
        run_replay(engine, speed=args.speed, n_bars=args.bars)


if __name__ == "__main__":
    main()
