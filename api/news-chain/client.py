import requests
import json
from web3 import Web3
import asyncio
from fastapi import FastAPI, Request
import uvicorn
import os

# ========================================
# CONFIG CLIENTE
# ========================================
API_URL = "http://localhost:8000"  # URL del API Trust Manager
PRIVATE_KEY = os.getenv("PRIVATE_KEY")  # Clave privada del usuario
ACCOUNT_ADDRESS = os.getenv("ACCOUNT_ADDRESS")  # Dirección de la wallet
RPC_URL = os.getenv("RPC_URL")
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS")

# Inicializar Web3
w3 = Web3(Web3.HTTPProvider(RPC_URL))
with open("contract_abi.json") as f:
    abi = json.load(f)
contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=abi)

# ========================================
# PUBLICAR NUEVO POST
# ========================================
def publish_new(hash_new: dict, hash_ipfs: dict, publisher: str, callback_url: str):
    payload = {
        "hash_new": hash_new,
        "hash_ipfs": hash_ipfs,
        "publisher": publisher,
        "callback_url": callback_url
    }
    resp = requests.post(f"{API_URL}/publishNew", json=payload)
    if resp.status_code == 200 or resp.status_code == 202:
        data = resp.json()
        print(f"Orden enviada: {data}")
        return data["order_id"], data["status"]
    else:
        raise Exception(f"Error publicando noticia: {resp.text}")

# ========================================
# CALLBACK SERVER (para recibir notificación de IPFS)
# ========================================
app = FastAPI()

@app.post("/callback")
async def callback_endpoint(req: Request):
    data = await req.json()
    order_id = data.get("order_id")
    cid = data.get("cid")
    print(f"Callback recibido para order_id={order_id}, CID={cid}")

    # Firmar y enviar la transacción al smart contract
    try:
        nonce = w3.eth.get_transaction_count(ACCOUNT_ADDRESS)
        tx = contract.functions.publishNew(
            (0x12, 0x20, bytes.fromhex("00"*32)),  # ejemplo: multihash hash_new
            (0x12, 0x20, bytes.fromhex("00"*32)),  # ejemplo: hash_ipfs
            [],  # lista de assertions vacía por ejemplo
            ACCOUNT_ADDRESS
        ).build_transaction({
            "from": ACCOUNT_ADDRESS,
            "nonce": nonce,
            "gas": 800000,
            "gasPrice": w3.toWei("1", "gwei")
        })
        signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        print(f"Transacción enviada al smart contract, hash={tx_hash.hex()}")
    except Exception as e:
        print(f"Error enviando transacción: {e}")

    return {"status": "ok"}

# ========================================
# EJEMPLO USO
# ========================================
if __name__ == "__main__":
    # Ejemplo hash
    hash_new = {"hash_function": "0x12", "hash_size": "0x20", "digest": "0x" + "00"*32}
    hash_ipfs = {"hash_function": "0x12", "hash_size": "0x20", "digest": "0x" + "11"*32}

    order_id, status = publish_new(hash_new, hash_ipfs, ACCOUNT_ADDRESS, "http://localhost:8080/callback")
    print(f"Orden creada: {order_id}, estado inicial: {status}")

    # Arrancar servidor para recibir callback
    uvicorn.run(app, host="0.0.0.0", port=8080)
