"""
FastAPI Web Application & Real-Time Trading API.
Serves the quantitative terminal dashboard and provides live endpoints
for paper trading, cointegration screening, history charts, and benchmark metrics.
"""

import json
from pathlib import Path
from typing import Dict, Any, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
import numpy as np
import pandas as pd
import uvicorn

from config import RESULTS_DIR, PROCESSED_DATA_DIR, trading_config, market_config
from src.paper_trader import PaperTradingEngine, PaperAccount

app = FastAPI(
    title="Cryptocurrency Statistical Arbitrage Dashboard",
    description="Quantitative pairs trading & live paper trading terminal",
    version="1.0.0"
)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"
engine = PaperTradingEngine(pair="BTCUSDT/ETHUSDT")
step_index = 0


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serves the primary React quantitative terminal UI."""
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Frontend index.html not found.")
    with open(index_file, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/api/status")
async def get_trading_status() -> Dict[str, Any]:
    """Returns the latest active paper trading portfolio snapshot."""
    state_file = RESULTS_DIR / "paper_trading_state.json"
    if state_file.exists():
        try:
            with open(state_file, "r") as f:
                data = json.load(f)
                return data
        except Exception:
            pass

    # Fallback to current engine state
    p_a, p_b = engine.fetch_live_prices()
    if p_a is None or p_b is None:
        p_a, p_b = 46780.93, 2835.01
    return engine.process_tick(p_a, p_b)


@app.get("/api/history")
async def get_price_history(limit: int = 80):
    """
    Returns time series of prices, spread, rolling mean, and Z-scores
    for the primary pair chart.
    """
    aligned_file = PROCESSED_DATA_DIR / "aligned_close_prices.csv"
    if not aligned_file.exists():
        return {"labels": [], "spreads": [], "zscores": [], "price_a": [], "price_b": []}

    df = pd.read_csv(aligned_file)
    sample = df.tail(limit)

    p_a = sample[engine.asset_a].values
    p_b = sample[engine.asset_b].values
    timestamps = [t.split(" ")[1][:5] if " " in str(t) else str(t) for t in sample["datetime"]]

    spreads = np.log(p_a) - engine.alpha - engine.beta * np.log(p_b)
    rolling_mean = pd.Series(spreads).rolling(window=min(30, len(spreads)), min_periods=5).mean().bfill().values
    rolling_std = pd.Series(spreads).rolling(window=min(30, len(spreads)), min_periods=5).std().bfill().values
    rolling_std[rolling_std == 0] = 1e-6
    zscores = (spreads - rolling_mean) / rolling_std

    return {
        "labels": timestamps,
        "spreads": [round(float(s), 6) for s in spreads],
        "means": [round(float(m), 6) for m in rolling_mean],
        "zscores": [round(float(z), 2) for z in zscores],
        "price_a": [round(float(p), 2) for p in p_a],
        "price_b": [round(float(p), 2) for p in p_b],
        "upper_band": [round(float(m + 2.0 * s), 6) for m, s in zip(rolling_mean, rolling_std)],
        "lower_band": [round(float(m - 2.0 * s), 6) for m, s in zip(rolling_mean, rolling_std)],
    }


@app.get("/api/screening")
async def get_screening_results():
    """Returns top cointegrated pairs from the FDR screening matrix."""
    screening_file = RESULTS_DIR / "pair_screening_results.csv"
    if not screening_file.exists():
        screening_file = PROCESSED_DATA_DIR / "pair_screening_results.csv"

    if not screening_file.exists():
        return {"pairs": []}

    df = pd.read_csv(screening_file)
    cols = ["pair", "correlation", "beta", "coint_t_stat", "p_value", "fdr_q_value", "half_life_hours", "eligible"]
    available = [c for c in cols if c in df.columns]
    records = df[available].head(15).to_dict(orient="records")
    for r in records:
        r["correlation"] = round(float(r["correlation"]), 3)
        r["beta"] = round(float(r["beta"]), 4)
        r["coint_t_stat"] = round(float(r["coint_t_stat"]), 2)
        r["half_life_hours"] = f"{float(r['half_life_hours']):.2f}h"
        r["eligible"] = bool(r["eligible"])
    return JSONResponse(content={"pairs": records})


@app.get("/api/benchmark")
async def get_benchmark_comparison():
    """Returns comparative backtest metrics (M1 Static OLS vs M3 Dynamic Kalman Filter)."""
    summary_file = RESULTS_DIR / "experiment_001_summary.json"
    if not summary_file.exists():
        summary_file = PROCESSED_DATA_DIR / "experiment_001_summary.json"

    if not summary_file.exists():
        raise HTTPException(status_code=404, detail="Benchmark summary not generated yet.")

    with open(summary_file, "r") as f:
        return json.load(f)


@app.get("/api/trades")
async def get_trade_history():
    """Returns all completed paper trading round-trip orders."""
    trades_file = RESULTS_DIR / "paper_trades.csv"
    if not trades_file.exists():
        return {"trades": []}

    df = pd.read_csv(trades_file)
    records = df.to_dict(orient="records")
    for r in records:
        r["gross_pnl"] = f"${float(r.get('gross_pnl', 0)):+,.2f}"
        r["fees_paid"] = f"${float(r.get('fees_paid', 0)):,.2f}"
        r["net_pnl"] = f"${float(r.get('net_pnl', 0)):+,.2f}"
        r["account_equity"] = f"${float(r.get('account_equity', 10000)):,.2f}"
    return JSONResponse(content={"trades": records})


@app.get("/api/market")
async def get_market_overview():
    """Returns current prices and 24h metrics for assets in universe."""
    aligned_file = PROCESSED_DATA_DIR / "aligned_close_prices.csv"
    if not aligned_file.exists():
        return {"assets": []}

    df = pd.read_csv(aligned_file)
    latest = df.iloc[-1]
    prev = df.iloc[-288] if len(df) >= 288 else df.iloc[0]

    assets = []
    for col in df.columns:
        if col in ["datetime", "timestamp"]:
            continue
        curr_p = float(latest[col])
        prev_p = float(prev[col])
        chg_pct = ((curr_p - prev_p) / prev_p) * 100.0
        assets.append({
            "symbol": col,
            "price": f"${curr_p:,.2f}" if curr_p >= 1.0 else f"${curr_p:.4f}",
            "change_24h": f"{chg_pct:+.2f}%",
            "is_positive": chg_pct >= 0
        })

    return {"assets": assets}


@app.post("/api/step")
async def step_simulation():
    """Advances paper trading engine by one market bar/tick."""
    global step_index
    aligned_file = PROCESSED_DATA_DIR / "aligned_close_prices.csv"
    if aligned_file.exists():
        df = pd.read_csv(aligned_file)
        idx = (8500 + step_index) % len(df)
        step_index += 1
        row = df.iloc[idx]
        p_a, p_b = float(row[engine.asset_a]), float(row[engine.asset_b])
        ts = str(row["datetime"])
    else:
        p_a, p_b = 46780.93, 2835.01
        ts = None

    snapshot = engine.process_tick(p_a, p_b, timestamp_str=ts)
    return snapshot


@app.post("/api/reset")
async def reset_portfolio():
    """Resets paper trading virtual balance and clears positions."""
    global step_index
    step_index = 0
    engine.account = PaperAccount(initial_balance=10000.0)
    engine.current_position_state = 0
    engine.bars_in_trade = 0
    engine.current_trade_meta = None
    engine.spread_history = []
    engine._warmup_spread_history()

    # Clear disk records
    state_file = RESULTS_DIR / "paper_trading_state.json"
    trades_file = RESULTS_DIR / "paper_trades.csv"
    if trades_file.exists():
        trades_file.unlink()

    snapshot = {
        "timestamp": "Reset State",
        "pair": engine.pair_name,
        "price_a": 46780.93,
        "price_b": 2835.01,
        "spread": 0.0,
        "rolling_mean": 0.0,
        "rolling_std": 0.005,
        "zscore": 0.0,
        "position_state": 0,
        "action": "RESET",
        "reason": "User reset",
        "cash_balance": 10000.0,
        "unrealized_pnl": 0.0,
        "realized_pnl": 0.0,
        "total_equity": 10000.0,
        "pnl_pct": 0.0,
        "total_trades": 0,
        "fees_paid": 0.0
    }
    with open(state_file, "w") as f:
        json.dump(snapshot, f, indent=4)

    return snapshot


def start():
    """Starts the FastAPI web server on port 8000."""
    print("=" * 65)
    print("  LAUNCHING QUANTITATIVE CRYPTO STATISTICAL ARBITRAGE DASHBOARD")
    print("=" * 65)
    print("  Web Interface : http://localhost:8000")
    print("  API Docs      : http://localhost:8000/docs")
    print("=" * 65)
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    start()
