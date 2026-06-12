import asyncio
import os
import aiohttp
from dotenv import load_dotenv
from bot import bot, dp, send_alert
from database import get_all_wallets, increment_tx_count

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

NATIVE_SYMBOL = {
    "ethereum": "ETH",
    "bsc": "BNB",
    "polygon": "MATIC",
    "arbitrum": "ETH",
    "optimism": "ETH",
    "avalanche": "AVAX",
    "base": "ETH",
    "fantom": "FTM",
}

COINGECKO_IDS = {
    "eth": "ethereum",
    "bnb": "binancecoin",
    "matic": "matic-network",
    "avax": "avalanche-2",
    "ftm": "fantom",
    "usdt": "tether",
    "usdc": "usd-coin",
}

# Dedupe memory (in-RAM)
seen_txs = set()
baselined = set()


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


async def fetch_json(session, url, params, headers):
    try:
        async with session.get(
            url, headers=headers, params=params,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                return None
            return await resp.json()
    except Exception:
        return None


async def monitor_wallet_moralis(wallet_doc: dict, session: aiohttp.ClientSession):
    address = wallet_doc["address"]
    chain = wallet_doc["chain"]
    user_id = wallet_doc["user_id"]
    wallet_name = wallet_doc.get("name", "")

    if chain not in CHAIN_IDS:
        return

    chain_id = CHAIN_IDS[chain]
    headers = {"X-API-Key": MORALIS_API_KEY}
    key_prefix = f"{address.lower()}:{chain}"
    txs_found = []

    try:
        # 1) NATIVE transactions (BNB, ETH, MATIC...)
        url_native = f"https://deep-index.moralis.io/api/v2.2/{address}"
        data = await fetch_json(
            session, url_native,
            {"chain": chain_id, "limit": 5, "order": "DESC"}, headers,
        )
        if data:
            for tx in data.get("result", []):
                value_wei = int(tx.get("value", "0") or "0")
                if value_wei == 0:
                    continue
                amount = value_wei / 1e18
                sym = NATIVE_SYMBOL.get(chain, "???")
                txs_found.append((
                    tx.get("hash", ""),
                    (tx.get("from_address") or "").lower(),
                    (tx.get("to_address") or "").lower(),
                    amount, sym, sym,
                ))

        # 2) ERC20 token transfers
        url_erc20 = f"https://deep-index.moralis.io/api/v2.2/{address}/erc20/transfers"
        data = await fetch_json(
            session, url_erc20,
            {"chain": chain_id, "limit": 5, "order": "DESC"}, headers,
        )
        if data:
            for tx in data.get("result", []):
                amount = float(tx.get("value_decimal", 0) or 0)
                if amount == 0:
                    continue
                txs_found.append((
                    tx.get("transaction_hash", ""),
                    (tx.get("from_address") or "").lower(),
                    (tx.get("to_address") or "").lower(),
                    amount,
                    tx.get("token_name", "Unknown"),
                    tx.get("token_symbol", "???"),
                ))

        first_time = key_prefix not in baselined

        for tx_hash, from_addr, to_addr, amount, token_name, token_symbol in txs_found:
            seen_key = f"{key_prefix}:{tx_hash}"
            if seen_key in seen_txs:
                continue
            seen_txs.add(seen_key)

            # First poll = baseline old txs, no alerts for history
            if first_time:
                continue

            tx_type = "SEND" if from_addr == address.lower() else "RECEIVE"

            price = await get_token_price(token_symbol)
            usd_value = f"{amount * price:.2f}" if price else None

            await send_alert(
                user_id=user_id,
                wallet_name=wallet_name,
                address=address,
                chain=chain,
                tx_type=tx_type,
                token_name=token_name,
                token_symbol=token_symbol,
                amount=amount,
                usd_value=usd_value,
                tx_hash=tx_hash,
            )
            increment_tx_count(address, chain)

        if first_time:
            baselined.add(key_prefix)

    except Exception as e:
        print(f"Monitor error for {address} on {chain}: {e}")


async def polling_loop():
    print("🔄 Starting wallet monitor...")

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

            await asyncio.sleep(30)


async def main():
    print("🚀 BlockTran Bot starting...")
    await asyncio.gather(
        dp.start_polling(bot, skip_updates=True),
        polling_loop(),
    )


if __name__ == "__main__":
    asyncio.run(main())