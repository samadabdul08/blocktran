from pymongo import MongoClient
from datetime import datetime
import os
import requests
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv("MONGODB_URI"))
db = client["blocktran"]
wallets_collection = db["wallets"]

def add_wallet(user_id, address, chain, name=""):
    existing = wallets_collection.find_one({
        "user_id": str(user_id),
        "address": address.lower(),
        "chain": chain
    })
    if existing:
        return False, "already_exists"

    wallet = {
        "user_id": str(user_id),
        "address": address.lower(),
        "chain": chain,
        "name": name,
        "active": True,
        "added_at": datetime.utcnow(),
        "tx_count": 0
    }
    wallets_collection.insert_one(wallet)
    return True, "added"

def get_user_wallets(user_id):
    return list(wallets_collection.find({
        "user_id": str(user_id),
        "active": True
    }))

def get_all_wallets():
    return list(wallets_collection.find({"active": True}))

def get_user_by_wallet(address, chain):
    return wallets_collection.find_one({
        "address": address.lower(),
        "chain": chain,
        "active": True
    })

def update_wallet_name(user_id, address, chain, new_name):
    wallets_collection.update_one(
        {"user_id": str(user_id), "address": address.lower(), "chain": chain},
        {"$set": {"name": new_name}}
    )

def remove_wallet(user_id, address, chain):
    wallets_collection.update_one(
        {"user_id": str(user_id), "address": address.lower(), "chain": chain},
        {"$set": {"active": False}}
    )

def increment_tx_count(address, chain):
    wallets_collection.update_one(
        {"address": address.lower(), "chain": chain},
        {"$inc": {"tx_count": 1}, "$set": {"last_seen": datetime.utcnow()}}
    )

def register_to_moralis_stream(address):
    api_key = os.getenv("MORALIS_API_KEY")
    stream_id = "eab9279d-47f8-4709-a0cc-e101690cf070"
    if not api_key:
        print("Moralis key missing - skip")
        return False
    url = f"https://api.moralis-streams.com/streams/evm/{stream_id}/address"
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    payload = {"address": address.lower()}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        if r.status_code in (200, 201):
            print(f"Stream add ok: {address}")
            return True
        print(f"Stream add fail {r.status_code}: {r.text}")
        return False
    except Exception as e:
        print(f"Stream error: {e}")
        return False