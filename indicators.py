"""
Indicator calculations for the gold scalping bot.
All functions take a pandas DataFrame with columns: open, high, low, close, volume
and return either a pandas Series or a scalar (for the latest value).
"""
import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 7) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50)  # neutral when undefined (e.g. no losses yet)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def vwap_with_bands(df: pd.DataFrame, num_std: float = 1.0) -> pd.DataFrame:
    """
    Session VWAP with standard-deviation bands.
    Assumes df is already sliced to the current session (e.g. since 00:00 UTC
    or since market open) — resets are the caller's responsibility.
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cum_vol = df["volume"].cumsum().replace(0, np.nan)
    cum_pv = (typical_price * df["volume"]).cumsum()
    vwap = cum_pv / cum_vol

    # rolling variance of price around vwap, weighted by volume
    sq_diff = (typical_price - vwap) ** 2
    cum_pv_sqdiff = (sq_diff * df["volume"]).cumsum()
    variance = cum_pv_sqdiff / cum_vol
    std = np.sqrt(variance.clip(lower=0))

    out = pd.DataFrame(index=df.index)
    out["vwap"] = vwap
    out["upper"] = vwap + num_std * std
    out["lower"] = vwap - num_std * std
    return out.bfill().ffill()


def ema_separation_pct(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """EMA9/21 separation as % of price — used by the chop filter."""
    return ((fast - slow).abs() / slow) * 100


def candle_color_alternation(df: pd.DataFrame, lookback: int = 6) -> bool:
    """
    True if the last `lookback` candles alternate direction (chop signature).
    Returns True = choppy (bad), False = directional (good).
    """
    recent = df.tail(lookback)
    colors = np.where(recent["close"] >= recent["open"], 1, -1)
    if len(colors) < 3:
        return False
    flips = np.sum(colors[1:] != colors[:-1])
    # if most consecutive candles flip color, that's chop
    return flips >= (len(colors) - 1) * 0.6
