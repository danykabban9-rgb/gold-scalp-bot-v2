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


def setup_webhook():
    try:
        webhook_url = "https://gold-scalp-bot-v2.onrender.com/telegram"
        url = f"{TELEGRAM_API}/setWebhook"
        requests.post(url, json={"url": webhook_url}, timeout=10)
        print(f"Webhook set to {webhook_url}")
    except Exception as e:
        print(f"Webhook error: {e}")


def send_telegram_message(chat_id, text):
    try:
        url = f"{TELEGRAM_API}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Send error: {e}")


def get_signal():
    try:
        df = get_latest("XAU/USD", "5min", TWELVE_DATA_KEY, bars=300)
        df = compute_all_indicators(df)
        df = add_obv_slope(df, window=5)
        latest_row = df.iloc[-1]
        signal = generate_signal(latest_row)
        
        if signal.side == "NO_TRADE":
            return f"NO TRADE\nRegime: {signal.regime}\nConfidence: {signal.confidence:.1%}"
        else:
            side_str = "BUY" if signal.side == "BUY" else "SELL"
            msg = f"{side_str}\nEntry: {signal.entry:.2f}\nSL: {signal.sl:.2f}\nTP1: {signal.tp1:.2f}\nTP2: {signal.tp2:.2f}\nConfidence: {signal.confidence:.1%}\nRegime: {signal.regime}"
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
        
        if text == "/start":
            send_telegram_message(chat_id, "Bot running")
        elif text == "/signal":
            signal = get_signal()
            send_telegram_message(chat_id, signal)
        
        return jsonify({"ok": True})
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"ok": True})


setup_webhook()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
