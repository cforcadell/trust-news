import os
import json
import uuid
import hashlib
import logging
import asyncio
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from web3 import Web3
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

# =========================================================
# Config
# =========================================================
load_dotenv()

RPC_URL = os.getenv("RPC_URL")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
ACCOUNT_ADDRESS = os.getenv("ACCOUNT_ADDRESS")
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS")
CONTRACT_ABI_PATH = os.getenv("CONTRACT_ABI_PATH", "TrustNews.json")

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
REQUEST_TOPIC = os.getenv("KAFKA_REQUEST_TOPIC", "register_blockchain")
RESPONSE_TOPIC = os.getenv("KAFKA_RESPONSE_TOPIC", "register_blockchain_responses")
ENABLE_KAFKA_CONSUMER = os.getenv("ENABLE_KAFKA_CONSUMER", "false").lower() == "true"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TrustNewsAPI")

# =========================================================
# Web3 / Contract
# =========================================================
w3 = Web3(Web3.HTTPProvider(RPC_URL))
with open(CONTRACT_ABI_PATH) as f:
    artifact = json.load(f)

abi = artifact["abi"]
contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=abi)

# =========================================================
# Models
# =========================================================
class MultihashModel(BaseModel):
    hash_function: str
    hash_size: str
    digest: str

class AsertionInputModel(BaseModel):
    idAssertion: Optional[str] = None
    text: str
    categoryId: int

class PublishRequestModel(BaseModel):
    text: str
    cid: str
    assertions: List[AsertionInputModel]
    publisher: str

# =========================================================
# Helpers
# =========================================================
def hash_text_to_multihash(text: str) -> MultihashModel:
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return MultihashModel(hash_function="0x12", hash_size="0x20", digest="0x"+h)

def multihash_to_tuple(mh: MultihashModel):
    hf = bytes.fromhex(mh.hash_function[2:])
    hs = bytes.fromhex(mh.hash_size[2:])
    dg = bytes.fromhex(mh.digest[2:])
    if len(dg) != 32:
        raise ValueError("Digest must be 32 bytes")
    return (hf, hs, dg)

def send_tx(function_call, gas_estimate=3_000_000):
    nonce = w3.eth.get_transaction_count(ACCOUNT_ADDRESS)
    tx = function_call.build_transaction({
        "from": ACCOUNT_ADDRESS,
        "nonce": nonce,
        "gas": gas_estimate,
        "gasPrice": w3.eth.gas_price,
    })
    signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    logger.info(f"TX enviada: {tx_hash.hex()}")
    return receipt

# =========================================================
# FastAPI
# =========================================================
app = FastAPI(title="TrustNews Smart Contract API")

@app.post("/registerNew")
def register_new(data: PublishRequestModel):
    try:
        logger.info(f"registerNew() invoked by {data.publisher}")

        # ===== Hash principal y CID =====
        hash_new = hash_text_to_multihash(data.text)
        hash_ipfs = MultihashModel(
            hash_function="0x12",
            hash_size="0x20",
            digest=data.cid if data.cid.startswith("0x") else "0x" + data.cid
        )

        # ===== Helpers locales para bytes exactos y tuplas =====
        def hex_to_bytes32(hexstr: str) -> bytes:
            b = bytes.fromhex(hexstr[2:]) if hexstr.startswith("0x") else bytes.fromhex(hexstr)
            if len(b) != 32:
                raise ValueError("Digest must be 32 bytes")
            return b

        def multihash_to_tuple(mh: MultihashModel):
            hf = bytes.fromhex(mh.hash_function[2:])   # bytes1
            hs = bytes.fromhex(mh.hash_size[2:])       # bytes1
            dg = hex_to_bytes32(mh.digest)             # bytes32
            return (hf, hs, dg)

        # ===== Preparar assertions =====
        asertions_struct = []
        categoryIds = []

        for a in data.assertions:
            mh = hash_text_to_multihash(a.text)
            empty_validations: list = []

            # struct: (hash_asertion, validations[], categoryId)
            as_tuple = (
                multihash_to_tuple(mh),
                tuple(empty_validations),
                int(a.categoryId)
            )
            asertions_struct.append(as_tuple)
            categoryIds.append(int(a.categoryId))

        asertions_struct = tuple(asertions_struct)
        categoryIds = tuple(categoryIds)

        # ===== Llamada al contrato =====
        func_call = contract.functions.registerNew(
            multihash_to_tuple(hash_new),
            multihash_to_tuple(hash_ipfs),
            asertions_struct,
            categoryIds
        )

        receipt = send_tx(func_call)

        # ===== Parseo seguro de eventos =====
        events = []
        for log in receipt.logs:
            try:
                ev = contract.events.RegisterNewResult().processLog(log)
                events.append(ev)
            except Exception:
                continue

        if not events:
            logger.warning("No RegisterNewResult event found; returning minimal info")
            return {
                "payload": {
                    "post_id": None,
                    "hash_text": hash_new.digest,
                    "assertions": [],
                    "tx_hash": receipt.transactionHash.hex()
                }
            }

        event = events[0]
        post_id = event['args']['postId']
        validator_addresses_by_asertion = event['args']['validatorAddressesByAsertion']

        # ===== Preparar output =====
        asertions_output = []
        for i, a in enumerate(data.assertions):
            digest_hex = asertions_struct[i][0][2].hex()
            addrs_raw = validator_addresses_by_asertion[i] if i < len(validator_addresses_by_asertion) else []
            addrs = [str(x) for x in addrs_raw]
            asertions_output.append({
                "hash_asertion": "0x" + digest_hex,
                "idAssertion": a.idAssertion or str(uuid.uuid4().hex[:8]),
                "text": a.text,
                "categoryId": a.categoryId,
                "validatorAddresses": addrs
            })

        return {
            "payload": {
                "post_id": str(post_id),
                "hash_text": hash_new.digest,
                "assertions": asertions_output,
                "tx_hash": receipt.transactionHash.hex()
            }
        }

    except Exception as e:
        logger.exception(f"Error en registerNew: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tx-status/{tx_hash}")
def tx_status(tx_hash: str):
    receipt = w3.eth.get_transaction_receipt(tx_hash)
    return {"status": receipt.status, "blockNumber": receipt.blockNumber}

# =========================================================
# Kafka consumer opcional
# =========================================================
async def consume_register_blockchain():
    consumer = AIOKafkaConsumer(
        REQUEST_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id="trustnews-api-group",
        auto_offset_reset="earliest"
    )
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP)

    await consumer.start()
    await producer.start()
    logger.info("Kafka consumer y producer iniciados")

    try:
        async for msg in consumer:
            try:
                payload_msg = json.loads(msg.value.decode())
                publish_input = PublishRequestModel(**payload_msg)
                result = await asyncio.to_thread(register_new, publish_input)
                await producer.send_and_wait(RESPONSE_TOPIC, json.dumps({
                    "action": "blockchain_registered",
                    "order_id": payload_msg.get("order_id"),
                    "payload": result
                }).encode())
                logger.info(f"Respuesta enviada para order_id={payload_msg.get('order_id')}")
            except Exception as e:
                logger.error(f"Error procesando mensaje Kafka: {e}")
    finally:
        await consumer.stop()
        await producer.stop()
        logger.info("Kafka detenido")

@app.on_event("startup")
async def startup_event():
    if ENABLE_KAFKA_CONSUMER:
        asyncio.create_task(consume_register_blockchain())
        logger.info("Kafka consumer iniciado en background")
