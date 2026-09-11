import os
import requests
from flask import Flask, request, jsonify
from strategy import get_signal

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

def send_telegram_message(chat_id, text):
    """Send message via Telegram Bot API"""
    try:
        url = f"{TELEGRAM_API}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Send message error: {e}")

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
            send_telegram_message(chat_id, "Gold scalping bot v2 running ✓")
        
        elif text == "/signal":
            signal = get_signal()
            send_telegram_message(chat_id, signal)
        
        return jsonify({"ok": True})
    
    except Exception as e:
        print(f"Webhook error: {e}")
        send_telegram_message(chat_id, f"Error: {str(e)}")
        return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
