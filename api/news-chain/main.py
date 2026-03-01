import os
import json
import uuid
import hashlib
import logging
import asyncio
import base58
import requests
import ast

from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv
from web3 import Web3
from web3.middleware import geth_poa_middleware

from aiokafka import AIOKafkaProducer

from common.blockchain import send_signed_tx, wait_for_receipt_blocking
from common.hash_utils import (
    safe_multihash_to_tuple,
    multihash_to_base58,
    multihash_to_base58_dict,
    hash_text_to_multihash,
    safe_hex,
)
from common.async_models import (
    Multihash,
    Assertion,
    RegisterBlockchainRequest,
    BlockchainRegisteredResponse,
    RegisterBlockchainPayload,
    RequestValidationPayload,
    ValidationCompletedPayload,
    RequestValidationRequest,
    ValidationCompletedResponse
)


from aiokafka import AIOKafkaConsumer



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
KAFKA_REQUEST_TOPIC = os.getenv("KAFKA_REQUEST_TOPIC", "request_validation")
KAFKA_RESPONSE_TOPIC = os.getenv("KAFKA_RESPONSE_TOPIC", "validation_completed")

IPFS_FASTAPI_URL = os.getenv("IPFS_FASTAPI_URL", "http://ipfs-fastapi:8060")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TrustNewsAPI")

# =========================================================
# Web3 / Contract
# =========================================================
w3 = Web3(Web3.HTTPProvider(RPC_URL))
w3.middleware_onion.inject(geth_poa_middleware, layer=0)

try:
    with open(CONTRACT_ABI_PATH) as f:
        artifact = json.load(f)
    abi = artifact["abi"]
    contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=abi)
    logger.info(f"Conectado a blockchain: {w3.is_connected()} - Account: {ACCOUNT_ADDRESS} - Contract: {CONTRACT_ADDRESS}")
except Exception as e:
    logger.error(f"Error cargando ABI o inicializando contrato: {e}")
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
def ipfs_get_text(cid: str) -> str:
    """
    Descarga texto desde IPFS vía tu gateway FastAPI.
    Añade logging detallado para diagnóstico.
    """
    try:
        url = f"{IPFS_FASTAPI_URL}/ipfs/{cid}"
        logger.info(f"🌍 IPFS GET → URL: {url}")

        r = requests.get(url, timeout=10)

        logger.info(
            f"📡 IPFS response | status={r.status_code} "
            f"content_length={len(r.content)} bytes"
        )

        # Si no es 200, logueamos body para diagnóstico
        if r.status_code != 200:
            logger.warning(
                f"⚠️ IPFS error response body: {r.text[:500]}"
            )

        r.raise_for_status()

        logger.info(
            f"✅ IPFS OK | CID={cid} | first_100_chars={r.text[:100]}"
        )

        return r.text

    except requests.exceptions.RequestException as e:
        logger.exception(f"❌ Error HTTP accediendo a IPFS | cid={cid} | {e}")
        return None

    except Exception as e:
        logger.exception(f"❌ Error inesperado en ipfs_get_text | cid={cid} | {e}")
        return None



