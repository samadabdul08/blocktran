from flask import Flask, request
import requests
import os
import asyncio
from telegram import Bot
from datetime import datetime

app = Flask(__name__)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

WALLET_LABELS = {
    "0xwallet1": "Main Wallet",
    "0xwallet2": "Trading Wallet",
}

bot = Bot(token=TELEGRAM_TOKEN)

async def send_alert(msg):
    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    try:
        for tx in data.get("txs", []):
            from_addr = tx.get("fromAddress", "").lower()
            to_addr = tx.get("toAddress", "").lower()
            value = float(tx.get("value", 0)) / 1e18
            chain = data.get("chainId", "")
            
            label = WALLET_LABELS.get(to_addr) or WALLET_LABELS.get(from_addr) or "Unknown Wallet"
            
            if to_addr in WALLET_LABELS:
                emoji = "🟢"
                direction = "RECEIVED"
            elif from_addr in WALLET_LABELS:
                emoji = "🔴"
                direction = "SENT"
            else:
                emoji = "🔄"
                direction = "ACTIVITY"

            msg = f"""{emoji} <b>{direction}</b>
👛 <b>Wallet:</b> {label}
💰 <b>Amount:</b> {value:.6f}
⛓️ <b>Chain:</b> {chain}
🕐 <b>Time:</b> {datetime.now().strftime('%d-%b %H:%M')}"""

            asyncio.run(send_alert(msg))
    except Exception as e:
        print(f"Error: {e}")
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
