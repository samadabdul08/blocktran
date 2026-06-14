import asyncio
import os
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest
from dotenv import load_dotenv
from database import add_wallet, get_user_wallets, update_wallet_name, remove_wallet, register_to_moralis_stream, get_user_by_wallet

load_dotenv()

bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
dp = Dispatcher(storage=MemoryStorage())

# EVM address pattern
EVM_PATTERN = re.compile(r'^0x[a-fA-F0-9]{40}$')
SOL_PATTERN = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')
TRON_PATTERN = re.compile(r'^T[a-zA-Z0-9]{33}$')

CHAINS = {
    "ethereum": "🔷 Ethereum",
    "bsc": "🟡 BNB Chain",
    "polygon": "🟣 Polygon",
    "arbitrum": "🔷 Arbitrum",
    "optimism": "🔴 Optimism",
    "avalanche": "🔺 Avalanche",
    "base": "🔵 Base",
    "fantom": "🔵 Fantom",
    "solana": "🟢 Solana",
    "tron": "🔴 TRON",
}

class WalletStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_rename_address = State()
    waiting_for_new_name = State()

pending_wallets = {}

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 <b>Welcome to BlockTran!</b>\n\n"
        "I monitor blockchain wallets in real-time and alert you instantly on any transaction.\n\n"
        "<b>🔗 Supported Chains:</b>\n"
        "🔷 Ethereum | 🟡 BNB Chain | 🟣 Polygon\n"
        "🔷 Arbitrum | 🔴 Optimism | 🔺 Avalanche\n"
        "🔵 Base | 🔵 Fantom | 🟢 Solana | 🔴 TRON\n\n"
        "<b>📋 Commands:</b>\n"
        "/add — Add wallet\n"
        "/list — View wallets\n"
        "/rename — Rename wallet\n"
        "/remove — Remove wallet\n\n"
        "<i>💡 Just paste any wallet address to add it!</i>",
        parse_mode="HTML"
    )

@dp.message(Command("add"))
async def cmd_add(message: types.Message):
    await message.answer("📋 Send me the wallet address:")

@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    wallets = get_user_wallets(message.from_user.id)
    if not wallets:
        await message.answer("No wallets yet! Send any address to add one.")
        return

    text = f"<b>📋 Your Wallets ({len(wallets)})</b>\n\n"
    for w in wallets:
        name = w.get('name') or '(no name)'
        chain = CHAINS.get(w['chain'], w['chain'])
        text += f"{chain}\n"
        text += f"  🏷 <b>{name}</b>\n"
        text += f"  <code>{w['address']}</code>\n"
        text += f"  📊 {w.get('tx_count', 0)} txs\n\n"

    await message.answer(text, parse_mode="HTML")

@dp.message(Command("rename"))
async def cmd_rename(message: types.Message, state: FSMContext):
    await state.set_state(WalletStates.waiting_for_rename_address)
    await message.answer("Which wallet to rename? Send the address:")

@dp.message(Command("remove"))
async def cmd_remove(message: types.Message):
    await message.answer("Send the wallet address to remove:")

@dp.message(WalletStates.waiting_for_rename_address)
async def process_rename_address(message: types.Message, state: FSMContext):
    await state.update_data(address=message.text.strip())
    await state.set_state(WalletStates.waiting_for_new_name)
    await message.answer("Enter the new name:")

@dp.message(WalletStates.waiting_for_new_name)
async def process_new_name(message: types.Message, state: FSMContext):
    data = await state.get_data()
    address = data.get('address', '').lower()
    wallets = get_user_wallets(message.from_user.id)

    updated = False
    for w in wallets:
        if w['address'] == address:
            update_wallet_name(message.from_user.id, address, w['chain'], message.text.strip())
            updated = True
            break

    await state.clear()
    if updated:
        await message.answer(f"✅ Wallet renamed to: <b>{message.text.strip()}</b>", parse_mode="HTML")
    else:
        await message.answer("❌ Wallet not found.")

@dp.message(WalletStates.waiting_for_name)
async def process_wallet_name(message: types.Message, state: FSMContext):
    data = await state.get_data()
    name = message.text.strip()

    if name.lower() == '/skip':
        name = ""

    success, result = add_wallet(
        message.from_user.id,
        data['address'],
        data['chain'],
        name
    )

    register_to_moralis_stream(data['address'])
    await state.clear()
    chain_name = CHAINS.get(data['chain'], data['chain'])

    if success:
        await message.answer(
            f"✅ <b>Wallet added!</b>\n\n"
            f"{chain_name}\n"
            f"<code>{data['address']}</code>\n"
            f"🏷 Name: {name or '(no name)'}\n\n"
            f"<i>I'll alert you on every transaction!</i>",
            parse_mode="HTML"
        )
    else:
        await message.answer("⚠️ This wallet is already being monitored!")

