"""
indicators.py
Pure pandas/numpy implementations of ~18-20 technical indicators.
No external TA library required -> fewer dependency/version failures on Render.

Input: a pandas DataFrame with columns: ['open', 'high', 'low', 'close', 'volume']
       indexed by datetime, sorted oldest -> newest.
Output: the same DataFrame with indicator columns added.
"""

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def bollinger_bands(series: pd.Series, period: int = 20, num_std: float = 2.0):
    mid = sma(series, period)
    std = series.rolling(period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


def vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    cum_vol = df["volume"].cumsum().replace(0, np.nan)
    return (typical * df["volume"]).cumsum() / cum_vol


def stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3):
    low_min = df["low"].rolling(k_period).min()
    high_max = df["high"].rolling(k_period).max()
    denom = (high_max - low_min).replace(0, np.nan)
    k = 100 * (df["close"] - low_min) / denom
    d = k.rolling(d_period).mean()
    return k.fillna(50), d.fillna(50)


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = atr(df, period) + 1e-9
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / tr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean().fillna(0)


def cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    ma = typical.rolling(period).mean()
    mean_dev = typical.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (typical - ma) / (0.015 * mean_dev.replace(0, np.nan))


def williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_max = df["high"].rolling(period).max()
    low_min = df["low"].rolling(period).min()
    denom = (high_max - low_min).replace(0, np.nan)
    return -100 * (high_max - df["close"]) / denom


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff().fillna(0))
    return (direction * df["volume"]).cumsum()


def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0):
    hl2 = (df["high"] + df["low"]) / 2
    _atr = atr(df, period)
    upper_band = hl2 + multiplier * _atr
    lower_band = hl2 - multiplier * _atr

    trend = pd.Series(index=df.index, dtype="float64")
    direction = pd.Series(index=df.index, dtype="int64")
    trend.iloc[0] = upper_band.iloc[0]
    direction.iloc[0] = 1

    for i in range(1, len(df)):
        curr_close = df["close"].iloc[i]
        if curr_close > upper_band.iloc[i - 1]:
            direction.iloc[i] = 1
        elif curr_close < lower_band.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]
            if direction.iloc[i] == 1 and lower_band.iloc[i] < lower_band.iloc[i - 1]:
                lower_band.iloc[i] = lower_band.iloc[i - 1]
            if direction.iloc[i] == -1 and upper_band.iloc[i] > upper_band.iloc[i - 1]:
                upper_band.iloc[i] = upper_band.iloc[i - 1]
        trend.iloc[i] = lower_band.iloc[i] if direction.iloc[i] == 1 else upper_band.iloc[i]

    return trend, direction


def parabolic_sar(df: pd.DataFrame, af_start: float = 0.02, af_step: float = 0.02, af_max: float = 0.2):
    high, low = df["high"], df["low"]
    sar = pd.Series(index=df.index, dtype="float64")
    trend_up = True
    af = af_start
    ep = low.iloc[0]
    sar.iloc[0] = high.iloc[0]

    for i in range(1, len(df)):
        prev_sar = sar.iloc[i - 1]
        if trend_up:
            new_sar = prev_sar + af * (ep - prev_sar)
            new_sar = min(new_sar, low.iloc[i - 1], low.iloc[i - 2] if i > 1 else low.iloc[i - 1])
            if low.iloc[i] < new_sar:
                trend_up = False
                new_sar = ep
                ep = low.iloc[i]
                af = af_start
            else:
                if high.iloc[i] > ep:
                    ep = high.iloc[i]
                    af = min(af + af_step, af_max)
        else:
            new_sar = prev_sar + af * (ep - prev_sar)
            new_sar = max(new_sar, high.iloc[i - 1], high.iloc[i - 2] if i > 1 else high.iloc[i - 1])
            if high.iloc[i] > new_sar:
                trend_up = True
                new_sar = ep
                ep = high.iloc[i]
                af = af_start
            else:
                if low.iloc[i] < ep:
                    ep = low.iloc[i]
                    af = min(af + af_step, af_max)
        sar.iloc[i] = new_sar

    return sar


def pivot_points(df: pd.DataFrame):
    """Classic daily-style pivots computed on the prior bar's H/L/C, applied per-row."""
    prev_high = df["high"].shift(1)
    prev_low = df["low"].shift(1)
    prev_close = df["close"].shift(1)
    pivot = (prev_high + prev_low + prev_close) / 3
    r1 = 2 * pivot - prev_low
    s1 = 2 * pivot - prev_high
    r2 = pivot + (prev_high - prev_low)
    s2 = pivot - (prev_high - prev_low)
    return pivot, r1, s1, r2, s2


