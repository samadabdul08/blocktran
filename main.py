import asyncio
import os
import aiohttp
from dotenv import load_dotenv
from bot import bot, dp
from database import get_all_wallets, increment_tx_count
from bot import send_alert

load_dotenv()

MORALIS_API_KEY = os.getenv("MORALIS_API_KEY")

CHAIN_IDS = {
    "ethereum": "0x1",
    "bsc": "0x38",
    "polygon": "0x89",
    "arbitrum": "0xa4b1",
    "optimism": "0xa",
    "avalanche": "0xa86a",
    "base": "0x2105",
    "fantom": "0xfa",
}

async def get_token_price(symbol: str) -> float:
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.coingecko.com/api/v3/simple/price"
            params = {"ids": symbol, "vs_currencies": "usd"}
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
                return data.get(symbol, {}).get("usd", 0)
    except:
        return 0

async def monitor_wallet_moralis(wallet_doc: dict, session: aiohttp.ClientSession):
    address = wallet_doc["address"]
    chain = wallet_doc["chain"]
    user_id = wallet_doc["user_id"]
    wallet_name = wallet_doc.get("name", "")

    if chain not in CHAIN_IDS and chain not in ["solana", "tron"]:
        return

    try:
        if chain in CHAIN_IDS:
            chain_id = CHAIN_IDS[chain]
            url = f"https://deep-index.moralis.io/api/v2.2/{address}/erc20/transfers"
            headers = {"X-API-Key": MORALIS_API_KEY}
            params = {"chain": chain_id, "limit": 5, "order": "DESC"}

            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    return
                data = await resp.json()
                txs = data.get("result", [])

            for tx in txs:
                tx_hash = tx.get("transaction_hash", "")
                from_addr = tx.get("from_address", "").lower()
                to_addr = tx.get("to_address", "").lower()
                value = float(tx.get("value_decimal", 0))
                token_name = tx.get("token_name", "Unknown")
                token_symbol = tx.get("token_symbol", "???")

                if value == 0:
                    continue

                tx_type = "SEND" if from_addr == address else "RECEIVE"

                # Get USD price
                price = await get_token_price(token_symbol.lower())
                usd_value = f"{value * price:.2f}" if price else None

                await send_alert(
                    user_id=user_id,
                    wallet_name=wallet_name,
                    address=address,
                    chain=chain,
                    tx_type=tx_type,
                    token_name=token_name,
                    token_symbol=token_symbol,
                    amount=value,
                    usd_value=usd_value,
                    tx_hash=tx_hash,
                )
                increment_tx_count(address, chain)

    except Exception as e:
        print(f"Monitor error for {address} on {chain}: {e}")

async def polling_loop():
    print("🔄 Starting wallet monitor...")
    seen_txs = set()

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                wallets = get_all_wallets()
                if not wallets:
                    await asyncio.sleep(15)
                    continue

                for wallet in wallets:
                    await monitor_wallet_moralis(wallet, session)
                    await asyncio.sleep(0.5)

            except Exception as e:
                print(f"Polling loop error: {e}")

            await asyncio.sleep(15)

async def main():
    print("🚀 BlockTran Bot starting...")
    await asyncio.gather(
        dp.start_polling(bot, skip_updates=True),
        polling_loop()
    )

if __name__ == "__main__":
    asyncio.run(main())