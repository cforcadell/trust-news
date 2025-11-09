import os
import json
import uuid
import hashlib
import logging
import asyncio
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ValidationError # BaseModel necesario si no se importa en common.async_models
from dotenv import load_dotenv
from web3 import Web3
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

# Importar modelos comunes
from common.async_models import Multihash, Assertion, RegisterBlockchainRequest, BlockchainRegisteredResponse, RegisterBlockchainPayload 

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
# Inicialización de Web3
w3 = Web3(Web3.HTTPProvider(RPC_URL))

# Carga del ABI del contrato
try:
    with open(CONTRACT_ABI_PATH) as f:
        artifact = json.load(f)
    abi = artifact["abi"]
    contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=abi)
except Exception as e:
    logger.error(f"Error cargando ABI o inicializando contrato: {e}")
    # Usar un contrato placeholder si la carga falla para permitir que el worker continúe
    class DummyContract:
        def __init__(self):
            self.functions = self
            self.events = self
            self.process_receipt = lambda x: []
            self.registerNew = lambda *args: self
            self.build_transaction = lambda x: {}
    contract = DummyContract()
    
# =========================================================
# Helpers
# =========================================================

# NOTA: Se ha eliminado una definición duplicada de hash_text_to_multihash

def safe_multihash_to_tuple(mh: Multihash) -> tuple:
    """
    Convierte Multihash (Pydantic) a la tupla (bytes, bytes, bytes32)
    requerida por el contrato Solidity.
    """
    try:
        # Aseguramos que los campos sean strings
        hash_function = getattr(mh, "hash_function", "0x00")
        hash_size = getattr(mh, "hash_size", "0x00")
        digest = getattr(mh, "digest", "")

        # Si digest es un objeto (por ejemplo otro modelo Pydantic), lo convertimos a string
        if not isinstance(digest, str):
            digest = str(digest)

        hf = bytes.fromhex(hash_function.removeprefix("0x"))
        hs = bytes.fromhex(hash_size.removeprefix("0x"))

        # Limpieza del digest (puede venir con o sin 0x)
        digest_clean = digest[2:] if digest.startswith("0x") else digest
        dg = bytes.fromhex(digest_clean)

        # Rellenar o truncar a 32 bytes (bytes32 en Solidity)
        if len(dg) > 32:
            dg = dg[:32]
        elif len(dg) < 32:
            dg = dg.ljust(32, b'\0')

    except Exception as e:
        logger.warning(f"Error en safe_multihash_to_tuple con digest '{mh}': {e}. Usando fallback.")
        # Fallback si el digest no es un hex válido
        hf = b'\x00'
        hs = b'\x00'
        dg = b'\0' * 32

    return (hf, hs, dg)


def hash_text_to_multihash(text: str) -> Multihash:
    """Calcula el SHA256 y lo envuelve en el modelo Multihash."""
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    # 0x12 es SHA256, 0x20 es 32 bytes (256 bits)
    return Multihash(hash_function="0x12", hash_size="0x20", digest="0x" + h)

def multihash_to_tuple(mh: Multihash) -> tuple:
    """Convierte Multihash a la tupla requerida (usado para aserciones)."""
    hf = bytes.fromhex(mh.hash_function[2:])
    hs = bytes.fromhex(mh.hash_size[2:])
    dg = bytes.fromhex(mh.digest[2:])
    
    if len(dg) != 32:
        # Esto debería fallar si el hash no es SHA256
        raise ValueError("Digest debe ser exactamente 32 bytes.")
    return (hf, hs, dg)

