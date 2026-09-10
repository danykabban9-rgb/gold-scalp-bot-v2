import requests
import os

TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"
WEBHOOK_URL = "https://gold-scalp-bot-v2.onrender.com/telegram"

url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
data = {"url": WEBHOOK_URL}

response = requests.post(url, data=data)
print(response.json())