def parse_registernew_event(receipt, data: RegisterBlockchainRequest) -> dict:
    class AttrDict(dict):
        def __getattr__(self, item):
            return self[item]

    if isinstance(receipt, dict):
        receipt = AttrDict(receipt)
    events = contract.events.RegisterNewResult().process_receipt(receipt)
    if not events:
        logger.warning("No se encontró evento RegisterNewResult; devolviendo info mínima.")
        return {
            "postId": None,
            "hash_text": "",
            "assertions": [],
            "tx_hash": getattr(receipt, "transactionHash", "0x")
        }
    event = events[0]
    postId = event['args']['postId']
    validator_addresses_by_asertion = event['args']['validatorAddressesByAsertion']
    asertions_output = []
    for i, a in enumerate(data.assertions):
        mh = hash_text_to_multihash(a.text)
        digest_hex = mh.digest[2:]
        addrs_raw = validator_addresses_by_asertion[i] if i < len(validator_addresses_by_asertion) else []
        addrs = [{"address": str(x)} for x in addrs_raw]
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
        "tx_hash": getattr(receipt, "transactionHash", "0x")
    }

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
            safe_multihash_to_tuple(hash_ipfs),
            tuple(categoryIds)
        )

        tx_hash = send_signed_tx(w3,func_call, ACCOUNT_ADDRESS, PRIVATE_KEY)
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
        document, publisher = contract.functions.getPostFlat(post_id).call()

        logger.info(f"Recuperados datos planos para postId {post_id}: "
                    f"publisher={publisher}, document={document}")

        post_info = {
            "postId": post_id,
            "publisher": publisher,
            "cid": multihash_to_base58(document)
        }
        logger.info(f"Post plano construido para postId {post_id}: {post_info}")

        # =====================================================
        # 2️⃣ Recuperar aserciones y validaciones
        # =====================================================
        asertions_raw = contract.functions.getAsertionsWithValidations(post_id).call()
        logger.info(f"RAW asertionsWithValidations: {asertions_raw}")
        logger.info(f"Recuperadas {len(asertions_raw)} aserciones para postId {post_id}.")
        asertions = []

        for idx_a, a in enumerate(asertions_raw):
            try:
                logger.info(f"Procesando aserción #{idx_a}: {a}")

                # a = (Multihash, ValidationView[], categoryId)
                category_id = a[0]
                raw_validations = a[1]


                logger.info(f"Aserción #{idx_a} tiene {len(raw_validations)} validaciones.")
                validations = []

                for idx_v, v in enumerate(raw_validations):
                    try:
                        logger.info(f"  Validación #{idx_v} cruda: {v}, tipos: {[type(x) for x in v]}")

                        validator_addr = safe_hex(v[0])
                        domain_val = str(v[1])
                        reputation_val = v[2]
                        veredict_val = v[3]
                        cid = v[4]

                        validation_entry = {
                            "validatorAddress": validator_addr,
                            "domain": domain_val,
                            "reputation": reputation_val,
                            "veredict": veredict_val,
                            "cid": multihash_to_base58(cid)
                        }
                        validations.append(validation_entry)

                        logger.info(f"  ✅ Validación #{idx_v} procesada correctamente")

                    except Exception as inner_e:
                        logger.exception(f"⚠️ Error procesando validación #{idx_v} de la aserción #{idx_a}: {inner_e}")

                asertions.append({
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
# AGENTE: LISTENER DE EVENTOS BLOCKCHAIN (VALIDATIONS)
# =========================================================

async def blockchain_event_listener():
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP)
    await producer.start()

    last_block = w3.eth.block_number
    logger.info(f"⛓️ Listener iniciado | desde bloque {last_block}")

    # Pre-cargamos eventos (más eficiente)
    validation_requested_event = contract.events.ValidationRequested()
    validation_submitted_event = contract.events.ValidationSubmitted()

    try:
        while True:
            latest = w3.eth.block_number

            if latest > last_block:
                for block in range(last_block + 1, latest + 1):
                    logger.info(f"📦 Procesando bloque {block}")

                    try:
                        block_data = w3.eth.get_block(block, full_transactions=True)
                    except Exception as e:
                        logger.exception(f"❌ Error leyendo bloque {block}: {e}")
                        continue

                    for tx in block_data.transactions:

                        # 🔥 FILTRO 1: solo tx hacia tu contrato
                        if not tx.to or tx.to.lower() != CONTRACT_ADDRESS.lower():
                            continue

                        tx_hash = safe_hex(tx.hash)

                        try:
                            receipt = w3.eth.get_transaction_receipt(tx.hash)
                        except Exception as e:
                            logger.exception(f"❌ Error obteniendo receipt {tx_hash}: {e}")
                            continue

                        # =====================================================
                        # Procesar logs individuales
                        # =====================================================
                        for log in receipt.logs:

                            # 🔥 FILTRO 2: solo logs de tu contrato
                            if log["address"].lower() != CONTRACT_ADDRESS.lower():
                                continue

                            # =================================================
                            # ValidationRequested
                            # =================================================
                            try:
                                logger.info(f"🔎 Intentando procesar log como ValidationRequested | tx={tx_hash}")
                                ev = validation_requested_event.process_log(log)
                                logger.info(f"✅ Log decodificado correctamente como ValidationRequested | tx={tx_hash}")

                                post_id = str(ev["args"]["postId"])
                                validator = str(ev["args"]["validator"])
                                assertion_index = int(ev["args"]["asertionIndex"])+1

                                logger.info(
                                    f"📨 ValidationRequested | "
                                    f"post={post_id} "
                                    f"assertion={assertion_index} "
                                    f"validator={validator} "
                                    f"tx={tx_hash}"
                                )

                                # ------------------------------------------------
                                # Obtener CID del documento
                                # ------------------------------------------------
                                raw_multihash = ev["args"]["postDocument"]
                                logger.info(f"🔗 Multihash recibido del contrato: {raw_multihash}")

                                cid_post = multihash_to_base58_dict(raw_multihash)
                                logger.info(f"🌍 CID convertido a base58: {cid_post}")

                                # ------------------------------------------------
                                # Descargar documento desde IPFS
                                # ------------------------------------------------
                                logger.info(f"📥 Descargando documento desde IPFS | cid={cid_post}")
                                ipfs_content = ipfs_get_text(cid_post)

                                if not ipfs_content:
                                    logger.warning(f"⚠️ Documento IPFS vacío o no encontrado | cid={cid_post}")
                                    continue

                                logger.info(f"📄 Documento IPFS descargado ({len(ipfs_content)} bytes)")

                                post_json = json.loads(ipfs_content)
                                logger.info("🧩 JSON parseado correctamente desde IPFS")
                                
                                content_obj = json.loads(post_json.get("content", "{}"))

                                # ------------------------------------------------
                                # Buscar assertion correspondiente
                                # ------------------------------------------------
                                assertions = content_obj.get("assertions", [])
                                logger.info(f"🔍 Total assertions encontradas en documento: {len(assertions)}")

                                assertion = next(
                                    (
                                        a for a in assertions
                                        if int(a.get("idAssertion", 0)) == assertion_index
                                    ),
                                    None,
                                )

                                if not assertion:
                                    logger.warning(
                                        f"⚠️ Assertion no encontrada en documento | "
                                        f"post={post_id} assertion={assertion_index}"
                                    )
                                    continue

                                logger.info(f"✅ Assertion localizada correctamente | assertion={assertion_index}")

                                text = assertion.get("text", "")
                                if not text:
                                    logger.warning(
                                        f"⚠️ Assertion sin texto | "
                                        f"post={post_id} assertion={assertion_index}"
                                    )
                                    continue

                                logger.info(
                                    f"📝 Texto assertion obtenido ({len(text)} chars) | "
                                    f"assertion={assertion_index}"
                                )

                                msg = RequestValidationRequest(
                                    order_id="",
                                    payload=RequestValidationPayload(
                                        postId=post_id,
                                        idValidator=validator,
                                        idAssertion=str(assertion_index),
                                        text=text,
                                    ),
                                )
                                
                                logger.info(
                                    f"📦 Mensaje Kafka construido | "
                                    f"topic={KAFKA_RESPONSE_TOPIC} "
                                    f"post={post_id} assertion={assertion_index}"
                                )
                                await producer.send_and_wait(
                                    KAFKA_RESPONSE_TOPIC,
                                    msg.model_dump_json().encode(),
                                )
                                
                                logger.info(
                                    f"🚀 Mensaje enviado a Kafka correctamente | "
                                    f"topic={KAFKA_RESPONSE_TOPIC} "
                                    f"post={post_id} assertion={assertion_index}"
                                )
                                continue  # Si se procesó como ValidationRequested, no intentamos ValidationSubmitted

                            except Exception as e:
                                if "event signature did not match" in str(e):
                                    pass  # No es este evento, continuar
                                else:
                                    logger.error(f"❌ Error procesando ValidationRequested: {str(e)}")

                            # =================================================
                            # ValidationSubmitted
                            # =================================================
                            try:
                                ev = validation_submitted_event.process_log(log)

                                post_id = str(ev["args"]["postId"])
                                validator = str(ev["args"]["validator"])
                                assertion_index = int(ev["args"]["asertionIndex"])+1

                                logger.info(
                                    f"📨 ValidationSubmitted | "
                                    f"post={post_id} "
                                    f"assertion={assertion_index} "
                                    f"validator={validator} "
                                    f"tx={tx_hash}"
                                )

                                #cid_post = multihash_to_base58_dict(
                                #    ev["args"]["postDocument"]
                                #)
                                cid_validation = multihash_to_base58_dict(
                                    ev["args"]["validationDocument"]
                                )

                                #post_json = json.loads(ipfs_get_text(cid_post))
                                raw_validation = json.loads(ipfs_get_text(cid_validation))

                                content_str = raw_validation.get("content", "")

                                # Si viene como b'...'
                                if content_str.startswith("b'") or content_str.startswith('b"'):
                                    # Convertir string representando bytes → bytes reales
                                    content_bytes = ast.literal_eval(content_str)
                                    content_str = content_bytes.decode("utf-8")

                                validation_json = json.loads(content_str)

                                msg = ValidationCompletedResponse(
                                    order_id="",
                                    payload=ValidationCompletedPayload(
                                        postId=post_id,
                                        idValidator=validator,
                                        idAssertion=str(assertion_index),
                                        approval=validation_json.get("estado"),
                                        text=validation_json.get("descripcion", ""),
                                        tx_hash=tx_hash,
                                        validator_alias=validation_json.get(
                                            "validator_alias", ""
                                        ),
                                    ),
                                )

                                await producer.send_and_wait(
                                    KAFKA_RESPONSE_TOPIC,
                                    msg.model_dump_json().encode(),
                                )

                            except Exception as e:
                                logger.error(f"❌ Error procesando ValidationSubmitted: {str(e)}")
                                pass

                last_block = latest

            await asyncio.sleep(2)

    finally:
        await producer.stop()
        logger.info("🛑 Kafka producer detenido")



async def consume_register_kafka():
    """Consume mensajes de Kafka para registrarlos en la Blockchain."""
    logger.info(f"Iniciando consumidor Kafka en {KAFKA_BOOTSTRAP}...")
    
    consumer = AIOKafkaConsumer(
        KAFKA_REQUEST_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id="trustnews-api-group",
        auto_offset_reset="earliest"
    )
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP)
    
    try:
        await consumer.start()
        await producer.start()
        logger.info(f"✅ Conectado a Kafka. Escuchando: {KAFKA_REQUEST_TOPIC}")

        async for msg in consumer:
            payload_msg = {}
            start_time = asyncio.get_event_loop().time()
            
            try:
                # 1. Parsear el mensaje JSON
                payload_msg = json.loads(msg.value.decode())
                order_id = payload_msg.get("order_id", str(uuid.uuid4()))
                
                logger.info(f"--- [START {order_id}] Mensaje recibido de Kafka ---")

                # 2. Validar el payload con el modelo Pydantic
                # Extraemos el contenido de 'payload' del mensaje Kafka
                inner_data = payload_msg.get("payload", {})
                publish_input = RegisterBlockchainPayload(**inner_data)
                
                # TRACE CORREGIDA: Usamos .text (que sí existe) en lugar de .title
                preview = publish_input.text[:40].replace('\n', ' ')
                logger.info(f"[{order_id}] Payload validado. Contenido: '{preview}...'")

                # 3. Paso 1: Enviar transacción a la Blockchain (Geth)
                logger.info(f"[{order_id}] ⛓️ Enviando transacción a la red Ethereum...")
                # Ejecutamos en un thread aparte porque web3.py suele ser bloqueante
                tx_info = await asyncio.to_thread(register_new, publish_input)
                tx_hash = tx_info["tx_hash"]
                logger.info(f"[{order_id}] 🚀 TX enviada con éxito. Hash: {tx_hash}")

                # 4. Paso 2: Esperar confirmación (Mining)
                logger.info(f"[{order_id}] ⏳ Esperando a que el minero confirme el bloque...")
                receipt = await asyncio.to_thread(wait_for_receipt_blocking, w3, tx_hash)
                
                if receipt.get('status') == 0:
                    logger.error(f"[{order_id}] ❌ ERROR: La transacción fue revertida (Status 0)")
                    continue

                logger.info(f"[{order_id}] ✅ TX minada en el bloque {receipt['blockNumber']}")

                # 5. Paso 3: Parsear eventos de la transacción
                result = await asyncio.to_thread(parse_registernew_event, receipt, publish_input)
                
                # 6. Crear el modelo de respuesta
                response_model = BlockchainRegisteredResponse(
                    action="blockchain_registered",
                    order_id=order_id,
                    payload=result
                )

                # 7. Paso 4: Publicar resultado en el tópico de respuesta
                logger.info(f"[{order_id}] 📤 Publicando resultado en {KAFKA_RESPONSE_TOPIC}...")
                await producer.send_and_wait(
                    KAFKA_RESPONSE_TOPIC, 
                    response_model.model_dump_json(exclude_none=True).encode("utf-8")
                )
                
                duration = round(asyncio.get_event_loop().time() - start_time, 2)
                logger.info(f"--- [END {order_id}] Ciclo completado en {duration}s ---")

            except ValidationError as ve:
                logger.error(f"[{payload_msg.get('order_id', 'N/A')}] ❌ Error de validación: {ve}")
            except Exception as e:
                # logger.exception nos dará el traceback completo en Stern
                logger.exception(f"[{payload_msg.get('order_id', 'N/A')}] 💥 Error inesperado: {e}")

    except Exception as e:
        logger.error(f"Fallo crítico en el loop del consumidor: {e}")
    finally:
        await consumer.stop()
        await producer.stop()
        logger.info("🔌 Conexiones de Kafka cerradas")
        
# =========================================================
# Startup
# =========================================================

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(blockchain_event_listener())
    logger.info("🚀 Agente de eventos blockchain iniciado")
        
    asyncio.create_task(consume_register_kafka())
    logger.info("Kafka consumer iniciado en background")