def send_tx_async(function_call, gas_estimate=3_000_000):
    """Firma y envía la transacción a la red."""
    if not w3.is_connected():
        raise ConnectionError("Web3 no está conectado al RPC.")
    if not PRIVATE_KEY or not ACCOUNT_ADDRESS:
        raise ValueError("Variables PRIVATE_KEY o ACCOUNT_ADDRESS no definidas.")
        
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
    """Espera a que la transacción sea minada."""
    logger.info(f"Esperando minado de {tx_hash}...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    logger.info(f"TX minada en bloque {receipt.blockNumber}")
    return receipt

def parse_registernew_event(receipt, data: RegisterBlockchainRequest) -> dict:
    """Extrae datos relevantes del evento RegisterNewResult de la transacción minada."""
    events = contract.events.RegisterNewResult().process_receipt(receipt)
    if not events:
        logger.warning("No se encontró evento RegisterNewResult; devolviendo info mínima.")
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
        # Se genera el hash de la aserción original para la respuesta
        mh = hash_text_to_multihash(a.text)
        digest_hex = mh.digest[2:]
        
        # Obtener las direcciones de los validadores para esta aserción
        addrs_raw = validator_addresses_by_asertion[i] if i < len(validator_addresses_by_asertion) else []
        logger.info(f"Aserción {i} tiene {len(addrs_raw)} validadores registrados. {addrs_raw}")
        addrs = [{"address": str(x)} for x in addrs_raw]
        logger.info(f"Direcciones de validadores para aserción {i}: {addrs}")
        
        # El modelo Assertion ya garantiza que a.categoryId es un int
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
    
def safe_hex(value):
    if value is None:
        return None
    if isinstance(value, bytes):
        h = value.hex()
        if not h.startswith("0x"):
            h = "0x" + h
        return h
    if isinstance(value, str) and value.startswith("0x0x"):
        return "0x" + value[4:]
    return value


# =========================================================
# FastAPI
# =========================================================
app = FastAPI(title="TrustNews Smart Contract API")

@app.post("/registerNew")
def register_new(data: RegisterBlockchainRequest):
    """Lanza la transacción sin esperar al minado, devolviendo tx_hash."""
    try:
        logger.info(f"registerNew() invoked by {data.publisher}")
        hash_new = hash_text_to_multihash(data.text)
        
        # El CID de IPFS/Arweave se convierte a Multihash para el contrato
        hash_ipfs = Multihash(
            hash_function="0x12",
            hash_size="0x20",
            digest=data.cid if data.cid.startswith("0x") else "0x" + data.cid
        )

        asertions_struct = []
        categoryIds = []
        for a in data.assertions:
            mh = hash_text_to_multihash(a.text)
            
            # Formato de aserción para el contrato (Multihash, array de validadores [vacío], categoryId)
            as_tuple = (multihash_to_tuple(mh), tuple([]), a.categoryId) 
            asertions_struct.append(as_tuple)
            # categoryId ya es int gracias a Pydantic
            categoryIds.append(a.categoryId)

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


@app.get("/tx/status/{tx_hash}")
def tx_status(tx_hash: str):
    """Consulta si la transacción está minada y devuelve el payload completo si lo está."""
    try:
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        if receipt is None:
            return {"result": False, "status": "pending"}

        if receipt.status == 1:
            # Transacción minada y exitosa
            try:
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
            # Transacción fallida
            return {"result": False, "status": "failed", "blockNumber": receipt.blockNumber}

    except Exception as e:
        logger.error(f"Error consultando estado de TX {tx_hash}: {e}")
        return {"result": False, "status": "error"}

@app.get("/tx/{tx_hash}")
def get_transaction(tx_hash: str):
    """
    Consulta una transacción concreta en la blockchain y devuelve su estado,
    bloque, emisor, receptor y gas utilizado.
    Convierte todos los campos binarios a hex para evitar errores UTF-8.
    """
    try:
        tx = w3.eth.get_transaction(tx_hash)
        receipt = w3.eth.get_transaction_receipt(tx_hash)

        if not tx:
            raise HTTPException(status_code=404, detail=f"No existe la transacción {tx_hash}")



        result = {
            "tx_hash": safe_hex(tx.hash),
            "from": tx["from"],
            "to": tx["to"],
            "blockNumber": tx.blockNumber,
            "gas": tx.gas,
            "gasPrice": tx.gasPrice,
            "nonce": tx.nonce,
            "value": tx.value,
        }

        if receipt:
            result.update({
                "status": "success" if receipt.status == 1 else "failed",
                "blockHash": safe_hex(receipt.blockHash),
                "transactionIndex": receipt.transactionIndex,
                "gasUsed": receipt.gasUsed,
                "cumulativeGasUsed": receipt.cumulativeGasUsed,
                "contractAddress": receipt.contractAddress,

            })
        else:
            result["status"] = "pending"

        return {"result": True, "payload": result}

    except Exception as e:
        logger.error(f"Error consultando transacción {tx_hash}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/block/{block_id}")
def get_block(block_id: int):
    """
    Devuelve información del bloque y las transacciones que contiene.
    """
    try:
        block = w3.eth.get_block(block_id, full_transactions=True)
        if not block:
            raise HTTPException(status_code=404, detail=f"No existe el bloque {block_id}")

        block_info = {
            "blockNumber": block.number,
            "blockHash": block.hash.hex(),
            "timestamp": block.timestamp,
            "miner": block.miner,
            "transactionCount": len(block.transactions),
            "transactions": [
                {
                    "tx_hash": tx.hash.hex(),
                    "from": tx["from"],
                    "to": tx["to"],
                    "value": tx["value"],
                    "gas": tx["gas"],
                }
                for tx in block.transactions
            ],
        }

        return {"result": True, "payload": block_info}

    except Exception as e:
        logger.error(f"Error consultando bloque {block_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================
# Kafka consumer opcional (asincrónico)
# =========================================================
async def consume_register_blockchain():
    """Consume mensajes de Kafka para registrarlos en la Blockchain."""
    consumer = AIOKafkaConsumer(
        REQUEST_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id="trustnews-api-group",
        auto_offset_reset="earliest"
    )
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP)
    
    try:
        await consumer.start()
        await producer.start()
        logger.info("Kafka consumer y producer iniciados")

        async for msg in consumer:
            payload_msg = {}
            try:
                payload_msg = json.loads(msg.value.decode())
                order_id = payload_msg.get("order_id", str(uuid.uuid4()))
                logger.info(f"[{order_id}] Mensaje recibido de Kafka.")
                
                # Validar el payload usando el nuevo modelo común
                # Asumo que el payload del mensaje Kafka es de tipo RegisterBlockchainPayload
                publish_input = RegisterBlockchainPayload(**payload_msg.get("payload", {}))

                # Paso 1: enviar transacción (sincrónico, pero ejecutado por to_thread)
                tx_info = await asyncio.to_thread(register_new, publish_input)
                tx_hash = tx_info["tx_hash"]
                logger.info(f"[{order_id}] TX enviada: {tx_hash}")

                # Paso 2: esperar hasta que se mine (sincrónico, en otro thread)
                receipt = await asyncio.to_thread(wait_for_receipt, tx_hash)
                
                # Paso 3: parsear el resultado (sincrónico)
                result = await asyncio.to_thread(parse_registernew_event, receipt, publish_input)
                
                # Crear la respuesta Kafka (asumo BlockchainRegisteredResponse para el tipo de respuesta)
                response_model = BlockchainRegisteredResponse(
                    action="blockchain_registered",
                    order_id=order_id,
                    payload=result
                )

                # Paso 4: Publicar el resultado
                await producer.send_and_wait(
                    RESPONSE_TOPIC, 
                    response_model.model_dump_json(exclude_none=True).encode("utf-8")
                )
                logger.info(f"[{order_id}] Respuesta publicada en {RESPONSE_TOPIC}")

            except ValidationError as ve:
                logger.error(f"[{payload_msg.get('order_id', 'N/A')}] Error de validación del payload de Kafka: {ve}")
            except Exception as e:
                logger.exception(f"Error procesando mensaje Kafka: {e}")

    finally:
        await consumer.stop()
        await producer.stop()
        logger.info("Kafka detenido")

@app.on_event("startup")
async def startup_event():
    if ENABLE_KAFKA_CONSUMER:
        asyncio.create_task(consume_register_blockchain())
        logger.info("Kafka consumer iniciado en background")