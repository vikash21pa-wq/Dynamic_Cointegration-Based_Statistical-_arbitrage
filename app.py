"""
FastAPI Web Application & Real-Time Trading API with Autonomous Background Worker.
Serves the quantitative terminal dashboard and provides live endpoints & WebSocket streaming
for automated live paper trading, cointegration screening, history charts, and benchmark metrics.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
import numpy as np
import pandas as pd
import uvicorn

from config import RESULTS_DIR, PROCESSED_DATA_DIR, trading_config, market_config
from src.paper_trader import PaperTradingEngine, PaperAccount

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("crypto_stat_arb")

# Global engine and concurrency primitives
engine = PaperTradingEngine(pair="BTCUSDT/ETHUSDT")
engine_lock: Optional[asyncio.Lock] = None


def get_engine_lock() -> asyncio.Lock:
    """Lazily initializes the engine lock within the active running event loop."""
    global engine_lock
    if engine_lock is None:
        engine_lock = asyncio.Lock()
    return engine_lock


step_index = 0
latest_snapshot: Optional[Dict[str, Any]] = None

# Active WebSocket connections for real-time tick streaming
active_websockets: List[WebSocket] = []

# Worker state tracking
worker_state = {
    "running": True,
    "mode": os.environ.get("WORKER_DEFAULT_MODE", "LIVE").upper(),
    "interval_seconds": float(os.environ.get("TICK_INTERVAL_SECONDS", "3.0")),
    "ticks_processed": 0,
    "last_tick_time": None,
    "last_error": None,
    "error_count": 0,
    "consecutive_failures": 0,
}

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"


async def broadcast_ws_tick(snapshot: dict):
    """Pushes a real-time tick snapshot to all connected WebSocket clients."""
    if not active_websockets:
        return
    disconnected = []
    for ws in list(active_websockets):
        try:
            await ws.send_json(snapshot)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        if ws in active_websockets:
            try:
                active_websockets.remove(ws)
            except ValueError:
                pass


async def background_trading_worker():
    """
    Autonomous background worker that continuously polls Binance Futures prices,
    evaluates mark-to-market equilibrium against stable 5m candle bands,
    updates engine state, persists state to disk, and broadcasts ticks via WebSocket.
    """
    global latest_snapshot
    logger.info(
        f"Autonomous Paper Trading Worker initialized. Interval: {worker_state['interval_seconds']}s, Mode: {worker_state['mode']}"
    )

    while worker_state["running"]:
        if worker_state["mode"] == "LIVE":
            try:
                # Offload blocking HTTP call to threadpool to keep async loop non-blocking
                p_a, p_b = await asyncio.to_thread(engine.fetch_live_prices)

                if p_a is not None and p_b is not None:
                    async with get_engine_lock():
                        snapshot = engine.process_tick(p_a, p_b)
                        latest_snapshot = snapshot

                    worker_state["ticks_processed"] += 1
                    worker_state["last_tick_time"] = datetime.now(timezone.utc).isoformat()
                    worker_state["consecutive_failures"] = 0

                    # Broadcast tick to connected UI terminals
                    await broadcast_ws_tick(snapshot)
                else:
                    worker_state["consecutive_failures"] += 1
            except asyncio.CancelledError:
                break
            except Exception as exc:
                worker_state["error_count"] += 1
                worker_state["last_error"] = str(exc)
                logger.warning(f"Background worker tick error: {exc}")

        try:
            await asyncio.sleep(worker_state["interval_seconds"])
        except asyncio.CancelledError:
            break

    logger.info("Autonomous Background Trading Worker cleanly exited.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI Lifespan context manager: launches background tasks on startup, cleans up on shutdown."""
    global latest_snapshot

    # 1. Warm up statistical history baseline
    try:
        engine._warmup_spread_history()
    except Exception as e:
        logger.warning(f"Engine baseline warmup warning: {e}")

    # 2. Pre-load persisted state if available
    state_file = RESULTS_DIR / "paper_trading_state.json"
    if state_file.exists():
        try:
            with open(state_file, "r") as f:
                latest_snapshot = json.load(f)
        except Exception as e:
            logger.warning(f"State file load warning: {e}")

    # 3. Launch the autonomous background worker (disabled during automated test runs)
    worker_task = None
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        worker_state["running"] = True
        worker_task = asyncio.create_task(background_trading_worker())
        logger.info("Autonomous Paper Trading Background Worker started.")
    else:
        logger.info("Test environment detected (PYTEST_CURRENT_TEST); background worker loop paused.")

    yield

    # 4. Graceful shutdown
    if worker_task:
        logger.info("FastAPI server shutting down; stopping background worker...")
        worker_state["running"] = False
        worker_task.cancel()
        try:
            await asyncio.wait_for(worker_task, timeout=1.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    for ws in list(active_websockets):
        try:
            await ws.close()
        except Exception:
            pass
    active_websockets.clear()
    logger.info("Background worker shutdown complete.")


app = FastAPI(
    title="Cryptocurrency Statistical Arbitrage Dashboard",
    description="Quantitative pairs trading & live paper trading terminal with autonomous background engine",
    version="1.1.0",
    lifespan=lifespan
)

# Enable CORS for local development & cloud deployments
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint for Render/Cloud load balancers and system monitoring."""
    return {
        "status": "ok",
        "app": "crypto-stat-arb-backend",
        "worker_running": worker_state["running"],
        "worker_mode": worker_state["mode"],
        "ticks_processed": worker_state["ticks_processed"],
        "consecutive_failures": worker_state["consecutive_failures"]
    }


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serves the primary React quantitative terminal UI."""
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        index_file = Path(__file__).resolve().parent / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Frontend index.html not found.")
    with open(index_file, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.websocket("/ws/ticks")
async def websocket_ticks_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time tick streaming.
    Immediately pushes the latest snapshot upon connection, then streams live updates.
    """
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        if latest_snapshot is not None:
            await websocket.send_json(latest_snapshot)
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if websocket in active_websockets:
            active_websockets.remove(websocket)


@app.get("/api/status")
async def get_trading_status() -> Dict[str, Any]:
    """Returns the latest active paper trading portfolio snapshot enriched with worker state."""
    global latest_snapshot
    if latest_snapshot is not None:
        data = dict(latest_snapshot)
        data["worker"] = {
            "running": worker_state["running"],
            "mode": worker_state["mode"],
            "ticks_processed": worker_state["ticks_processed"],
            "last_tick_time": worker_state["last_tick_time"],
            "interval_seconds": worker_state["interval_seconds"],
        }
        return data

    state_file = RESULTS_DIR / "paper_trading_state.json"
    if state_file.exists():
        try:
            with open(state_file, "r") as f:
                data = json.load(f)
                data["worker"] = {
                    "running": worker_state["running"],
                    "mode": worker_state["mode"],
                    "ticks_processed": worker_state["ticks_processed"],
                    "last_tick_time": worker_state["last_tick_time"],
                    "interval_seconds": worker_state["interval_seconds"],
                }
                latest_snapshot = data
                return data
        except Exception:
            pass

    # Fallback to current engine state
    p_a, p_b = engine.fetch_live_prices()
    if p_a is None or p_b is None:
        p_a, p_b = 46780.93, 2835.01
    snap = engine.process_tick(p_a, p_b)
    latest_snapshot = snap
    snap["worker"] = {
        "running": worker_state["running"],
        "mode": worker_state["mode"],
        "ticks_processed": worker_state["ticks_processed"],
        "last_tick_time": worker_state["last_tick_time"],
        "interval_seconds": worker_state["interval_seconds"],
    }
    return snap


@app.get("/api/worker")
async def get_worker_status() -> Dict[str, Any]:
    """Returns real-time diagnostics of the autonomous background trading worker."""
    return {
        "status": "running" if worker_state["running"] else "stopped",
        "mode": worker_state["mode"],
        "interval_seconds": worker_state["interval_seconds"],
        "ticks_processed": worker_state["ticks_processed"],
        "last_tick_time": worker_state["last_tick_time"],
        "last_error": worker_state["last_error"],
        "error_count": worker_state["error_count"],
        "consecutive_failures": worker_state["consecutive_failures"],
        "active_websockets": len(active_websockets),
    }


@app.post("/api/worker/mode")
async def set_worker_mode(payload: Dict[str, Any]):
    """Sets worker mode to 'LIVE' or 'PAUSED'."""
    mode = str(payload.get("mode", "LIVE")).upper()
    if mode in ["LIVE", "PAUSED"]:
        worker_state["mode"] = mode
        return {"status": "ok", "mode": worker_state["mode"]}
    raise HTTPException(status_code=400, detail="Invalid mode. Choose 'LIVE' or 'PAUSED'.")


@app.post("/api/worker/tick")
async def trigger_manual_tick(payload: Optional[Dict[str, Any]] = None):
    """
    Manually triggers a price tick evaluation through the engine.
    Allows injecting prices or falling back to live Binance feed.
    """
    global latest_snapshot
    payload = payload or {}
    p_a = payload.get("price_a")
    p_b = payload.get("price_b")
    ts = payload.get("timestamp")

    if p_a is None or p_b is None:
        p_a, p_b = await asyncio.to_thread(engine.fetch_live_prices)

    if p_a is None or p_b is None:
        p_a, p_b = 46780.93, 2835.01

    async with get_engine_lock():
        snapshot = engine.process_tick(float(p_a), float(p_b), timestamp_str=ts)
        latest_snapshot = snapshot

    worker_state["ticks_processed"] += 1
    worker_state["last_tick_time"] = datetime.now(timezone.utc).isoformat()
    await broadcast_ws_tick(snapshot)
    return snapshot


@app.get("/api/history")
async def get_price_history(limit: int = 80):
    """
    Returns time series of prices, spread, rolling mean, and Z-scores
    for the primary pair chart, including live mark-to-market candle updates.
    """
    aligned_file = PROCESSED_DATA_DIR / "aligned_close_prices.csv"
    if not aligned_file.exists():
        return {"labels": [], "spreads": [], "zscores": [], "price_a": [], "price_b": []}

    df = pd.read_csv(aligned_file)
    sample = df.tail(limit)

    p_a = list(sample[engine.asset_a].values)
    p_b = list(sample[engine.asset_b].values)
    timestamps = [t.split(" ")[1][:5] if " " in str(t) else str(t) for t in sample["datetime"]]

    spreads = list(np.log(p_a) - engine.alpha - engine.beta * np.log(p_b))
    rolling_mean = pd.Series(spreads).rolling(window=min(30, len(spreads)), min_periods=5).mean().bfill().values
    rolling_std = pd.Series(spreads).rolling(window=min(30, len(spreads)), min_periods=5).std().bfill().values
    rolling_std[rolling_std == 0] = 1e-6
    zscores = (spreads - rolling_mean) / rolling_std

    # If active live tick exists, append as real-time mark-to-market data point
    if latest_snapshot and latest_snapshot.get("timestamp"):
        ts_str = str(latest_snapshot["timestamp"])
        ts_short = ts_str.split(" ")[1][:5] if " " in ts_str else ts_str[-5:]
        timestamps.append(f"{ts_short}*")
        spreads.append(float(latest_snapshot["spread"]))
        rolling_mean = np.append(rolling_mean, float(latest_snapshot["rolling_mean"]))
        rolling_std = np.append(rolling_std, float(latest_snapshot["rolling_std"]))
        zscores = np.append(zscores, float(latest_snapshot["zscore"]))
        p_a.append(float(latest_snapshot["price_a"]))
        p_b.append(float(latest_snapshot["price_b"]))

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
    """Advances paper trading engine by one market bar/tick from historical data."""
    global step_index, latest_snapshot
    async with get_engine_lock():
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
        latest_snapshot = snapshot

    await broadcast_ws_tick(snapshot)
    return snapshot


@app.post("/api/reset")
async def reset_portfolio():
    """Resets paper trading virtual balance and clears positions."""
    global step_index, latest_snapshot
    async with get_engine_lock():
        step_index = 0
        engine.account = PaperAccount(initial_balance=10000.0)
        engine.current_position_state = 0
        engine.bars_in_trade = 0
        engine.current_trade_meta = None
        engine.current_bar = None
        engine.spread_history = []
        engine._warmup_spread_history()

        # Clear disk records
        state_file = RESULTS_DIR / "paper_trading_state.json"
        trades_file = RESULTS_DIR / "paper_trades.csv"
        if trades_file.exists():
            try:
                trades_file.unlink()
            except Exception:
                pass

        snapshot = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "pair": engine.pair_name,
            "price_a": 46780.93,
            "price_b": 2835.01,
            "spread": 0.0,
            "rolling_mean": float(engine.rolling_mean),
            "rolling_std": float(engine.rolling_std),
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
            "fees_paid": 0.0,
            "candle_minutes": engine.candle_minutes,
            "candle_progress_pct": 0.0,
            "candle_elapsed_seconds": 0,
            "candle_closed": False,
            "ticks_in_candle": 0,
            "candle_open_a": 46780.93,
            "candle_open_b": 2835.01,
            "bars_in_trade": 0
        }
        with open(state_file, "w") as f:
            json.dump(snapshot, f, indent=4)
        latest_snapshot = snapshot

    await broadcast_ws_tick(snapshot)
    return snapshot


def start():
    """Starts the FastAPI web server with dynamic port resolution for Render/Cloud."""
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0"
    print("=" * 68)
    print("  LAUNCHING QUANTITATIVE CRYPTO STATISTICAL ARBITRAGE DASHBOARD")
    print("=" * 68)
    print(f"  Listening on        : http://{host}:{port}")
    print(f"  API Docs            : http://{host}:{port}/docs")
    print(f"  WebSocket Stream    : ws://{host}:{port}/ws/ticks")
    print(f"  Autonomous Worker   : Mode={worker_state['mode']} Interval={worker_state['interval_seconds']}s")
    print("=" * 68)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    start()
