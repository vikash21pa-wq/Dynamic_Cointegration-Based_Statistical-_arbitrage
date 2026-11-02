"""
Main Orchestration Pipeline for Experiment 001.
Dynamic Cointegration-Based Statistical Arbitrage in Cryptocurrency Markets.

Terminal CLI supporting live Binance USDT-M data, cached matrices, synthetic markets,
pair screening, walk-forward simulation, and instant results viewing.
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any

import pandas as pd
import numpy as np

from config import (
    market_config,
    selection_config,
    trading_config,
    kalman_config,
    PROCESSED_DATA_DIR,
    RAW_DATA_DIR,
    RESULTS_DIR
)


def setup_logger(quiet: bool = False) -> logging.Logger:
    """Configures clean terminal logging."""
    log_level = logging.WARNING if quiet else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )
    return logging.getLogger("CryptoStatArb")


def display_saved_results(processed_dir: Path = PROCESSED_DATA_DIR, results_dir: Path = RESULTS_DIR):
    """
    Instantly displays previously calculated experiment results and screening tables.
    Executes in milliseconds without re-computing models.
    """
    summary_file = results_dir / "experiment_001_summary.json"
    if not summary_file.exists():
        summary_file = processed_dir / "experiment_001_summary.json"

    screening_file = results_dir / "pair_screening_results.csv"
    if not screening_file.exists():
        screening_file = processed_dir / "pair_screening_results.csv"

    print("\n" + "=" * 78)
    print("  DYNAMIC COINTEGRATION STATISTICAL ARBITRAGE - EXPERIMENT RESULTS")
    print("=" * 78)

    if not summary_file.exists():
        print(f"No previous experiment summary found at: {summary_file}")
        print("Run the experiment first: python main.py")
        return

    with open(summary_file, "r") as f:
        summary = json.load(f)

    print(f"\n  Experiment       : {summary.get('experiment', 'Experiment 001')}")
    print(f"  Selected Pair    : {summary.get('selected_pair', 'N/A')}")
    print(f"  Timeframe        : {summary.get('timeframe', '5m')} (Aligned Bars: {summary.get('total_bars_aligned', 'N/A'):,})")
    print(f"  Universe Size    : {len(summary.get('universe', []))} assets ({summary.get('total_pairs_screened', 45)} candidate pairs)")
    print(f"  Cointegrated     : {summary.get('eligible_cointegrated_pairs_count', 0)} eligible under FDR correction")

    m1 = summary.get("m1_static_ols", {})
    m3 = summary.get("m3_kalman_filter", {})

    metrics_rows = [
        ("Initial Capital", f"${m1.get('initial_capital', 10000):,.2f}", f"${m3.get('initial_capital', 10000):,.2f}"),
        ("Final Equity", f"${m1.get('final_equity', 0):,.2f}", f"${m3.get('final_equity', 0):,.2f}"),
        ("Net Profit ($)", f"${m1.get('net_profit', 0):+,.2f}", f"${m3.get('net_profit', 0):+,.2f}"),
        ("Total Net Return (%)", f"{m1.get('total_net_return_pct', 0):+.2f}%", f"{m3.get('total_net_return_pct', 0):+.2f}%"),
        ("Annualized Return (%)", f"{m1.get('annualized_return_pct', 0):+.2f}%", f"{m3.get('annualized_return_pct', 0):+.2f}%"),
        ("Annualized Sharpe Ratio", f"{m1.get('annualized_sharpe_ratio', 0):.2f}", f"{m3.get('annualized_sharpe_ratio', 0):.2f}"),
        ("Annualized Sortino Ratio", f"{m1.get('annualized_sortino_ratio', 0):.2f}", f"{m3.get('annualized_sortino_ratio', 0):.2f}"),
        ("Maximum Drawdown (%)", f"{m1.get('max_drawdown_pct', 0):.2f}%", f"{m3.get('max_drawdown_pct', 0):.2f}%"),
        ("Calmar Ratio", f"{m1.get('calmar_ratio', 0):.2f}", f"{m3.get('calmar_ratio', 0):.2f}"),
        ("Total Completed Trades", f"{m1.get('total_trades_completed', 0)}", f"{m3.get('total_trades_completed', 0)}"),
        ("Win Rate (%)", f"{m1.get('win_rate_pct', 0):.1f}%", f"{m3.get('win_rate_pct', 0):.1f}%"),
        ("Profit Factor", f"{m1.get('profit_factor', 0):.2f}", f"{m3.get('profit_factor', 0):.2f}"),
        ("Avg Holding Time (Hours)", f"{m1.get('avg_holding_hours', 0):.2f}h", f"{m3.get('avg_holding_hours', 0):.2f}h"),
        ("Total Costs Paid ($)", f"${m1.get('total_costs_paid', 0):.2f}", f"${m3.get('total_costs_paid', 0):.2f}"),
    ]

    print("\n" + "-" * 78)
    print(f"{'Performance Metric':<28} | {'M1 (Static OLS)':<22} | {'M3 (Kalman Filter)':<22}")
    print("-" * 78)
    for name, v1, v3 in metrics_rows:
        print(f"{name:<28} | {v1:<22} | {v3:<22}")
    print("-" * 78)

    if screening_file.exists():
        screening_df = pd.read_csv(screening_file)
        display_cols = ["pair", "correlation", "beta", "coint_t_stat", "p_value", "fdr_q_value", "half_life_hours", "eligible"]
        available_cols = [c for c in display_cols if c in screening_df.columns]
        print("\nTop 5 Cointegrated Pairs from Screening Leaderboard:")
        print(screening_df[available_cols].head(5).to_string(index=False))
        print("-" * 78)

    print("\n Artifacts stored in:")
    print(f"  - {summary_file}")
    if screening_file.exists():
        print(f"  - {screening_file}")
    print("=" * 78 + "\n")


def run_experiment(
    days: int = 30,
    force_refresh: bool = False,
    use_synthetic: bool = False,
    screen_only: bool = False,
    custom_pair: Optional[str] = None,
    method: str = "all",
    capital: Optional[float] = None,
    allocation: Optional[float] = None,
    export_results: bool = True,
    quiet: bool = False
) -> Dict[str, Any]:
    """
    Executes the quantitative statistical arbitrage research pipeline.
    """
    logger = setup_logger(quiet=quiet)

    from src.data_loader import BinanceFuturesDataLoader, generate_synthetic_futures_data
    from src.preprocessing import DataPreprocessor
    from src.pair_selection import PairSelectionEngine
    from src.backtester import PairsBacktester

    initial_capital = capital if capital is not None else trading_config.initial_capital
    pair_allocation = allocation if allocation is not None else trading_config.pair_gross_allocation

    print("\n" + "=" * 80)
    print("  DYNAMIC COINTEGRATION STATISTICAL ARBITRAGE - CRYPTOCURRENCY MARKETS")
    print("=" * 80)
    logger.info(f"Universe: {', '.join(market_config.universe)}")
    logger.info(f"Timeframe: {market_config.timeframe} | History: {days} days")
    logger.info(f"Simulated Capital: ${initial_capital:,.2f} | Leverage: {trading_config.leverage}x | Allocation: {pair_allocation*100:.1f}%")

    # -------------------------------------------------------------
    # STAGE 1: DATA ENGINEERING & COLLECTION
    # -------------------------------------------------------------
    logger.info("\n--- [STAGE 1/4] DATA ENGINEERING & COLLECTION ---")
    data_loader = BinanceFuturesDataLoader(raw_dir=RAW_DATA_DIR)
    raw_data = None

    if use_synthetic:
        logger.info("Using calibrated synthetic multi-asset crypto dataset...")
        raw_data = generate_synthetic_futures_data(
            symbols=market_config.universe,
            n_bars=days * 288,
            seed=42
        )
    else:
        logger.info("Querying Binance USDT-M Perpetual Futures 5m candles...")
        try:
            downloaded = data_loader.download_universe(
                symbols=market_config.universe,
                days=days,
                interval=market_config.timeframe,
                force_refresh=force_refresh
            )
            if downloaded and len(downloaded) >= len(market_config.universe):
                raw_data = downloaded
            else:
                raise RuntimeError("Incomplete universe downloaded from exchange.")
        except Exception as e:
            logger.warning(f"Live network download unavailable ({e}). Falling back to calibrated market dataset.")
            raw_data = generate_synthetic_futures_data(
                symbols=market_config.universe,
                n_bars=days * 288,
                seed=42
            )

    # -------------------------------------------------------------
    # STAGE 2: PREPROCESSING & QUALITY AUDIT
    # -------------------------------------------------------------
    logger.info("\n--- [STAGE 2/4] PREPROCESSING & QUALITY AUDIT ---")
    preprocessor = DataPreprocessor(processed_dir=PROCESSED_DATA_DIR)
    quality_report_df = preprocessor.generate_quality_report(raw_data)
    
    if not quiet:
        print("\nData Quality Summary:")
        print(quality_report_df[["symbol", "row_count", "missing_gaps_count", "outlier_5sigma_returns", "status"]].to_string(index=False))

    aligned_close, aligned_log, aligned_ret = preprocessor.synchronize_universe(raw_data, save_csv=True)
    logger.info(f"Synchronized price matrix: {aligned_close.shape[0]} bars x {aligned_close.shape[1]} assets.")

    # -------------------------------------------------------------
    # STAGE 3: STATISTICAL SCREENING & FDR COINTEGRATION
    # -------------------------------------------------------------
    logger.info("\n--- [STAGE 3/4] STATISTICAL SCREENING & FDR COINTEGRATION ---")
    pair_engine = PairSelectionEngine(
        min_correlation=selection_config.min_correlation,
        coint_alpha=selection_config.cointegration_alpha,
        fdr_alpha=selection_config.fdr_alpha,
        require_positive_beta=selection_config.require_positive_beta,
        max_half_life_bars=selection_config.max_half_life_bars,
        processed_dir=PROCESSED_DATA_DIR
    )

    if custom_pair:
        parts = custom_pair.replace("-", "/").split("/")
        if len(parts) == 2 and parts[0] in aligned_close.columns and parts[1] in aligned_close.columns:
            sym_a, sym_b = parts[0], parts[1]
            pair_name = f"{sym_a}/{sym_b}"
            logger.info(f"Direct pair requested: {pair_name}. Running statistical analysis on target pair...")
            pair_stats = pair_engine.analyze_pair(
                log_price_a=aligned_log[sym_a],
                log_price_b=aligned_log[sym_b],
                log_returns_a=aligned_ret[sym_a],
                log_returns_b=aligned_ret[sym_b]
            )
            pair_stats["asset_A"] = sym_a
            pair_stats["asset_B"] = sym_b
            pair_stats["pair"] = pair_name
            pair_stats["fdr_q_value"] = pair_stats["p_value"]
            pair_stats["fdr_significant"] = pair_stats["p_value"] <= selection_config.fdr_alpha
            pair_stats["eligible"] = (
                pair_stats["correlation"] >= selection_config.min_correlation and
                pair_stats["p_value"] <= selection_config.cointegration_alpha and
                pair_stats["beta"] > 0
            )
            target_pair = pd.Series(pair_stats)
            screening_results = pd.DataFrame([pair_stats])
            eligible_pairs = screening_results[screening_results["eligible"] == True]
        else:
            logger.error(f"Pair '{custom_pair}' invalid or symbols not in universe. Screening entire universe...")
            screening_results = pair_engine.screen_universe(
                aligned_log_prices=aligned_log,
                aligned_log_returns=aligned_ret,
                lookback_bars=min(len(aligned_log), selection_config.training_bars)
            )
            eligible_pairs = screening_results[screening_results["eligible"] == True]
            target_pair = eligible_pairs.iloc[0] if not eligible_pairs.empty else screening_results.iloc[0]
    else:
        screening_results = pair_engine.screen_universe(
            aligned_log_prices=aligned_log,
            aligned_log_returns=aligned_ret,
            lookback_bars=min(len(aligned_log), selection_config.training_bars)
        )
        eligible_pairs = screening_results[screening_results["eligible"] == True]
        target_pair = eligible_pairs.iloc[0] if not eligible_pairs.empty else screening_results.iloc[0]

    logger.info(f"Screening complete: {len(screening_results)} pairs tested, {len(eligible_pairs)} passed all statistical filters.")

    display_cols = ["pair", "correlation", "beta", "coint_t_stat", "p_value", "fdr_q_value", "half_life_hours", "eligible"]
    available_cols = [c for c in display_cols if c in screening_results.columns]
    print("\nTop Candidate Pairs Ranked by Cointegration Strength:", flush=True)
    print(screening_results[available_cols].head(10).to_string(index=False), flush=True)

    # Also save to results directory
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    screening_results.to_csv(RESULTS_DIR / "pair_screening_results.csv", index=False)

    if screen_only:
        print("\nScreen-only mode requested. Terminating before backtest simulation.", flush=True)
        return {"screening_results": screening_results}

    # -------------------------------------------------------------
    # STAGE 4: MODEL SIMULATION & WALK-FORWARD COMPARISON
    # -------------------------------------------------------------
    logger.info("\n--- [STAGE 4/4] MODEL SIMULATION & EXECUTION ---")

    sym_a = target_pair["asset_A"]
    sym_b = target_pair["asset_B"]
    pair_name = target_pair["pair"]
    beta_static = float(target_pair["beta"])
    alpha_static = float(target_pair["alpha"])

    logger.info(f"Target Pair for Simulation: {pair_name}")
    logger.info(f"Parameters: Static Beta={beta_static:.4f}, Alpha={alpha_static:.4f}, Half-Life={target_pair.get('half_life_hours', 0):.2f}h")

    backtester = PairsBacktester(
        initial_capital=initial_capital,
        pair_allocation=pair_allocation,
        fee_pct=trading_config.taker_fee_pct,
        slippage_pct=trading_config.slippage_pct,
        funding_rate_8h=trading_config.default_funding_rate_8h
    )

    m1_result = None
    m3_result = None

    if method in ["all", "ols"]:
        logger.info("Simulating Model M1: Static OLS Cointegration...")
        m1_result = backtester.run_pair_simulation(
            price_a=aligned_close[sym_a],
            price_b=aligned_close[sym_b],
            alpha=alpha_static,
            beta=beta_static,
            pair_name=pair_name,
            use_kalman=False
        )

    if method in ["all", "kalman"]:
        logger.info("Simulating Model M3: Dynamic Kalman Filter Hedge Ratio...")
        m3_result = backtester.run_pair_simulation(
            price_a=aligned_close[sym_a],
            price_b=aligned_close[sym_b],
            alpha=alpha_static,
            beta=beta_static,
            pair_name=pair_name,
            use_kalman=True
        )

    # -------------------------------------------------------------
    # DISPLAY & SAVE RESULTS
    # -------------------------------------------------------------
    comparison_data: Dict[str, List[Any]] = {
        "Metric": [
            "Total Net Return (%)",
            "Annualized Return (%)",
            "Annualized Sharpe Ratio",
            "Annualized Sortino Ratio",
            "Maximum Drawdown (%)",
            "Calmar Ratio",
            "Total Trades Completed",
            "Win Rate (%)",
            "Profit Factor",
            "Avg Holding Time (Hours)",
            "Total Trading Costs ($)"
        ]
    }

    if m1_result is not None:
        m1_m = m1_result["metrics"]
        comparison_data["M1 (Static OLS)"] = [
            f"{m1_m['total_net_return_pct']:.2f}%",
            f"{m1_m['annualized_return_pct']:.2f}%",
            f"{m1_m['annualized_sharpe_ratio']:.2f}",
            f"{m1_m['annualized_sortino_ratio']:.2f}",
            f"{m1_m['max_drawdown_pct']:.2f}%",
            f"{m1_m['calmar_ratio']:.2f}",
            m1_m['total_trades_completed'],
            f"{m1_m['win_rate_pct']:.1f}%",
            f"{m1_m['profit_factor']:.2f}",
            f"{m1_m['avg_holding_hours']:.1f}h",
            f"${m1_m['total_costs_paid']:.2f}"
        ]

    if m3_result is not None:
        m3_m = m3_result["metrics"]
        comparison_data["M3 (Kalman Filter)"] = [
            f"{m3_m['total_net_return_pct']:.2f}%",
            f"{m3_m['annualized_return_pct']:.2f}%",
            f"{m3_m['annualized_sharpe_ratio']:.2f}",
            f"{m3_m['annualized_sortino_ratio']:.2f}",
            f"{m3_m['max_drawdown_pct']:.2f}%",
            f"{m3_m['calmar_ratio']:.2f}",
            m3_m['total_trades_completed'],
            f"{m3_m['win_rate_pct']:.1f}%",
            f"{m3_m['profit_factor']:.2f}",
            f"{m3_m['avg_holding_hours']:.1f}h",
            f"${m3_m['total_costs_paid']:.2f}"
        ]

    comparison_df = pd.DataFrame(comparison_data)
    print("\n" + "=" * 70)
    print(f"  PERFORMANCE BENCHMARK: {pair_name}")
    print("=" * 70)
    print(comparison_df.to_string(index=False))
    print("=" * 70)

    # Save summary json
    summary_data = {
        "experiment": "Experiment 001 - Baseline Static vs Dynamic Cointegration",
        "universe": market_config.universe,
        "timeframe": market_config.timeframe,
        "total_bars_aligned": len(aligned_close),
        "total_pairs_screened": len(screening_results),
        "eligible_cointegrated_pairs_count": int(screening_results["eligible"].sum()),
        "selected_pair": pair_name,
        "m1_static_ols": m1_result["metrics"] if m1_result else None,
        "m3_kalman_filter": m3_result["metrics"] if m3_result else None
    }

    for target_dir in [PROCESSED_DATA_DIR, RESULTS_DIR]:
        summary_path = target_dir / "experiment_001_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary_data, f, indent=4)
        comparison_df.to_csv(target_dir / "experiment_001_comparison.csv", index=False)

    if export_results:
        if m1_result and not m1_result["trades"].empty:
            m1_result["trades"].to_csv(RESULTS_DIR / "m1_trades.csv", index=False)
        if m3_result and not m3_result["trades"].empty:
            m3_result["trades"].to_csv(RESULTS_DIR / "m3_trades.csv", index=False)
        logger.info(f"Exported simulation logs to {RESULTS_DIR}")

    return summary_data


def main():
    parser = argparse.ArgumentParser(
        description="Dynamic Cointegration Statistical Arbitrage Framework for Cryptocurrency Markets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py -r                                 # Instantly display cached results
  python main.py                                    # Run standard 30-day pipeline
  python main.py --synthetic                        # Run with calibrated synthetic market
  python main.py --screen-only                      # Screen all 45 pairs without backtesting
  python main.py --pair BTCUSDT/ETHUSDT             # Backtest a specific pair
  python main.py --method ols                       # Run only Static OLS model
  python main.py --capital 25000 --allocation 0.15  # Custom capital and allocation
        """
    )
    parser.add_argument("-r", "--results", "--view-results", action="store_true", dest="view_results",
                        help="Instantly view saved experiment results and screening leaderboard")
    parser.add_argument("--days", type=int, default=30,
                        help="Number of days of 5m historical candles (default: 30)")
    parser.add_argument("--pair", type=str, default=None,
                        help="Specific pair to backtest (e.g., BTCUSDT/ETHUSDT)")
    parser.add_argument("--method", choices=["all", "ols", "kalman"], default="all",
                        help="Trading model to simulate (default: all)")
    parser.add_argument("--capital", type=float, default=None,
                        help="Initial portfolio capital in USD (default: $10,000)")
    parser.add_argument("--allocation", type=float, default=None,
                        help="Gross notional capital allocation fraction per pair (default: 0.10)")
    parser.add_argument("--screen-only", action="store_true",
                        help="Perform universe cointegration screening only")
    parser.add_argument("--synthetic", action="store_true",
                        help="Run using calibrated synthetic market test data")
    parser.add_argument("--refresh", action="store_true",
                        help="Force refresh Binance USDT-M Futures data")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress detailed logs, output only tables")

    args = parser.parse_args()

    if args.view_results:
        display_saved_results()
        sys.exit(0)

    run_experiment(
        days=args.days,
        force_refresh=args.refresh,
        use_synthetic=args.synthetic,
        screen_only=args.screen_only,
        custom_pair=args.pair,
        method=args.method,
        capital=args.capital,
        allocation=args.allocation,
        quiet=args.quiet
    )


if __name__ == "__main__":
    main()
