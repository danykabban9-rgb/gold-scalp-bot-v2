"""
Twelve Data price feed for XAU/USD.
Includes retry + timeout handling since the old bot's main failure mode
was an unhandled ReadTimeout from api.twelvedata.com.
"""
import os
import time
import requests
import pandas as pd

TWELVE_DATA_KEY = os.environ.get("TWELVE_DATA_KEY", "")
BASE_URL = "https://api.twelvedata.com/time_series"

INTERVAL_MAP = {"M5": "5min", "M15": "15min"}


def fetch_candles(timeframe: str, outputsize: int = 150, retries: int = 3, timeout: int = 15) -> pd.DataFrame:
    """
    Fetch OHLCV candles for XAU/USD at the given timeframe ('M5' or 'M15').
    Raises RuntimeError with a clear message on repeated failure, instead of
    letting a raw ReadTimeout/ConnectionError bubble up uncaught.
    """
    if timeframe not in INTERVAL_MAP:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    params = {
        "symbol": "XAU/USD",
        "interval": INTERVAL_MAP[timeframe],
        "outputsize": outputsize,
        "apikey": TWELVE_DATA_KEY,
        "format": "JSON",
    }

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(BASE_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            payload = resp.json()

            if "values" not in payload:
                # Twelve Data returns {"status":"error", "message": ...} on failure
                raise RuntimeError(payload.get("message", "Unknown Twelve Data API error"))

            df = pd.DataFrame(payload["values"])
            df = df.rename(columns={
                "datetime": "datetime", "open": "open", "high": "high",
                "low": "low", "close": "close", "volume": "volume",
            })
            for col in ["open", "high", "low", "close"]:
                df[col] = df[col].astype(float)
            df["volume"] = df.get("volume", pd.Series([0] * len(df))).astype(float)
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.sort_values("datetime").reset_index(drop=True)
            return df

        except (requests.exceptions.RequestException, RuntimeError, ValueError) as e:
            last_error = e
            if attempt < retries:
                time.sleep(2 * attempt)  # simple backoff: 2s, 4s
            continue

    raise RuntimeError(f"Failed to fetch {timeframe} data after {retries} attempts: {last_error}")
