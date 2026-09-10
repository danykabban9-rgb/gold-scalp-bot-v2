import requests
import os

TOKEN = 8516893389:AAFSiy73OSI-zUUOJeve3f37MkuRGP0_GVo
WEBHOOK_URL = "https://gold-scalp-bot-v2.onrender.com/telegram"

url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
data = {"url": WEBHOOK_URL}

response = requests.post(url, data=data)
print(response.json())
