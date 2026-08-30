"""
Strategy engine built on Dany's rule-based framework:
  - EMA9/21 crossover for directional bias
  - VWAP + deviation bands for mean-reversion / trend context
  - RSI7 for momentum (never used alone for counter-trend entries)
  - ATR for volatility filtering and SL/TP placement
  - Chop Filter: candle alternation + VWAP distance + EMA separation
  - Rejection Confirmation Rule: wick >=2x body, close in outer third,
    next candle breaks the level
  - M5 = entry timeframe, M15 = trend/confluence filter
  - Weighted scoring: fires when at least 4 of 5 gates pass
"""
import indicators as ind

MIN_RR = 2.0  # minimum reward:risk enforced on every signal


def build_frame(df):
    """Attach all indicators to a raw OHLCV dataframe. Returns the same df enriched."""
    df = df.copy()
    df["ema9"] = ind.ema(df["close"], 9)
    df["ema21"] = ind.ema(df["close"], 21)
    df["rsi7"] = ind.rsi(df["close"], 7)
    df["atr14"] = ind.atr(df, 14)
    vwap_df = ind.vwap_with_bands(df, num_std=1.0)
    df["vwap"] = vwap_df["vwap"]
    df["vwap_upper"] = vwap_df["upper"]
    df["vwap_lower"] = vwap_df["lower"]
    df["ema_sep_pct"] = ind.ema_separation_pct(df["ema9"], df["ema21"])
    return df


def trend_direction(df) -> str:
    """M15 trend bias from EMA9/21 relationship. 'up' / 'down' / 'flat'."""
    last = df.iloc[-1]
    if last["ema9"] > last["ema21"]:
        return "up"
    elif last["ema9"] < last["ema21"]:
        return "down"
    return "flat"


def chop_filter_pass(df) -> bool:
    """
    Returns True if the market is NOT choppy (i.e. safe to trade).
    Three checks, all must indicate directionality:
      1. Candles are not alternating color randomly
      2. Price is meaningfully away from VWAP (not glued to it)
      3. EMA9/21 have real separation (not flat/tangled)
    """
    last = df.iloc[-1]
    is_alternating = ind.candle_color_alternation(df, lookback=6)
    vwap_distance_pct = abs(last["close"] - last["vwap"]) / last["vwap"] * 100
    has_vwap_distance = vwap_distance_pct > 0.3  # ~ a few dollars on gold
    has_ema_separation = last["ema_sep_pct"] > 0.02

    return (not is_alternating) and has_vwap_distance and has_ema_separation


def atr_volatility_ok(df, lookback: int = 20) -> bool:
    """Skip dead markets: current ATR must be at/above its recent average."""
    recent_atr = df["atr14"].tail(lookback)
    if len(recent_atr) < lookback:
        return True  # not enough history yet, don't block on this alone
    return df["atr14"].iloc[-1] >= recent_atr.mean()


def rejection_confirmation(df, direction: str) -> bool:
    """
    direction: 'buy' looks for bullish rejection (long lower wick, close upper third,
                next candle breaks the low).
    direction: 'sell' looks for bearish rejection (long upper wick, close lower third,
                next candle breaks the high).
    Requires at least 2 candles after the rejection candle to confirm the break.
    """
    if len(df) < 3:
        return False
    candle = df.iloc[-2]   # the rejection candle
    confirm = df.iloc[-1]  # the candle that should break its level

    body = abs(candle["close"] - candle["open"])
    full_range = candle["high"] - candle["low"]
    if full_range <= 0:
        return False

    if direction == "buy":
        lower_wick = min(candle["open"], candle["close"]) - candle["low"]
        close_position = (candle["close"] - candle["low"]) / full_range
        wick_ok = body > 0 and lower_wick >= 2 * body
        close_ok = close_position >= 0.66
        break_ok = confirm["high"] > candle["high"]
        return wick_ok and close_ok and break_ok

    if direction == "sell":
        upper_wick = candle["high"] - max(candle["open"], candle["close"])
        close_position = (candle["high"] - candle["close"]) / full_range
        wick_ok = body > 0 and upper_wick >= 2 * body
        close_ok = close_position >= 0.66
        break_ok = confirm["low"] < candle["low"]
        return wick_ok and close_ok and break_ok

    return False


def rsi_agrees(df, direction: str) -> bool:
    """RSI is a confirmation input only, never a standalone trigger."""
    last_rsi = df["rsi7"].iloc[-1]
    if direction == "buy":
        return last_rsi < 65  # not already overbought / exhausted
    if direction == "sell":
        return last_rsi > 35  # not already oversold / exhausted
    return False


def evaluate_signal(m5_df, m15_df):
    """
    Main entry point. Runs the full confluence gate on M5 (entry) confirmed
    by M15 (trend). Returns a dict describing the outcome — either a
    high-probability trade signal or a structured 'no trade' reason.

    Weighted scoring: fires a signal when at least 4 of the 5 gates pass,
    instead of requiring all 5.
    """
    m5 = build_frame(m5_df)
    m15 = build_frame(m15_df)

    m15_trend = trend_direction(m15)
    if m15_trend == "flat":
        return {"signal": "NO_TRADE", "reason": "No clear M15 trend"}

    direction = "buy" if m15_trend == "up" else "sell"

    gates = {
        "m15_trend_defined": m15_trend != "flat",
        "chop_filter": chop_filter_pass(m5),
        "atr_volatility": atr_volatility_ok(m5),
        "rejection_confirmation": rejection_confirmation(m5, direction),
        "rsi_agrees": rsi_agrees(m5, direction),
    }

    score = sum(1 for v in gates.values() if v)
    MIN_SCORE = 4
    if score < MIN_SCORE:
        failed = [k for k, v in gates.items() if not v]
        return {"signal": "NO_TRADE", "reason": f"Score {score}/5, failed: {', '.join(failed)}"}

    last = m5.iloc[-1]
    entry = last["close"]
    atr_val = last["atr14"]

    rejection_candle = m5.iloc[-2]
    if direction == "buy":
        sl = rejection_candle["low"] - 0.25 * atr_val
        risk = entry - sl
        tp = entry + MIN_RR * risk
    else:
        sl = rejection_candle["high"] + 0.25 * atr_val
        risk = sl - entry
        tp = entry - MIN_RR * risk

    if risk <= 0:
        return {"signal": "NO_TRADE", "reason": "Invalid risk calculation"}

    rr = abs(tp - entry) / risk
    if rr < MIN_RR - 0.01:
        return {"signal": "NO_TRADE", "reason": "RR below minimum threshold"}

    return {
        "signal": "BUY" if direction == "buy" else "SELL",
        "entry": round(entry, 2),
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "rr": round(rr, 2),
        "rsi7": round(last["rsi7"], 1),
        "atr": round(atr_val, 2),
        "m15_trend": m15_trend,
        "gates": gates,
        "score": f"{score}/5",
    }
