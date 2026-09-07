"""
backtest.py
Walks through historical candles, generates signals with strategy.py, and
simulates each trade forward (checking which of SL/TP1/TP2 gets hit first)
to see how the strategy would ACTUALLY have performed -- this is the "learn
from past candle reactions" piece, not just indicator guesswork.

Also runs a small grid search over the tunable thresholds in strategy.py and
saves whichever combination performed best to best_params.json, which bot.py
loads at runtime.

Usage:
    python backtest.py                # uses cached data (data_feed cache/)
"""

import json
import itertools
import os
import pandas as pd
import numpy as np

from indicators import compute_all_indicators
from strategy import generate_signal, add_obv_slope, DEFAULT_PARAMS

RESULTS_PATH = os.path.join(os.path.dirname(__file__), "best_params.json")


def simulate_trades(df: pd.DataFrame, params: dict, max_bars_forward: int = 100):
    """
    For every bar, generate a signal; if it's BUY/SELL, walk forward bar by bar
    until SL, TP1, or TP2 is hit (or we run out of bars). Returns a list of
    trade result dicts.
    """
    trades = []
    n = len(df)

    for i in range(200, n - 1):  # need lookback warmup + room to walk forward
        row = df.iloc[i]
        sig = generate_signal(row, params)
        if sig.side == "NO_TRADE":
            continue

        outcome = "OPEN"
        exit_price = None
        bars_held = 0

        for j in range(i + 1, min(i + 1 + max_bars_forward, n)):
            bar = df.iloc[j]
            bars_held += 1
            if sig.side == "BUY":
                hit_sl = bar["low"] <= sig.sl
                hit_tp2 = bar["high"] >= sig.tp2
                hit_tp1 = bar["high"] >= sig.tp1
            else:
                hit_sl = bar["high"] >= sig.sl
                hit_tp2 = bar["low"] <= sig.tp2
                hit_tp1 = bar["low"] <= sig.tp1

            # Conservative: if SL and a TP hit the same bar, count it as SL
            # (we don't know which came first intrabar -- don't overstate wins).
            if hit_sl:
                outcome = "SL"
                exit_price = sig.sl
                break
            elif hit_tp2:
                outcome = "TP2"
                exit_price = sig.tp2
                break
            elif hit_tp1:
                outcome = "TP1"
                exit_price = sig.tp1
                break

        trades.append({
            "time": df.index[i],
            "side": sig.side,
            "regime": sig.regime,
            "confidence": sig.confidence,
            "entry": sig.entry,
            "outcome": outcome,
            "bars_held": bars_held,
        })

    return trades


def score_trades(trades: list) -> dict:
    closed = [t for t in trades if t["outcome"] != "OPEN"]
    if not closed:
        return {"n_trades": 0, "win_rate": 0.0, "score": -1}

    wins = [t for t in closed if t["outcome"] in ("TP1", "TP2")]
    win_rate = len(wins) / len(closed)

    # Reward more trades too, but not at the expense of win rate --
    # a 90% win rate on 3 trades isn't as trustworthy as 65% on 80 trades.
    sample_confidence = min(len(closed) / 50, 1.0)
    score = win_rate * (0.5 + 0.5 * sample_confidence)

    return {
        "n_trades": len(closed),
        "win_rate": round(win_rate, 3),
        "score": round(score, 4),
    }


def grid_search(df: pd.DataFrame) -> dict:
    adx_options = [18, 22, 26]
    trend_thresh_options = [0.55, 0.65, 0.75]
    range_thresh_options = [0.55, 0.65, 0.75]

    best = None
    best_stats = None

    for adx_t, trend_t, range_t in itertools.product(
        adx_options, trend_thresh_options, range_thresh_options
    ):
        params = {
            **DEFAULT_PARAMS,
            "adx_trend_threshold": adx_t,
            "score_threshold_trend": trend_t,
            "score_threshold_range": range_t,
        }
        trades = simulate_trades(df, params)
        stats = score_trades(trades)

        if best is None or stats["score"] > best_stats["score"]:
            best = params
            best_stats = stats

    return best, best_stats


def run_backtest(df: pd.DataFrame):
    df = compute_all_indicators(df)
    df = add_obv_slope(df)
    best_params, best_stats = grid_search(df)

    result = {"params": best_params, "stats": best_stats}
    with open(RESULTS_PATH, "w") as f:
        json.dump(result, f, indent=2, default=str)

    return result


if __name__ == "__main__":
    cache_path = os.path.join(os.path.dirname(__file__), "cache", "XAUUSD_15min.csv")

    if os.path.exists(cache_path):
        df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        result = run_backtest(df)
        print(json.dumps(result, indent=2, default=str))
    else:
        # Offline self-test with synthetic data, since the sandbox has no
        # internet to pull real Twelve Data history. Real cached data will
        # be used automatically once it exists on Render.
        rng = np.random.default_rng(3)
        n = 1500
        price = 2000 + np.cumsum(rng.normal(0, 1.2, n))
        high = price + rng.uniform(0.5, 2.0, n)
        low = price - rng.uniform(0.5, 2.0, n)
        open_ = price + rng.normal(0, 0.4, n)
        close = price + rng.normal(0, 0.4, n)
        volume = rng.uniform(100, 1000, n)
        df = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
            index=pd.date_range("2026-01-01", periods=n, freq="15min"),
        )
        result = run_backtest(df)
        print("Self-test (synthetic data) OK.")
        print(json.dumps(result, indent=2, default=str))
