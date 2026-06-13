import asyncio
import os
import json
import hmac
import hashlib
import aiohttp
from fastapi import FastAPI, Request, Response
from dotenv import load_dotenv
from bot import bot, dp, send_alert
from database import get_user_by_wallet, increment_tx_count

load_dotenv()

MORALIS_API_KEY = os.getenv("MORALIS_API_KEY")
MORALIS_STREAM_SECRET = os.getenv("MORALIS_STREAM_SECRET", "")

app = FastAPI()

CHAIN_INFO = {
    "0x1": ("ethereum", "ETH"),
    "0x38": ("bsc", "BNB"),
    "0x89": ("polygon", "MATIC"),
    "0xa4b1": ("arbitrum", "ETH"),
    "0xa": ("optimism", "ETH"),
    "0xa86a": ("avalanche", "AVAX"),
    "0x2105": ("base", "ETH"),
    "0xfa": ("fantom", "FTM"),
}

COINGECKO_IDS = {
    "eth": "ethereum", "bnb": "binancecoin", "matic": "matic-network",
    "avax": "avalanche-2", "ftm": "fantom",
    "usdt": "tether", "usdc": "usd-coin",
}


async def get_token_price(symbol: str) -> float:
    cg_id = COINGECKO_IDS.get(symbol.lower())
    if not cg_id:
        return 0
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": cg_id, "vs_currencies": "usd"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                data = await r.json()
                return data.get(cg_id, {}).get("usd", 0)
    except Exception:
        return 0


def verify_signature(body: bytes, provided_sig: str) -> bool:
    if not MORALIS_STREAM_SECRET:
        return True
    expected = hmac.new(
        MORALIS_STREAM_SECRET.encode(),
        body,
        hashlib.sha3_256,
    ).hexdigest()
    return hmac.compare_digest(expected, provided_sig or "")


@app.get("/")
async def health():
    return {"status": "BlockTran webhook alive"}


@app.post("/webhook")
async def webhook(request: Request):
    body = await request.body()
    sig = request.headers.get("x-signature", "")

    if not verify_signature(body, sig):
        return Response(status_code=401)

    data = json.loads(body)

    if not data.get("confirmed", True):
        return {"ok": True}

    chain_hex = data.get("chainId", "")
    chain_name, native_sym = CHAIN_INFO.get(chain_hex, (chain_hex, "???"))

    for tx in data.get("txs", []):
        value_wei = int(tx.get("value", "0") or "0")
        if value_wei == 0:
            continue
        amount = value_wei / 1e18
        from_addr = (tx.get("fromAddress") or "").lower()
        to_addr = (tx.get("toAddress") or "").lower()
        tx_hash = tx.get("hash", "")
        await handle_tx(from_addr, to_addr, amount, native_sym, native_sym,
                        chain_name, tx_hash)

    for ev in data.get("erc20Transfers", []):
        amount = float(ev.get("valueWithDecimals", 0) or 0)
        if amount == 0:
            continue
        from_addr = (ev.get("from") or "").lower()
        to_addr = (ev.get("to") or "").lower()
        tx_hash = ev.get("transactionHash", "")
        token_name = ev.get("tokenName", "Unknown")
        token_symbol = ev.get("tokenSymbol", "???")
        await handle_tx(from_addr, to_addr, amount, token_name, token_symbol,
                        chain_name, tx_hash)

    return {"ok": True}


async def handle_tx(from_addr, to_addr, amount, token_name, token_symbol,
                    chain_name, tx_hash):
    for watched in (from_addr, to_addr):
        user = get_user_by_wallet(watched, chain_name)
        if not user:
            continue
        tx_type = "SEND" if watched == from_addr else "RECEIVE"
        price = await get_token_price(token_symbol)
        usd_value = f"{amount * price:.2f}" if price else None
        await send_alert(
            user_id=user["user_id"],
            wallet_name=user.get("name", ""),
            address=watched,
            chain=chain_name,
            tx_type=tx_type,
            token_name=token_name,
            token_symbol=token_symbol,
            amount=amount,
            usd_value=usd_value,
            tx_hash=tx_hash,
        )
        increment_tx_count(watched, chain_name)


async def run_bot():
    print("🚀 BlockTran bot (Telegram) starting...")
    await dp.start_polling(bot, skip_updates=True)


@app.on_event("startup")
async def startup():
    asyncio.create_task(run_bot())
    print("🔔 Webhook server ready - waiting for Moralis pushes...")