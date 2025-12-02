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
from fastapi import Query
import base58
from web3.middleware import geth_poa_middleware

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

w3.middleware_onion.inject(geth_poa_middleware, layer=0)

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





def safe_multihash_to_tuple(mh: Multihash) -> tuple:
    """
    Convierte Multihash (Pydantic) a la tupla (bytes1, bytes1, bytes32)
    requerida por Solidity. Soporta digest en 0x... o Base58 (CID IPFS).
    """
    try:
        digest = mh.digest
        # Si digest es base58 (CID tipo Qm...), lo decodificamos completo
        if isinstance(digest, str) and digest.startswith("Qm"):
            decoded = base58.b58decode(digest)
            hf = decoded[0:1]
            hs = decoded[1:2]
            dg = decoded[2:34]  # digest real
        else:
            # Si digest ya es hex (0x...), usar hash_function y hash_size explícitos
            hf = bytes.fromhex(mh.hash_function.removeprefix("0x"))
            hs = bytes.fromhex(mh.hash_size.removeprefix("0x"))
            dg = bytes.fromhex(digest.removeprefix("0x"))

        # Validación de longitud
        if len(dg) != 32:
            raise ValueError(f"Digest debe tener 32 bytes, tiene {len(dg)}")

        return (hf, hs, dg)

    except Exception as e:
        logger.warning(f"Error en safe_multihash_to_tuple({mh}): {e}")
        return (b'\x00', b'\x00', b'\x00' * 32)

def multihash_to_base58(multihash_tuple: tuple) -> str:
    """
    Convierte un Multihash (bytes1, bytes1, bytes32) en un CID base58 (IPFS-style).

    """
    try:
        hf, hs, dg = multihash_tuple
        # Concatenar bytes: [hash_function][hash_size][digest]
        multihash_bytes = hf + hs + dg
        return base58.b58encode(multihash_bytes).decode("utf-8")
    except Exception as e:
        logger.warning(f"Error en multihash_to_base58: {e}")
        return None

def hash_text_to_multihash(text: str) -> Multihash:
    """Calcula el SHA256 y lo envuelve en el modelo Multihash."""
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    # 0x12 es SHA256, 0x20 es 32 bytes (256 bits)
    return Multihash(hash_function="0x12", hash_size="0x20", digest="0x" + h)



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
            digest=data.cid 
        )

        asertions_struct = []
        categoryIds = []
        for a in data.assertions:
            mh = hash_text_to_multihash(a.text)
            
            # Formato de aserción para el contrato (Multihash, array de validadores [vacío], categoryId)
            as_tuple = (safe_multihash_to_tuple(mh), tuple([]), a.categoryId) 
            asertions_struct.append(as_tuple)
            # categoryId ya es int gracias a Pydantic
            categoryIds.append(a.categoryId)

        logger.info(f"Preparando llamada a registerNew con ipfs:{hash_ipfs} hash_new:{hash_new}.")
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


@app.get("/blockchain/post/{post_id}")
def get_info_by_postid(post_id: int):
    try:
        # =====================================================
        # 1️⃣ Recuperar los campos planos del Post
        # =====================================================
        document, publisher, hash_new = contract.functions.getPostFlat(post_id).call()

        logger.info(f"Recuperados datos planos para postId {post_id}: "
                    f"publisher={publisher}, document={document}, hash_new={hash_new}")

        post_info = {
            "postId": post_id,
            "publisher": publisher,
            "document": multihash_to_base58(document),
            "hash_new": safe_hex(hash_new[2])
        }

        # =====================================================
        # 2️⃣ Recuperar aserciones y validaciones
        # =====================================================
        asertions_raw = contract.functions.getAsertionsWithValidations(post_id).call()
        logger.info(f"Recuperadas {len(asertions_raw)} aserciones para postId {post_id}.")
        asertions = []

        for idx_a, a in enumerate(asertions_raw):
            try:
                logger.info(f"Procesando aserción #{idx_a}: {a}")

                # a = (Multihash, ValidationView[], categoryId)
                hash_asertion_raw = a[0]
                category_id = a[2] if len(a) > 2 else a[1]
                raw_validations = a[1] if isinstance(a[1], (list, tuple)) else []

                hash_asertion = {
                    "hash_function": safe_hex(hash_asertion_raw[0]),
                    "hash_size": safe_hex(hash_asertion_raw[1]),
                    "digest": safe_hex(hash_asertion_raw[2]),
                }

                logger.info(f"Aserción #{idx_a} tiene {len(raw_validations)} validaciones.")
                validations = []

                for idx_v, v in enumerate(raw_validations):
                    try:
                        logger.info(f"  Validación #{idx_v} cruda: {v}, tipos: {[type(x) for x in v]}")

                        validator_addr = safe_hex(v[0])
                        domain_val = str(v[1])
                        reputation_val = v[2]
                        veredict_val = v[3]
                        hash_desc = v[4]

                        hash_description = {
                            "hash_function": safe_hex(hash_desc[0]),
                            "hash_size": safe_hex(hash_desc[1]),
                            "digest": safe_hex(hash_desc[2]),
                        }

                        validation_entry = {
                            "validatorAddress": validator_addr,
                            "domain": domain_val,
                            "reputation": reputation_val,
                            "veredict": veredict_val,
                            "hash_description": hash_description
                        }
                        validations.append(validation_entry)

                        logger.info(f"  ✅ Validación #{idx_v} procesada correctamente")

                    except Exception as inner_e:
                        logger.exception(f"⚠️ Error procesando validación #{idx_v} de la aserción #{idx_a}: {inner_e}")

                asertions.append({
                    "hash_asertion": hash_asertion,
                    "categoryId": category_id,
                    "validations": validations
                })

            except Exception as inner_a:
                logger.exception(f"⚠️ Error procesando aserción #{idx_a}: {inner_a}")

        post_info["asertions"] = asertions

        logger.info(f"✅ Post {post_id} procesado correctamente.")
        return {"result": True, "post": post_info}

    except Exception as e:
        logger.exception(f"❌ Error al recuperar post {post_id}: {e}")
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