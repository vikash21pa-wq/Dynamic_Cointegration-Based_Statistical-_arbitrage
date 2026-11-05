import pytest
import numpy as np
from datetime import datetime, timezone, timedelta
from src.paper_trader import PaperTradingEngine, PaperAccount


def test_candle_accumulator_tick_isolation():
    """
    Verifies that high-frequency ticks (e.g. 5-second polling) within the same 5-minute bar
    do NOT mutate or truncate the historical baseline in spread_history.
    """
    engine = PaperTradingEngine(pair="BTCUSDT/ETHUSDT")
    initial_history_len = len(engine.spread_history)
    initial_mean = engine.rolling_mean
    initial_std = engine.rolling_std

    assert initial_history_len == engine.zscore_window, f"Warmup should load {engine.zscore_window} completed 5-minute bars"
    assert initial_std > 0, "Rolling standard deviation must be positive"

    # Simulate 50 ticks spaced 5 seconds apart (spanning 250s, which is strictly INSIDE the same 5-minute candle)
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(50):
        t = base_time + timedelta(seconds=i * 5)
        # Price fluctuations
        p_a = 46000.0 + np.sin(i) * 20.0
        p_b = 2800.0 + np.cos(i) * 5.0
        snapshot = engine.process_tick(p_a, p_b, timestamp_str=t.strftime("%Y-%m-%d %H:%M:%S"))

        # The historical buffer MUST NOT be displaced by intra-candle ticks!
        assert len(engine.spread_history) == engine.zscore_window
        assert engine.rolling_mean == initial_mean
        assert engine.rolling_std == initial_std
        assert snapshot["candle_closed"] is False
        assert snapshot["ticks_in_candle"] == i + 1


def test_candle_accumulator_rollover_on_bar_close():
    """
    Verifies that when a 5-minute boundary is crossed (300 seconds), the completed candle's
    close spread is committed to spread_history, the rolling statistics update,
    and a new candle accumulator is started.
    """
    engine = PaperTradingEngine(pair="BTCUSDT/ETHUSDT")
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Tick 1: Inside Bar 0 (12:00:00)
    snap1 = engine.process_tick(46000.0, 2800.0, timestamp_str=base_time.strftime("%Y-%m-%d %H:%M:%S"))
    assert snap1["candle_closed"] is False

    # Tick 2: 4 minutes later (12:04:00) -> Still inside Bar 0
    t2 = base_time + timedelta(minutes=4)
    snap2 = engine.process_tick(46100.0, 2810.0, timestamp_str=t2.strftime("%Y-%m-%d %H:%M:%S"))
    assert snap2["candle_closed"] is False
    assert snap2["ticks_in_candle"] == 2

    # Tick 3: 5 minutes later (12:05:05) -> Crosses into Bar 1!
    t3 = base_time + timedelta(minutes=5, seconds=5)
    snap3 = engine.process_tick(46200.0, 2820.0, timestamp_str=t3.strftime("%Y-%m-%d %H:%M:%S"))

    # Bar 0 must have completed and closed!
    assert snap3["candle_closed"] is True
    assert engine.last_completed_candle is not None
    assert engine.last_completed_candle.close_a == 46100.0
    assert engine.last_completed_candle.close_b == 2810.0
    assert engine.last_completed_candle.ticks == 2
    assert len(engine.spread_history) == engine.zscore_window
    assert snap3["ticks_in_candle"] == 1  # Reset for new bar