def market_structure(df: pd.DataFrame, lookback: int = 3) -> pd.Series:
    """
    Flags swing points as HH / HL / LH / LL based on local highs/lows
    over a rolling window. Returns a string label per bar ('' if not a swing point).
    """
    high, low = df["high"], df["low"]
    is_swing_high = (high == high.rolling(lookback * 2 + 1, center=True).max())
    is_swing_low = (low == low.rolling(lookback * 2 + 1, center=True).min())

    labels = pd.Series("", index=df.index)
    last_high = None
    last_low = None

    for i in range(len(df)):
        if is_swing_high.iloc[i]:
            h = high.iloc[i]
            if last_high is not None:
                labels.iloc[i] = "HH" if h > last_high else "LH"
            last_high = h
        elif is_swing_low.iloc[i]:
            l = low.iloc[i]
            if last_low is not None:
                labels.iloc[i] = "HL" if l > last_low else "LL"
            last_low = l

    return labels


def candlestick_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Simple, robust candlestick pattern flags (booleans)."""
    body = (df["close"] - df["open"]).abs()
    range_ = (df["high"] - df["low"]).replace(0, np.nan)
    upper_wick = df["high"] - df[["close", "open"]].max(axis=1)
    lower_wick = df[["close", "open"]].min(axis=1) - df["low"]

    flags = pd.DataFrame(index=df.index)
    flags["bullish_engulfing"] = (
        (df["close"] > df["open"])
        & (df["close"].shift(1) < df["open"].shift(1))
        & (df["close"] >= df["open"].shift(1))
        & (df["open"] <= df["close"].shift(1))
    )
    flags["bearish_engulfing"] = (
        (df["close"] < df["open"])
        & (df["close"].shift(1) > df["open"].shift(1))
        & (df["close"] <= df["open"].shift(1))
        & (df["open"] >= df["close"].shift(1))
    )
    flags["pin_bar_bull"] = (lower_wick >= 2 * body) & (df["close"] > df["open"])
    flags["pin_bar_bear"] = (upper_wick >= 2 * body) & (df["close"] < df["open"])
    flags["doji"] = body <= 0.1 * range_
    return flags.fillna(False)


def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Adds every indicator column to a copy of df and returns it."""
    out = df.copy()

    out["ema9"] = ema(out["close"], 9)
    out["ema21"] = ema(out["close"], 21)
    out["ema50"] = ema(out["close"], 50)
    out["ema200"] = ema(out["close"], 200)
    out["rsi7"] = rsi(out["close"], 7)
    out["rsi14"] = rsi(out["close"], 14)
    out["macd"], out["macd_signal"], out["macd_hist"] = macd(out["close"])
    out["atr14"] = atr(out, 14)
    out["bb_upper"], out["bb_mid"], out["bb_lower"] = bollinger_bands(out["close"])
    out["vwap"] = vwap(out)
    out["stoch_k"], out["stoch_d"] = stochastic(out)
    out["adx14"] = adx(out, 14)
    out["cci20"] = cci(out, 20)
    out["williams_r"] = williams_r(out)
    out["obv"] = obv(out)
    out["supertrend"], out["supertrend_dir"] = supertrend(out)
    out["psar"] = parabolic_sar(out)
    out["pivot"], out["r1"], out["s1"], out["r2"], out["s2"] = pivot_points(out)
    out["structure"] = market_structure(out)

    candles = candlestick_flags(out)
    out = pd.concat([out, candles], axis=1)

    return out


if __name__ == "__main__":
    # Quick self-test with synthetic data so we catch errors before this ever
    # touches Render or real money.
    rng = np.random.default_rng(42)
    n = 300
    price = 2000 + np.cumsum(rng.normal(0, 1.5, n))
    high = price + rng.uniform(0.5, 2.5, n)
    low = price - rng.uniform(0.5, 2.5, n)
    open_ = price + rng.normal(0, 0.5, n)
    close = price + rng.normal(0, 0.5, n)
    volume = rng.uniform(100, 1000, n)

    test_df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=pd.date_range("2026-01-01", periods=n, freq="5min"),
    )

    result = compute_all_indicators(test_df)
    print("Self-test OK. Columns:", len(result.columns))
    print(result.tail(3).to_string())
    assert result.isna().all().sum() == 0, "A column is entirely NaN — bug in an indicator"
    print("No fully-empty columns. Indicators module is solid.")
