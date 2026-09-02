"""
Danytraderlebanon (@dany13goldbot) — XAUUSD scalping bot.

Built on Dany's own framework (EMA9/21, VWAP+bands, RSI7, ATR, Chop Filter,
Rejection Confirmation Rule, M5 entry / M15 trend confluence). Only sends a
Telegram alert when every confluence gate passes — no partial-credit scoring,
no noise.

Env vars required (set these on Render):
  TELEGRAM_TOKEN   - bot token from BotFather for @dany13goldbot
  TWELVE_DATA_KEY  - Twelve Data API key
  CHAT_ID          - your personal Telegram chat id, for auto-alerts
                       (get it by messaging the bot once, then hitting
                       https://api.telegram.org/bot<TOKEN>/getUpdates)
"""
import os
import threading
import time
import traceback

import requests
from flask import Flask, request

import strategy
from data_feed import fetch_candles

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

POLL_SECONDS = 5 * 60  # check once per M5 candle close

# ---------------------------------------------------------------------------
# Telegram helpers
# ---------------------------------------------------------------------------
def send_message(chat_id, text):
    try:
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except requests.exceptions.RequestException:
        pass  # don't crash the bot over a failed notification


def format_signal_message(result: dict) -> str:
    if result["signal"] == "NO_TRADE":
        return (
            f"⚪ <b>NO TRADE</b>\n\n"
            f"XAUUSD — M5 entry / M15 trend\n"
            f"Reason: {result['reason']}"
        )

    emoji = "🟢" if result["signal"] == "BUY" else "🔴"
    return (
        f"{emoji} <b>{result['signal']}</b>\n\n"
        f"XAUUSD — M5 entry / M15 trend ({result['m15_trend']})\n\n"
        f"Entry: {result['entry']}\n"
        f"SL: {result['sl']}\n"
        f"TP: {result['tp']}\n"
        f"RR: 1:{result['rr']}\n"
        f"RSI7: {result['rsi7']}\n"
        f"ATR: {result['atr']}\n\n"
        f"All confluence gates passed. Signal only — no automatic trading."
    )


# ---------------------------------------------------------------------------
# Core signal generation
# ---------------------------------------------------------------------------
def get_current_signal():
    m5_df = fetch_candles("M5", outputsize=150)
    m15_df = fetch_candles("M15", outputsize=150)
    result = strategy.evaluate_signal(m5_df, m15_df)
    return result


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------
@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    try:
        update = request.get_json(force=True)
        message = update.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        text = (message.get("text") or "").strip()

        if not chat_id:
            return "ok"

        if text == "/start":
            send_message(chat_id, "Danytraderlebanon gold scalping bot online. Send /signal")
        elif text == "/signal":
            try:
                result = get_current_signal()
                send_message(chat_id, format_signal_message(result))
            except Exception as e:
                send_message(chat_id, f"⚠️ Error fetching signal: {e}")
        else:
            send_message(chat_id, "Commands: /signal")

    except Exception:
        traceback.print_exc()  # surfaces in Render logs instead of failing silently

    return "ok"


@app.route("/", methods=["GET"])
def health():
    return "Danytraderlebanon bot is running."


# ---------------------------------------------------------------------------
# Background polling loop — sends an alert automatically ONLY on a
# high-probability BUY/SELL signal. Stays silent on NO_TRADE.
# ---------------------------------------------------------------------------
def poll_loop():
    last_signal_key = None
    while True:
        try:
            if CHAT_ID:
                result = get_current_signal()
                print("[POLL]", result.get("signal"), "|", result.get("reason", result.get("gates")), flush=True)
