"""
bot.py

Flask app that:
- Responds to Telegram commands /start and /signal (manual check)
- Exposes /scan for an external free cron-pinger (cron-job.org) to hit every
few minutes, so the bot actually scans in the background on Render's free
tier (which has no persistent worker process)
"""

import os
import json
import time
import requests
from flask import Flask, request, jsonify

from data_feed import get_latest, get_history
from indicators import compute_all_indicators
from strategy import generate_signal, add_obv_slope, DEFAULT_PARAMS
from backtest import run_backtest

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TWELVE_DATA_KEY = os.environ.get("TWELVE_DATA_KEY", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
SYMBOL = "XAU/USD"

STATE_PATH = os.path.join(os.path.dirname(__file__), "last_alert.json")
PARAMS_PATH = os.path.join(os.path.dirname(__file__), "best_params.json")


def setup_webhook():
    """Auto-setup webhook on startup."""
    WEBHOOK_URL = "https://gold-scalp-bot-v2.onrender.com/telegram"
    
    if not TELEGRAM_TOKEN:
        print("⚠️  TELEGRAM_TOKEN not set, skipping webhook setup")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
    try:
        response = requests.post(url, json={"url": WEBHOOK_URL}, timeout=10)
        result = response.json()
        if result.get("ok"):
            print(f"✅ Webhook set to {WEBHOOK_URL}")
        else:
            print(f"❌ Webhook setup failed: {result}")
    except Exception as e:
        print(f"❌ Webhook setup error: {e}")


def load_params() -> dict:
    if os.path.exists(PARAMS_PATH):
        try:
            with open(PARAMS_PATH) as f:
                return json.load(f)["params"]
        except Exception:
            pass
    return DEFAULT_PARAMS


def load_last_alert_time() -> str:
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH) as f:
                return json.load(f).get("last_alert_time", "")
        except Exception:
            pass
    return ""


def save_last_alert_time(ts: str) -> None:
    with open(STATE_PATH, "w") as f:
        json.dump({"last_alert_time": ts}, f)


def send_telegram(text: str, chat_id: str = None) -> None:
    if not TELEGRAM_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": chat_id or CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        print("Telegram send failed:", e)


def check_m5_confluence(side: str) -> bool:
    """Cheap confirmation: does the M5 EMA9/21 direction agree with the M15 signal?"""
    try:
        df5 = get_latest(SYMBOL, "5min", TWELVE_DATA_KEY, bars=60)
        df5 = compute_all_indicators(df5)
        last = df5.iloc[-1]
        if side == "BUY":
            return last["ema9"] > last["ema21"]
        elif side == "SELL":
            return last["ema9"] < last["ema21"]
    except Exception as e:
        print("M5 confluence check failed, allowing signal through:", e)
        return True  # don't block a alert just because a secondary check failed
    return True


def build_signal():
    """Pulls fresh M15 data, computes indicators, and returns (signal, candle_time)."""
    df15 = get_latest(SYMBOL, "15min", TWELVE_DATA_KEY, bars=300)
    df15 = compute_all_indicators(df15)
    df15 = add_obv_slope(df15)
    params = load_params()
    last_row = df15.iloc[-1]
    sig = generate_signal(last_row, params)
    candle_time = str(df15.index[-1])
    return sig, candle_time


def format_signal_message(sig, candle_time: str) -> str:
    return (
        f"<b>{sig.side} XAUUSD</b>\n"
        f"Regime: {sig.regime} | Confidence: {sig.confidence:.0%}\n"
        f"Entry: {sig.entry:.2f}\n"
        f"SL: {sig.sl:.2f}\n"
        f"TP1: {sig.tp1:.2f}\n"
        f"TP2: {sig.tp2:.2f}\n"
        f"Confirming: {', '.join(sig.reasons)}\n"
        f"Candle: {candle_time}"
    )


def manual_signal():
    """Manual check—always replies, even on NO TRADE, since it was asked for directly."""
    try:
        sig, candle_time = build_signal()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if sig.side == "NO_TRADE":
        msg = f"NO TRADE right now (regime: {sig.regime}, confidence: {sig.confidence:.0%})"
    else:
        msg = format_signal_message(sig, candle_time)

    return jsonify({"message": msg})


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/signal", methods=["GET"])
def manual_signal_endpoint():
    """Manual check—always replies, even on NO TRADE, since it was asked for directly."""
    try:
        sig, candle_time = build_signal()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if sig.side == "NO_TRADE":
        msg = f"NO TRADE right now (regime: {sig.regime}, confidence: {sig.confidence:.0%})"
    else:
        msg = format_signal_message(sig, candle_time)

    return jsonify({"message": msg})


@app.route("/scan", methods=["GET", "POST"])
def scan():
    """
    Hit by the free external cron pinger every few minutes. Only sends a
    Telegram push if: a real BUY/SELL fires, M5 confluence agrees, and we
    haven't already alerted on this exact candle.
    """
    try:
        sig, candle_time = build_signal()
    except Exception as e:
        print("Scan error:", e)
        return jsonify({"error": str(e)}), 500

    if sig.side == "NO_TRADE":
        return jsonify({"status": "no_trade"})

    if candle_time == load_last_alert_time():
        return jsonify({"status": "already_alerted_this_candle"})

    if not check_m5_confluence(sig.side):
        return jsonify({"status": "m5_confluence_failed"})

    send_telegram(format_signal_message(sig, candle_time))
    save_last_alert_time(candle_time)
    return jsonify({"status": "alert_sent", "side": sig.side})


@app.route("/run_backtest", methods=["GET"])
def run_backtest_endpoint():
    """
    One-off admin endpoint (free-tier substitute for Render Shell): pulls all
    available M15 history from Twelve Data and runs the backtest grid search,
    returning the best params + stats as JSON. Visit this URL once in a
    browser, then copy the 'params' block into best_params.json in the repo
    so it survives free-tier restarts (the live filesystem is wiped on spin-down).
    """
    try:
        df = get_history(SYMBOL, "15min", TWELVE_DATA_KEY, refresh=True)
        if len(df) < 250:
            return jsonify({"error": f"Only {len(df)} candles available, need at least 250"}), 400

        result = run_backtest(df)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    try:
        update = request.get_json(force=True)
        message = update.get("message", {})
        text = message.get("text", "")
        chat_id = str(message.get("chat", {}).get("id", ""))

        if text.startswith("/start"):
            send_telegram(
                "Gold scalp bot v2 (beast mode) is online.\n"
                "Use /signal anytime for a manual check.\n"
                "Auto-alerts run in the background via /scan.",
                chat_id=chat_id,
            )
        elif text.startswith("/signal"):
            sig, candle_time = build_signal()
            if sig.side == "NO_TRADE":
                msg = f"NO TRADE right now (regime: {sig.regime}, confidence: {sig.confidence:.0%})"
            else:
                msg = format_signal_message(sig, candle_time)
            send_telegram(msg, chat_id=chat_id)
        
        except Exception as e:
            print("Telegram webhook error:", e)
            try:
                send_telegram(f"Error handling your command: {e}", chat_id=chat_id)
            except Exception:
                pass

        return jsonify({"ok": True})

    except Exception as e:
        print("Telegram webhook error:", e)
        return jsonify({"ok": False}), 500


if __name__ == "__main__":
    setup_webhook()  # Auto-setup webhook on startup
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
