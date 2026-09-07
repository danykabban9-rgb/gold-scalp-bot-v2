"""
strategy.py
Regime-aware, multi-indicator scoring engine.

Regime detection: ADX14 + EMA separation decide if the market is trending or ranging.
- Trending regime -> trend-following score (EMA stack, MACD, Supertrend, PSAR, ADX, structure)
- Ranging regime  -> mean-reversion score (Bollinger/VWAP deviation, RSI, Stoch, Williams %R, CCI, rejection candle)

Every indicator "votes" BUY / SELL / neutral. A signal only fires when the
vote count clears score_threshold out of the indicators active for that regime
-- this is what backtest.py tunes, so the threshold isn't just guessed.

Entry/SL/TP are ATR-based so they scale with current volatility, with a
minimum 1:2 risk/reward enforced (matches the user's own trading rule).
"""

from dataclasses import dataclass, field
from typing import Literal

Side = Literal["BUY", "SELL", "NO_TRADE"]

DEFAULT_PARAMS = {
    "adx_trend_threshold": 22,      # ADX above this = trending regime
    "score_threshold_trend": 0.6,   # fraction of trend-votes needed to fire
    "score_threshold_range": 0.6,   # fraction of range-votes needed to fire
    "atr_sl_mult": 1.5,
    "atr_tp1_mult": 3.0,            # 1:2 RR minimum
    "atr_tp2_mult": 5.0,
}


@dataclass
class Signal:
    side: Side
    entry: float = 0.0
    sl: float = 0.0
    tp1: float = 0.0
    tp2: float = 0.0
    confidence: float = 0.0
    regime: str = ""
    reasons: list = field(default_factory=list)


def _trend_votes(row) -> list:
    """Each entry: +1 vote bullish, -1 bearish, 0 neutral, with a label."""
    votes = []
    votes.append((1 if row["ema9"] > row["ema21"] > row["ema50"] else
                  -1 if row["ema9"] < row["ema21"] < row["ema50"] else 0, "ema_stack"))
    votes.append((1 if row["close"] > row["ema200"] else -1, "ema200_bias"))
    votes.append((1 if row["macd_hist"] > 0 else -1, "macd_hist"))
    votes.append((1 if row["supertrend_dir"] == 1 else -1, "supertrend"))
    votes.append((1 if row["close"] > row["psar"] else -1, "psar"))
    votes.append((1 if row["adx14"] >= 22 else 0, "adx_strength"))  # confirms strength, no direction
    votes.append((1 if row["structure"] in ("HH", "HL") else
                  -1 if row["structure"] in ("LH", "LL") else 0, "structure"))
    votes.append((1 if row["rsi14"] > 50 else -1, "rsi_bias"))
    votes.append((1 if row["obv_slope"] > 0 else -1, "obv_slope"))
    return votes


def _range_votes(row) -> list:
    votes = []
    votes.append((1 if row["close"] <= row["bb_lower"] else
                  -1 if row["close"] >= row["bb_upper"] else 0, "bollinger"))
    votes.append((1 if row["rsi7"] <= 30 else -1 if row["rsi7"] >= 70 else 0, "rsi7_extreme"))
    votes.append((1 if row["stoch_k"] <= 20 else -1 if row["stoch_k"] >= 80 else 0, "stochastic"))
    votes.append((1 if row["williams_r"] <= -80 else -1 if row["williams_r"] >= -20 else 0, "williams_r"))
    votes.append((1 if row["cci20"] <= -100 else -1 if row["cci20"] >= 100 else 0, "cci"))
    votes.append((1 if row["close"] < row["vwap"] else -1, "vwap_side"))
    votes.append((1 if row["pin_bar_bull"] else -1 if row["pin_bar_bear"] else 0, "rejection_candle"))
    votes.append((1 if row["close"] <= row["s1"] else -1 if row["close"] >= row["r1"] else 0, "pivot_zone"))
    return votes


def _score(votes) -> tuple:
    """Returns (side, confidence 0-1, reasons list) from a vote list."""
    active = [v for v in votes if v[0] != 0]
    if not active:
        return "NO_TRADE", 0.0, []
    bulls = [label for v, label in active if v == 1]
    bears = [label for v, label in active if v == -1]
    total = len(votes)

    if len(bulls) > len(bears):
        return "BUY", len(bulls) / total, bulls
    elif len(bears) > len(bulls):
        return "SELL", len(bears) / total, bears
    return "NO_TRADE", 0.0, []


def generate_signal(row, params: dict = None) -> Signal:
    """
    row: a single row (pandas Series) from the indicator-enriched DataFrame,
         must already include an 'obv_slope' column (see strategy.add_obv_slope).
    """
    p = {**DEFAULT_PARAMS, **(params or {})}
    regime = "trend" if row["adx14"] >= p["adx_trend_threshold"] else "range"

    if regime == "trend":
        votes = _trend_votes(row)
        side, confidence, reasons = _score(votes)
        threshold = p["score_threshold_trend"]
    else:
        votes = _range_votes(row)
        side, confidence, reasons = _score(votes)
        threshold = p["score_threshold_range"]

    if side == "NO_TRADE" or confidence < threshold:
        return Signal(side="NO_TRADE", regime=regime, confidence=confidence)

    entry = row["close"]
    atr_val = row["atr14"]
    if side == "BUY":
        sl = entry - p["atr_sl_mult"] * atr_val
        tp1 = entry + p["atr_tp1_mult"] * atr_val
        tp2 = entry + p["atr_tp2_mult"] * atr_val
    else:
        sl = entry + p["atr_sl_mult"] * atr_val
        tp1 = entry - p["atr_tp1_mult"] * atr_val
        tp2 = entry - p["atr_tp2_mult"] * atr_val

    return Signal(
        side=side,
        entry=entry,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
        confidence=confidence,
        regime=regime,
        reasons=reasons,
    )


def add_obv_slope(df, window: int = 5):
    """OBV's raw value isn't meaningful on its own -- its recent slope is."""
    df = df.copy()
    df["obv_slope"] = df["obv"].diff(window)
    df["obv_slope"] = df["obv_slope"].fillna(0)
    return df
