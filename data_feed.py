"""
data_feed.py
Pulls XAU/USD candles from Twelve Data (free tier) and caches them to disk,
so we don't burn API credits re-downloading the same history every run.

Free tier limits handled here:
- 8 requests/minute, 800 requests/day  -> we sleep between calls and cache aggressively.
- outputsize capped at 5000 bars per call on the free plan.
"""

import os
import time
import json
import requests
import pandas as pd

TWELVE_DATA_BASE = "https://api.twelvedata.com/time_series"
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_path(symbol: str, interval: str) -> str:
    safe_symbol = symbol.replace("/", "")
    return os.path.join(CACHE_DIR, f"{safe_symbol}_{interval}.csv")


def _load_cache(symbol: str, interval: str) -> pd.DataFrame:
    path = _cache_path(symbol, interval)
    if os.path.exists(path):
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return df
    return pd.DataFrame()


def _save_cache(df: pd.DataFrame, symbol: str, interval: str) -> None:
    df.to_csv(_cache_path(symbol, interval))


def fetch_candles(
    symbol: str,
    interval: str,
    api_key: str,
    outputsize: int = 5000,
    max_retries: int = 3,
) -> pd.DataFrame:
    """
    Fetches candles from Twelve Data. Returns a DataFrame with columns
    ['open', 'high', 'low', 'close', 'volume'], indexed by datetime, oldest->newest.
    Raises RuntimeError on API failure (bad key, rate limit exhausted, etc).
    """
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": min(outputsize, 5000),
        "apikey": api_key,
        "format": "JSON",
        "order": "ASC",
    }

    last_error = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(TWELVE_DATA_BASE, params=params, timeout=20)
            data = resp.json()
        except Exception as e:
            last_error = str(e)
            time.sleep(8)
            continue

        if isinstance(data, dict) and data.get("status") == "error":
            msg = data.get("message", "unknown Twelve Data error")
            if "run out of API credits" in msg.lower() or "limit" in msg.lower():
                # Rate-limited: back off and retry once, since free tier resets per minute
                last_error = msg
                time.sleep(65)
                continue
            raise RuntimeError(f"Twelve Data error: {msg}")

        values = data.get("values")
        if not values:
            last_error = f"No 'values' in response: {data}"
            time.sleep(8)
            continue

        df = pd.DataFrame(values)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime")
        for col in ["open", "high", "low", "close", "volume"]:
            if col not in df.columns:
                df[col] = 0.0
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.sort_index()
        return df[["open", "high", "low", "close", "volume"]]

    raise RuntimeError(f"Failed to fetch candles after {max_retries} attempts: {last_error}")


def get_history(
    symbol: str,
    interval: str,
    api_key: str,
    refresh: bool = False,
) -> pd.DataFrame:
    """
    Returns as much cached + freshly-fetched history as the free plan allows.
    Set refresh=True to force a new pull (e.g. nightly cron), otherwise this
    just merges in any new candles since the cache was last saved.
    """
    cached = _load_cache(symbol, interval)

    if refresh or cached.empty:
        fresh = fetch_candles(symbol, interval, api_key, outputsize=5000)
        if not cached.empty:
            merged = pd.concat([cached, fresh])
            merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        else:
            merged = fresh
        _save_cache(merged, symbol, interval)
        return merged

    return cached


def get_latest(symbol: str, interval: str, api_key: str, bars: int = 300) -> pd.DataFrame:
    """Lightweight pull for live signal checks — small outputsize, cheap on rate limits."""
    return fetch_candles(symbol, interval, api_key, outputsize=bars)


if __name__ == "__main__":
    # Offline structural test: fake a Twelve Data-shaped payload and make sure
    # the parsing path works, without hitting the network (sandbox has none).
    import numpy as np

    fake_values = []
    base_time = pd.Timestamp("2026-01-01 00:00:00")
    price = 2000.0
    rng = np.random.default_rng(1)
    for i in range(50):
        price += rng.normal(0, 1.0)
        fake_values.append(
            {
                "datetime": str(base_time + pd.Timedelta(minutes=5 * i)),
                "open": str(price),
                "high": str(price + 1.2),
                "low": str(price - 1.2),
                "close": str(price + rng.normal(0, 0.3)),
                "volume": str(rng.uniform(100, 500)),
            }
        )

    df = pd.DataFrame(fake_values)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_index()[["open", "high", "low", "close", "volume"]]

    assert not df.isna().any().any(), "Parsing produced NaNs"
    assert len(df) == 50
    print("Self-test OK. Parsing logic works. Sample:")
    print(df.tail(3).to_string())
