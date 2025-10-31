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

def safe_multihash_to_tuple(mh: MultihashModel):
    """
    Convierte SHA256 (hex) a bytes, pero si digest no es hex (ej. CID IPFS),
    devolvemos 32 bytes vacíos y lo guardamos como string en el contrato (emulado).
    """
    hf = bytes.fromhex(mh.hash_function[2:])
    hs = bytes.fromhex(mh.hash_size[2:])
    
    try:
        dg = bytes.fromhex(mh.digest[2:])
        if len(dg) != 32:
            dg = dg.ljust(32, b'\0')
    except ValueError:
        dg = b'\0' * 32  # fallback para CID no hex
        logger.warning(f"Digest no hex, usando bytes vacíos: {mh.digest}")

    return (hf, hs, dg)

def hash_text_to_multihash(text: str) -> MultihashModel:
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return MultihashModel(hash_function="0x12", hash_size="0x20", digest="0x" + h)



def hash_text_to_multihash(text: str) -> MultihashModel:
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return MultihashModel(hash_function="0x12", hash_size="0x20", digest="0x" + h)

def multihash_to_tuple(mh: MultihashModel):
    hf = bytes.fromhex(mh.hash_function[2:])
    hs = bytes.fromhex(mh.hash_size[2:])
    dg = bytes.fromhex(mh.digest[2:])
    if len(dg) != 32:
        raise ValueError("Digest must be 32 bytes")
    return (hf, hs, dg)

def send_tx_async(function_call, gas_estimate=3_000_000):
    nonce = w3.eth.get_transaction_count(ACCOUNT_ADDRESS)
    tx = function_call.build_transaction({
        "from": ACCOUNT_ADDRESS,
        "nonce": nonce,
        "gas": gas_estimate,
        "gasPrice": w3.eth.gas_price,
    })
    signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    logger.info(f"TX enviada (no minada aún): {tx_hash.hex()}")
    return tx_hash.hex()

def wait_for_receipt(tx_hash: str):
    logger.info(f"Esperando minado de {tx_hash}...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    logger.info(f"TX minada en bloque {receipt.blockNumber}")
    return receipt

def parse_registernew_event(receipt, data: PublishRequestModel):
    events = contract.events.RegisterNewResult().process_receipt(receipt)
    if not events:
        logger.warning("No RegisterNewResult event found; returning minimal info")
        return {
            "postId": None,
            "hash_text": "",
            "assertions": [],
            "tx_hash": receipt.transactionHash.hex()
        }

    event = events[0]
    postId = event['args']['postId']
    validator_addresses_by_asertion = event['args']['validatorAddressesByAsertion']

    # reconstrucción hashes
    asertions_output = []
    for i, a in enumerate(data.assertions):
        mh = hash_text_to_multihash(a.text)
        digest_hex = mh.digest[2:]
        addrs_raw = validator_addresses_by_asertion[i] if i < len(validator_addresses_by_asertion) else []
        addrs = [str(x) for x in addrs_raw]
        asertions_output.append({
            "hash_asertion": "0x" + digest_hex,
            "idAssertion": a.idAssertion or str(uuid.uuid4().hex[:8]),
            "text": a.text,
            "categoryId": a.categoryId,
            "validatorAddresses": addrs
        })

    hash_new = hash_text_to_multihash(data.text)

    return {
        "postId": str(postId),
        "hash_text": hash_new.digest,
        "assertions": asertions_output,
        "tx_hash": receipt.transactionHash.hex()
    }

# =========================================================
# FastAPI
# =========================================================
app = FastAPI(title="TrustNews Smart Contract API")

@app.post("/registerNew")
def register_new(data: PublishRequestModel):
    """Lanza la transacción sin esperar al minado, devolviendo tx_hash."""
    try:
        logger.info(f"registerNew() invoked by {data.publisher}")
        hash_new = hash_text_to_multihash(data.text)
        hash_ipfs = MultihashModel(
            hash_function="0x12",
            hash_size="0x20",
            digest=data.cid if data.cid.startswith("0x") else "0x" + data.cid
        )

        asertions_struct = []
        categoryIds = []
        for a in data.assertions:
            mh = hash_text_to_multihash(a.text)
            as_tuple = (multihash_to_tuple(mh), tuple([]), int(a.categoryId))
            asertions_struct.append(as_tuple)
            categoryIds.append(int(a.categoryId))

        func_call = contract.functions.registerNew(
            safe_multihash_to_tuple(hash_new),
            safe_multihash_to_tuple(hash_ipfs),
            tuple(asertions_struct),
            tuple(categoryIds)
        )

        tx_hash = send_tx_async(func_call)
        return {"tx_hash": tx_hash, "result": False}

    except Exception as e:
        logger.exception(f"Error en registerNew: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tx-status/{tx_hash}")
def tx_status(tx_hash: str):
    """Consulta si la transacción está minada y devuelve el payload completo si lo está."""
    try:
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        if receipt is None:
            return {"result": False, "status": "pending"}

        if receipt.status == 1:
            # Intenta reconstruir los eventos como la parte asíncrona
            try:
                # Necesitamos un PublishRequestModel para el parseo completo, si lo tenemos cacheado.
                # Si no lo tenemos (porque no se guarda), devolvemos solo la info del receipt.
                # Por simplicidad: devolvemos solo los datos del evento.
                events = contract.events.RegisterNewResult().process_receipt(receipt)
                if not events:
                    return {
                        "result": True,
                        "status": "mined",
                        "blockNumber": receipt.blockNumber,
                        "payload": {"message": "Transaction mined but no events found."}
                    }

                event = events[0]
                postId = event['args']['postId']
                validator_addresses_by_asertion = event['args']['validatorAddressesByAsertion']

                # Construimos payload tipo asincrono
                payload = {
                    "postId": str(postId),
                    "validatorAddressesByAsertion": [
                        [str(a) for a in addrs]
                        for addrs in validator_addresses_by_asertion
                    ],
                    "tx_hash": tx_hash
                }

                return {
                    "result": True,
                    "status": "mined",
                    "blockNumber": receipt.blockNumber,
                    "payload": payload
                }

            except Exception as e:
                logger.error(f"Error al parsear evento de {tx_hash}: {e}")
                return {
                    "result": True,
                    "status": "mined",
                    "blockNumber": receipt.blockNumber,
                    "payload": {"message": "Transaction mined but parse failed."}
                }

        else:
            return {"result": False, "status": "pending"}

    except Exception:
        return {"result": False, "status": "pending"}


# =========================================================
# Kafka consumer opcional (asincrónico)
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
                publish_input = PublishRequestModel(**payload_msg.get("payload", {}))
                
                # Paso 1: enviar transacción
                tx_info = register_new(publish_input)
                tx_hash = tx_info["tx_hash"]

                # Paso 2: esperar hasta que se mine
                receipt = await asyncio.to_thread(wait_for_receipt, tx_hash)
                result = parse_registernew_event(receipt, publish_input)

                await producer.send_and_wait(RESPONSE_TOPIC, json.dumps({
                    "action": "blockchain_registered",
                    "order_id": payload_msg.get("order_id"),
                    "payload": result
                }).encode())
                logger.info(f"Respuesta enviada para order_id={payload_msg.get('order_id')} payload={json.dumps(result, indent=2)}")

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