@dp.message()
async def handle_address(message: types.Message, state: FSMContext):
    if not message.text:
        return
    text = message.text.strip()

    # Detect chain from address
    detected_chains = []
    if EVM_PATTERN.match(text):
        detected_chains = ["ethereum", "bsc", "polygon", "arbitrum", "optimism", "avalanche", "base", "fantom"]
    elif SOL_PATTERN.match(text):
        detected_chains = ["solana"]
    elif TRON_PATTERN.match(text):
        detected_chains = ["tron"]

    if not detected_chains:
        await message.answer("❓ I didn't understand that. Use /help or send a wallet address.")
        return

    # For EVM — ask which chain or all
    if len(detected_chains) > 1:
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text=CHAINS[c], callback_data=f"chain:{text}:{c}")
             for c in detected_chains[:5]]
        ] + [
            [types.InlineKeyboardButton(text="🔵 All EVM Chains", callback_data=f"chain:{text}:all_evm")]
        ])
        await message.answer(
            f"📍 Address detected!\n<code>{text}</code>\n\nSelect chain:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await state.update_data(address=text, chain=detected_chains[0])
        await state.set_state(WalletStates.waiting_for_name)
        await message.answer("✏️ Give this wallet a name (or send /skip):")

@dp.callback_query(F.data.startswith("chain:"))
async def process_chain_selection(callback: types.CallbackQuery, state: FSMContext):
    _, address, chain = callback.data.split(":", 2)

    if chain == "all_evm":
        evm_chains = ["ethereum", "bsc", "polygon", "arbitrum", "optimism", "avalanche", "base", "fantom"]
        added = 0
        for c in evm_chains:
            success, _ = add_wallet(callback.from_user.id, address, c, "")
            if success:
                added += 1
        register_to_moralis_stream(address)
        try:
            await callback.message.edit_text(
                f"✅ Added to <b>{added}</b> EVM chains!\n<code>{address}</code>",
                parse_mode="HTML"
            )
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise
    else:
        register_to_moralis_stream(address)
        await state.update_data(address=address, chain=chain)
        await state.set_state(WalletStates.waiting_for_name)
        await callback.message.edit_text("✏️ Give this wallet a name (or send /skip):")

    await callback.answer()

async def send_alert(user_id: str, wallet_name: str, address: str, chain: str,
                     tx_type: str, token_name: str, token_symbol: str,
                     amount: float, usd_value: str, tx_hash: str):
    arrow = "📥" if tx_type == "RECEIVE" else "📤"
    direction = "🟢 RECEIVED" if tx_type == "RECEIVE" else "🔴 SENT"
    chain_name = CHAINS.get(chain, chain)

    msg = (
        f"{arrow} <b>{direction}</b> — {chain_name}\n\n"
        f"🔴 Wallet: <b>{wallet_name or address[:10]+'...'}</b>\n"
        f"📍 <code>{address[:8]}...{address[-6:]}</code>\n\n"
        f"🪙 Token: <b>{token_name}</b> ({token_symbol})\n"
        f"💰 Amount: <b>{amount:.6f} {token_symbol}</b>"
    )

    if usd_value:
        msg += f" <i>(${usd_value})</i>"

    msg += f"\n\n🔗 <a href='https://etherscan.io/tx/{tx_hash}'>View Transaction</a>"
    msg += f"\n🕐 {__import__('datetime').datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"

    try:
        await bot.send_message(user_id, msg, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        print(f"Alert send failed: {e}")

from aiohttp import web

async def moralis_webhook(request):
    try:
        data = await request.json()
    except Exception:
        return web.Response(text="bad json")

    if not data.get("confirmed", False):
        return web.Response(text="ok")

    txs = data.get("txs", [])
    erc20 = data.get("erc20Transfers", [])
    chain_hex = data.get("chainId", "")

    chain_map = {
        "0x1": "ethereum", "0x38": "bsc", "0x89": "polygon",
        "0xa4b1": "arbitrum", "0xa": "optimism", "0xa86a": "avalanche",
        "0x2105": "base", "0xfa": "fantom",
    }
    chain = chain_map.get(chain_hex, "ethereum")

    for tx in txs:
        to_addr = (tx.get("toAddress") or "").lower()
        from_addr = (tx.get("fromAddress") or "").lower()
        value = int(tx.get("value", "0"))
        if value == 0:
            continue
        amount = value / 1e18
        for addr, tx_type in [(to_addr, "RECEIVE"), (from_addr, "SEND")]:
            user = get_user_by_wallet(addr, chain)
            if user:
                await send_alert(
                    user["user_id"], user.get("name", ""), addr, chain,
                    tx_type, "Native", "ETH" if chain == "ethereum" else "BNB",
                    amount, "", tx.get("hash", "")
                )

    for ev in erc20:
        to_addr = (ev.get("to") or "").lower()
        from_addr = (ev.get("from") or "").lower()
        decimals = int(ev.get("tokenDecimals", "18") or "18")
        raw = int(ev.get("value", "0") or "0")
        amount = raw / (10 ** decimals)
        for addr, tx_type in [(to_addr, "RECEIVE"), (from_addr, "SEND")]:
            user = get_user_by_wallet(addr, chain)
            if user:
                await send_alert(
                    user["user_id"], user.get("name", ""), addr, chain,
                    tx_type, ev.get("tokenName", "Token"),
                    ev.get("tokenSymbol", ""), amount, "",
                    ev.get("transactionHash", "")
                )

    return web.Response(text="ok")

async def main():
    app = web.Application()
    app.router.add_post("/webhook", moralis_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "10000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Webhook server started on port {port}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())