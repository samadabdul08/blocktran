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
    "0x2b4622c73d4d7bdfe224ca48cb0302d4ad7b4c17" "Main Wallet",,
}

bot = Bot(token=TELEGRAM_TOKEN)

def get_usd_price(chain):
    symbols = {
        "0x1": "ethereum",
        "0x38": "binancecoin",
        "0x89": "matic-network",
        "0xa4b1": "ethereum",
        "0x2105": "ethereum",
        "0xa": "ethereum",
    }
    coin = symbols.get(chain, "ethereum")
    try:
        r = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd")
        return r.json()[coin]["usd"]
    except:
        return 0

def detect_tx_type(tx, logs):
    input_data = tx.get("input", "").lower()
    method_id = input_data[:10] if len(input_data) >= 10 else ""
    
    swap_methods = ["0x38ed1739", "0x7ff36ab5", "0x18cbafe5", "0x791ac947", "0x5c11d795"]
    stake_methods = ["0xa694fc3a", "0x3a4b66f1", "0x1249c58b"]
    unstake_methods = ["0x2e1a7d4d", "0x38d07436", "0xd1058e59"]
    
    if method_id in swap_methods:
        return "SWAP", "🔁"
    elif method_id in stake_methods:
        return "STAKED", "🔒"
    elif method_id in unstake_methods:
        return "UNSTAKED", "🔓"
    
    for log in logs:
        topics = log.get("topics", [])
        if topics:
            topic = topics[0].lower()
            if "swap" in log.get("address", "").lower():
                return "SWAP", "🔁"
    
    return None, None

async def send_alert(msg):
    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    try:
        chain = data.get("chainId", "")
        price = get_usd_price(chain)
        logs = data.get("logs", [])
        
        chain_names = {
            "0x1": "Ethereum",
            "0x38": "BNB Chain",
            "0x89": "Polygon",
            "0xa4b1": "Arbitrum",
            "0x2105": "Base",
            "0xa": "Optimism",
        }
        chain_name = chain_names.get(chain, chain)

        for tx in data.get("txs", []):
            from_addr = tx.get("fromAddress", "").lower()
            to_addr = tx.get("toAddress", "").lower()
            value = float(tx.get("value", 0)) / 1e18
            usd_value = value * price
            
            # Gas/Fees
            gas_used = int(tx.get("gasPrice", 0)) * int(tx.get("receiptGasUsed", 0))
            fee_eth = gas_used / 1e18
            fee_usd = fee_eth * price

            label = WALLET_LABELS.get(to_addr) or WALLET_LABELS.get(from_addr) or "label = to_addr if to_addr else from_addr"

            # Detect type
            tx_type, type_emoji = detect_tx_type(tx, logs)
            
            if tx_type:
                emoji = type_emoji
                direction = tx_type
            elif to_addr in WALLET_LABELS:
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
💰 <b>Amount:</b> {value:.6f} (~${usd_value:.2f} USD)
⛽ <b>Fee:</b> {fee_eth:.6f} (~${fee_usd:.4f} USD)
⛓️ <b>Chain:</b> {chain_name}
🕐 <b>Time:</b> {datetime.now().strftime('%d-%b %H:%M')}"""

            asyncio.run(send_alert(msg))

        # ERC20 Transfers (tokens)
        for transfer in data.get("erc20Transfers", []):
            from_addr = transfer.get("from", "").lower()
            to_addr = transfer.get("to", "").lower()
            token_symbol = transfer.get("tokenSymbol", "TOKEN")
            decimals = int(transfer.get("tokenDecimals", 18))
            amount = int(transfer.get("value", 0)) / (10 ** decimals)

            label = WALLET_LABELS.get(to_addr) or WALLET_LABELS.get(from_addr) or "label = to_addr if to_addr else from_addr"

            if to_addr in WALLET_LABELS:
                emoji = "🟢"
                direction = "RECEIVED"
            elif from_addr in WALLET_LABELS:
                emoji = "🔴"
                direction = "SENT"
            else:
                emoji = "🔄"
                direction = "ACTIVITY"

            msg = f"""{emoji} <b>{direction} {token_symbol}</b>
👛 <b>Wallet:</b> {label}
💰 <b>Amount:</b> {amount:.4f} {token_symbol}
⛓️ <b>Chain:</b> {chain_name}
🕐 <b>Time:</b> {datetime.now().strftime('%d-%b %H:%M')}"""

            asyncio.run(send_alert(msg))

    except Exception as e:
        print(f"Error: {e}")
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
