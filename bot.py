import os
import requests
from flask import Flask, request, jsonify
from data_feed import get_latest
from indicators import compute_all_indicators
from strategy import generate_signal, add_obv_slope

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
TWELVE_DATA_KEY = os.environ.get("TWELVE_DATA_KEY", "")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def send_telegram_message(chat_id, text):
    """Send message via Telegram Bot API"""
    try:
        url = f"{TELEGRAM_API}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Send message error: {e}")


def get_signal():
    """Fetch latest candles, compute indicators, generate signal"""
    try:
        df = get_latest("XAU/USD", "5min", TWELVE_DATA_KEY, bars=300)
        df = compute_all_indicators(df)
        df = add_obv_slope(df, window=5)
        
        latest_row = df.iloc[-1]
        signal = generate_signal(latest_row)
        
        if signal.side == "NO_TRADE":
            msg = "NO TRADE\n"
            msg += f"Regime: {signal.regime}\n"
            msg += f"Confidence: {signal.confidence:.2%}"
        else:
            emoji = "BUY" if signal.side == "BUY" else "SELL"
            msg = emoji + "\n"
            msg += f"Entry: {signal.entry:.2f}\n"
            msg += f"SL: {signal.sl:.2f}\n"
            msg += f"TP1: {signal.tp1:.2f}\n"
            msg += f"TP2: {signal.tp2:.2f}\n"
            msg += f"Confidence: {signal.confidence:.2%}\n"
            msg += f"Regime: {signal.regime}\n"
            msg += f"Reasons: {', '.join(signal.reasons)}"
        
        return msg
    
    except Exception as e:
        return f"Error: {str(e)}"


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"ok": True})
        
        message = data.get("message", {})
        text = message.get("text", "")
        chat_id = str(message.get("chat", {}).get("id", ""))
