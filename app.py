"""
FastAPI Web Application & Real-Time Trading API.
Serves the quantitative terminal dashboard and provides live endpoints
for paper trading, cointegration screening, and benchmark metrics.
"""

import json
from pathlib import Path
from typing import Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
import pandas as pd
import uvicorn

from config import RESULTS_DIR, PROCESSED_DATA_DIR, trading_config
from src.paper_trader import PaperTradingEngine

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


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serves the primary quantitative terminal UI."""
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
                return json.load(f)
        except Exception:
            pass

    # Fallback to current engine state
    p_a, p_b = engine.fetch_live_prices()
    if p_a is None or p_b is None:
        p_a, p_b = 46780.93, 2835.01
    return engine.process_tick(p_a, p_b)


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
    return JSONResponse(content={"pairs": df[available].head(15).to_dict(orient="records")})


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
    return JSONResponse(content={"trades": df.to_dict(orient="records")})


@app.post("/api/step")
async def step_simulation():
    """Advances paper trading engine by one market bar/tick."""
    p_a, p_b = engine.fetch_live_prices()
    if p_a is None or p_b is None:
        # Step using aligned dataset
        aligned_file = PROCESSED_DATA_DIR / "aligned_close_prices.csv"
        if aligned_file.exists():
            df = pd.read_csv(aligned_file)
            row = df.sample(1).iloc[0]
            p_a, p_b = float(row[engine.asset_a]), float(row[engine.asset_b])
        else:
            p_a, p_b = 46780.93, 2835.01

    snapshot = engine.process_tick(p_a, p_b)
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
