# fake_news_orchestrator_typed.py
import os
import uuid
import json
import asyncio
import logging
import hashlib
import requests
import httpx
import time # Añadir import de time
import lxml.html

from bs4 import BeautifulSoup
from typing import Any, Dict, List, Optional, Tuple
from common.hash_utils import hash_text_to_multihash,hash_text_to_hash
from fastapi import FastAPI, HTTPException, Query,APIRouter
from pydantic import BaseModel, ValidationError,HttpUrl
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from bson import ObjectId
from datetime import datetime, timedelta, timezone
from readability import Document
from loguru import logger
from common.veredicto import Validacion
from common.async_models import (
    GenerateAssertionsRequest,
    AssertionsGeneratedResponse,
    UploadIpfsRequest,
    IpfsUploadedResponse,
    RegisterBlockchainRequest,
    BlockchainRegisteredResponse,
    RequestValidationRequest,
    ValidationCompletedResponse,
    Document as DocModel,
    Metadata as MetadataModel,
    Assertion,
    AssertionExtended,
    ValidatorAddress,
    ConsistencyCheckResult,
    Multihash,
    ExtractedTextResponse,
    ExtractTextRequest,
    PreGeneratedAssertion,
    PublishWithAssertionsRequest
)

# =========================================================
# Cargar .env
# =========================================================
load_dotenv()

# =========================================================
# Config / Logging
# =========================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fake-news-orchestrator")

KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
KAFKA_USERNAME = os.getenv("KAFKA_USERNAME", "app")
KAFKA_PASSWORD = os.getenv("KAFKA_PASSWORD", "")
KAFKA_SECURITY_PROTOCOL = os.getenv("KAFKA_SECURITY_PROTOCOL", "SASL_PLAINTEXT")
KAFKA_MECHANISM = os.getenv("KAFKA_MECHANISM", "PLAIN")

TOPIC_REQUESTS_GENERATE = os.getenv("TOPIC_REQUESTS_GENERATE", "fake_news_requests_generate")
TOPIC_REQUESTS_IPFS = os.getenv("TOPIC_REQUESTS_IPFS", "fake_news_requests_ipfs")
TOPIC_REQUESTS_BLOCKCHAIN = os.getenv("TOPIC_REQUESTS_BLOCKCHAIN", "fake_news_requests_blockchain")
TOPIC_REQUESTS_VALIDATE = os.getenv("TOPIC_REQUESTS_VALIDATE", "fake_news_requests_validate")
TOPIC_RESPONSES = os.getenv("TOPIC_RESPONSES", "fake_news_responses")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb:27017")
MONGO_DBNAME = os.getenv("MONGO_DBNAME", "tfm")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "orders")

MAX_WORKERS = int(os.getenv("MAX_WORKERS", "1"))



IPFS_FASTAPI_URL = os.getenv("IPFS_FASTAPI_URL", "http://ipfs-fastapi:8060")
NEWS_CHAIN_URL = os.getenv("NEWS_CHAIN_URL", "http://news-chain:8073")


# =========================================================
# App & globals
# =========================================================
app = FastAPI(title="Fake News Orchestrator (Typed)")
producer: Optional[AIOKafkaProducer] = None
consumer: Optional[AIOKafkaConsumer] = None
mongo_client: Optional[AsyncIOMotorClient] = None
db = None
orders_collection = None
order_locks = {}

# ---------- Models ----------
class PublishRequest(BaseModel):
    text: str

class EventModel(BaseModel):
    action: str
    topic: str
    timestamp: str
    payload: dict

# =========================================================
# Helpers DB & Kafka security
# =========================================================
def kafka_security_kwargs():
    kwargs = {}
    if KAFKA_SECURITY_PROTOCOL:
        kwargs["security_protocol"] = KAFKA_SECURITY_PROTOCOL
    if KAFKA_MECHANISM:
        kwargs["sasl_mechanism"] = KAFKA_MECHANISM
    if KAFKA_USERNAME:
        kwargs["sasl_plain_username"] = KAFKA_USERNAME
    if KAFKA_PASSWORD:
        kwargs["sasl_plain_password"] = KAFKA_PASSWORD
    return kwargs

async def save_order_doc(order_doc: dict):
    global orders_collection
    await orders_collection.insert_one(order_doc)

async def update_order(order_id: str, update: dict):
    global orders_collection
    mongo_update = {}

    if "$push" in update:
        mongo_update["$push"] = update.pop("$push")

    if "$set" in update:
        mongo_update["$set"] = update.pop("$set")
    elif update:
        mongo_update["$set"] = update

    result = await orders_collection.update_one({"order_id": order_id}, mongo_update)
    if result.matched_count == 0:
        logger.error(f"Order {order_id} not found in MongoDB")

async def get_order_doc(order_id: str) -> Optional[dict]:
    doc = await orders_collection.find_one({"order_id": order_id})
    return doc

async def get_order_id_by_post_id(post_id: str) -> Optional[str]:
    doc = await orders_collection.find_one({"postId": post_id})
    return doc["order_id"] if doc else None
# ===========================
# Helpers para hashes
# ===========================
def ipfs_get_text(cid: str) -> str:
    url = f"{IPFS_FASTAPI_URL}/{cid}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.text

async def get_order_lock(order_id: str):
    if order_id not in order_locks:
        order_locks[order_id] = asyncio.Lock()
    return order_locks[order_id]

# =========================================================
# 🟢 Helpers para logging de eventos y validaciones
# =========================================================
async def log_event(order_id: str, action: str, topic: str, payload: dict):
    global db
    if not order_id:
        logger.warning(f"Evento con order_id vacío ignorado: action={action}, topic={topic}")
        return

    events_col = db["events"]
    
    # 🚨 CAMBIO CLAVE: Usar time.time() * 1000 para obtener la marca de tiempo UNIX absoluta en milisegundos
    current_ms_timestamp = int(time.time() * 1000) 
    
    event_doc = {
        "order_id": order_id,
        "action": action,
        "topic": topic,
        "timestamp": current_ms_timestamp, # Ahora es la marca de tiempo absoluta
        "payload": payload,
    }
    await events_col.insert_one(event_doc)
    logger.info(f"[{order_id}] 🟢 Evento '{action}' registrado en MongoDB ({topic}).")

async def log_validation(order_id: str, post_id: str, id_assertion: str, id_validator: str, approval: Validacion, tx_hash: str, payload: dict):
    global db
    if not order_id:
        logger.warning(f"Intento de log_validation sin order_id, ignorado.")
        return

    validations_col = db["validations"]
    val_doc = {
        "order_id": order_id,
        "postId": post_id,
        "idAssertion": id_assertion,
        "idValidator": id_validator,
        "approval": approval,
        "tx_hash": tx_hash,
        "payload": payload,
        "timestamp": asyncio.get_event_loop().time()
    }
    await validations_col.insert_one(val_doc)
    logger.info(f"[{order_id}] 🟢 Validación registrada en MongoDB (Assertion={id_assertion}, Validator={id_validator}).")

# ===========================
# manejo blockchain
# ===========================
async def handle_blockchain_request(order_id: str, text: str, cid: str, assertions: list):
    global producer

    try:
        # Construir la request blockchain REAL
        req = RegisterBlockchainRequest(
            action="register_blockchain",
            order_id=order_id,
            payload={
                "text": text,
                "cid": cid,
                "assertions": assertions,
                "publisher": "news-handler"
            }
        )

        # Enviar al topic real
        await producer.send_and_wait(
            TOPIC_REQUESTS_BLOCKCHAIN,
            req.model_dump_json().encode("utf-8")
        )

        logger.info(f"[{order_id}] Mensaje enviado al topic {TOPIC_REQUESTS_BLOCKCHAIN}")

        # Registrar evento
        await log_event(order_id, req.action, TOPIC_REQUESTS_BLOCKCHAIN, req.payload.model_dump())

    except ValidationError as e:
        logger.exception(f"Error validando register_blockchain request: {e}")


# =========================================================
# Procesador genérico de mensajes Kafka (reutilizable)
# =========================================================
ACTION_TO_MODEL_RESPONSE = {
    "assertions_generated": AssertionsGeneratedResponse,
    "ipfs_uploaded": IpfsUploadedResponse,
    "blockchain_registered": BlockchainRegisteredResponse,
    "validation_completed": ValidationCompletedResponse,
    "request_validation": RequestValidationRequest
}

async def process_kafka_message(data: dict):
    """
    data: dict ya decodificado del JSON del mensaje Kafka.
    Maneja: assertions_generated, ipfs_uploaded, blockchain_registered, validation_completed.
    """
    try:
        action = data.get("action")
        order_id = data.get("order_id")
        if not action :
            logger.warning("⚠️ Mensaje Kafka sin 'action' ")
            return

        # ============================================================
        # 🔁 Resolver order_id a partir de postId si no viene informado
        # ============================================================
        if not order_id or order_id == "":
            post_id = (
                data.get("payload", {}).get("postId")
                if isinstance(data.get("payload"), dict)
                else None
            )

            if not post_id:
                logger.warning(
                    "⚠️ Mensaje Kafka sin 'order_id' ni 'postId', ignorado."
                )
                return

            order_id = await get_order_id_by_post_id(str(post_id))

            if not order_id:
                logger.warning(
                    f"⚠️ No se pudo resolver order_id para postId={post_id}, ignorando evento."
                )
                return

            logger.info(
                f"🔁 order_id resuelto por postId | postId={post_id} → order_id={order_id}"
            )

        # 🔒 A partir de aquí order_id EXISTE siempre


        # Si existe un modelo de respuesta para esa acción, validamos
        model_cls = ACTION_TO_MODEL_RESPONSE.get(action)
        parsed = None
        if model_cls:
            try:
                parsed = model_cls(**data)
                logger.info(f"[{order_id}] ✅ Mensaje '{action}' validado con {model_cls.__name__}")
            except ValidationError as e:
                logger.error(f"[{order_id}] ❌ Error de validación para '{action}': {e}")
                # Log evento de error (payload original)
                await log_event(order_id, f"{action}_invalid", TOPIC_RESPONSES, {"error": str(e), "raw": data})
                return
        else:
            # Si no existe modelo para la acción entrante, registrar y continuar
            logger.warning(f"[{order_id}] ⚠️ Acción entrante no mapeada a modelo: {action}")
            await log_event(order_id, f"{action}_unknown", TOPIC_RESPONSES, data)
            return

        # Registrar evento de entrada
        await log_event(order_id, action, TOPIC_RESPONSES, parsed.payload.model_dump())

        logger.info(f"📨 [{order_id}] Procesando acción '{action}'...")

        # ================================================================
        # 1️⃣ assertions_generated
        # ================================================================
        if action == "assertions_generated":
            # parsed es AssertionsGeneratedResponse
            doc = await get_order_doc(order_id)
            if not doc:
                logger.warning(f"[{order_id}] ⚠️ Documento no encontrado en DB.")
                return

            assertions = parsed.payload.assertions or []
            if not assertions:
                logger.warning(f"[{order_id}] ⚠️ Payload vacío de aserciones.")
                return

            # Convert assertions (Pydantic Assertion -> dict)
            assertions_list = [a.model_dump() if isinstance(a, Assertion) else a for a in assertions]

            # Crear documento tipado (usamos DocModel/MetadataModel para validar si quieres)
            try:
                metadata = MetadataModel(generated_by="news-handler", timestamp=asyncio.get_event_loop().time())
                document_model = DocModel(
                    order_id=order_id,
                    text=doc.get("text", ""),
                    assertions=assertions_list,
                    metadata=metadata
                )
                document = document_model.model_dump()
            except ValidationError as e:
                logger.exception(f"[{order_id}] Error validando Document model: {e}")
                # Caemos de forma tolerante: construimos document crudo
                document = {
                    "order_id": order_id,
                    "text": doc.get("text", ""),
                    "assertions": assertions_list,
                    "metadata": {"generated_by": "news-handler", "timestamp": asyncio.get_event_loop().time()}
                }

            await update_order(order_id, {
                "assertions": assertions_list,
                "document": document,
                "status": "DOCUMENT_CREATED"
            })
            logger.info(f"[{order_id}] 📄 Documento y aserciones guardadas en MongoDB.")

            # Enviar upload_ipfs request usando UploadIpfsRequest
            try:
                upload_req = UploadIpfsRequest(
                    action="upload_ipfs",
                    order_id=order_id,
                    payload={"document": document}
                )
                await producer.send_and_wait(TOPIC_REQUESTS_IPFS, upload_req.model_dump_json().encode("utf-8"))
                logger.info(f"[{order_id}] 🌐 Documento enviado al servicio IPFS ({TOPIC_REQUESTS_IPFS}).")
                await log_event(order_id, upload_req.action, TOPIC_REQUESTS_IPFS, upload_req.payload.model_dump())
            except ValidationError as e:
                logger.exception(f"[{order_id}] Error validando upload_ipfs request: {e}")

            await update_order(order_id, {"status": "IPFS_PENDING"})

        # ================================================================
        # 2️⃣ ipfs_uploaded
        # ================================================================
        elif action == "ipfs_uploaded":
            cid = parsed.payload.cid
            if not cid:
                logger.warning(f"[{order_id}] ⚠️ Falta 'cid' en payload.")
                return

            doc = await get_order_doc(order_id)
            if not doc:
                logger.warning(f"[{order_id}] ⚠️ Documento no encontrado para IPFS update.")
                return

            await update_order(order_id, {
                "cid": cid,
                "status": "IPFS_UPLOADED"
            })
            logger.info(f"[{order_id}] ✅ IPFS subido con CID={cid}")

            # Generar request a blockchain (emulado o real)
            await handle_blockchain_request(order_id, doc.get("text", ""), cid, doc.get("assertions", []))
            await update_order(order_id, {"status": "BLOCKCHAIN_PENDING"})
            logger.info(f"[{order_id}] ⛓️ Petición de registro blockchain enviada (emulada o real según configuración).")

        # ================================================================
        # 3️⃣ blockchain_registered
        # ================================================================
        elif action == "blockchain_registered":
            payload = parsed.payload.model_dump()
            postId = payload.get("postId")
            tx_hash = payload.get("tx_hash")
            hash_text = payload.get("hash_text")
            assertions_payload = payload.get("assertions", [])

            if not assertions_payload:
                logger.warning(f"[{order_id}] ⚠️ blockchain_registered sin assertions, abortando.")
                return

            doc = await get_order_doc(order_id)
            if not doc:
                logger.warning(f"[{order_id}] ❌ Documento no encontrado en MongoDB.")
                return

            validators_info = []
            for i, a in enumerate(assertions_payload):
                # a puede venir validado por Pydantic como dicts
                assertion_id = a.get("idAssertion")
                assertion_text = a.get("text")
                category_id = int(a.get("categoryId", 0))


                raw_validators = a.get("validatorAddresses") 
                validator_addresses = set()
                for v in raw_validators:
                    if isinstance(v, dict):
                        addr = v.get("address")
                    else:
                        addr = v
                    if addr:
                        validator_addresses.add(str(addr))
                validator_addresses = list(validator_addresses)

                logger.info(f"[{order_id}] 🧩 Aserción #{i+1}: id={assertion_id}, texto='{(assertion_text or '')[:70]}...', categoria={category_id}")
                logger.debug(f"[{order_id}] ⚙️ Validadores únicos: {validator_addresses}")

                validators_info.append({
                    "idAssertion": assertion_id,
                    "validatorAddresses": validator_addresses,
                    "text": assertion_text,
                    "categoryId": category_id
                })

            await update_order(order_id, {
                "validators": validators_info,
                "validators_pending": sum(len(v["validatorAddresses"]) for v in validators_info),
                "status": "VALIDATION_PENDING",
                "postId": postId,
                "tx_hash": tx_hash,
                "hash_text": hash_text
            })

            logger.info(f"[{order_id}] ✅ Validadores guardados en MongoDB ({len(validators_info)} aserciones).")

        # ================================================================
        # 4 request_validation  
        # ================================================================
        elif action == "request_validation":
            payload = parsed.payload.model_dump()

            postId = str(payload.get("postId"))
            id_val = payload.get("idValidator")
            id_assert = str(payload.get("idAssertion"))
            text_assert = payload.get("text", "")
            context = payload.get("context")

            logger.info(
                f"[{order_id}] 📥 RequestValidation recibida -> "
                f"postId={postId}, assertion={id_assert}, validator={id_val}"
            )

            if not id_val or not id_assert:
                logger.warning(f"[{order_id}] ⚠️ request_validation sin idValidator o idAssertion.")
                return

            lock = await get_order_lock(order_id)
            async with lock:
                doc = await get_order_doc(order_id)
                if not doc:
                    logger.warning(f"[{order_id}] ❌ Documento no encontrado para request_validation.")
                    return

                validators_cfg = doc.get("validators", [])
                assertion_cfg = None

                for v in validators_cfg:
                    if str(v.get("idAssertion")) == id_assert:
                        assertion_cfg = v
                        break

                if not assertion_cfg:
                    logger.warning(
                        f"[{order_id}] ⚠️ request_validation para aserción desconocida: {id_assert}"
                    )
                    return

                validator_addresses = set(assertion_cfg.get("validatorAddresses", []))
                if id_val not in validator_addresses:
                    logger.warning(
                        f"[{order_id}] ⚠️ Validator {id_val} no esperado para aserción {id_assert}"
                    )
                    return

                # Registrar request recibida (auditoría / trazabilidad)
                # await log_event(
                #     order_id,
                #     "request_validation_received",
                #     TOPIC_RESPONSES,
                #     payload
                # )

                # Inicializar estructura de validaciones si no existe
                validations = doc.get("validations", {})
                if id_assert not in validations:
                    validations[id_assert] = {}

                # Si ya hay validación hecha, ignoramos
                if id_val in validations[id_assert]:
                    logger.info(
                        f"[{order_id}] ⚠️ request_validation duplicada ignorada "
                        f"(Assertion={id_assert}, Validator={id_val})"
                    )
                    return

                # Guardar request como pendiente (opcional pero útil)
                pending_requests = doc.get("validation_requests", {})
                pending_requests.setdefault(id_assert, set())
                pending_requests[id_assert].add(id_val)

                # Persistir
                await update_order(order_id, {
                    "$set": {
                        "validation_requests": {
                            k: list(v) for k, v in pending_requests.items()
                        }
                    }
                })

                logger.info(
                    f"[{order_id}] 🧾 RequestValidation registrada "
                    f"(Assertion={id_assert}, Validator={id_val})"
                )

        # ================================================================
        # 5 validation_completed
        # ================================================================
        elif action == "validation_completed":
            payload = parsed.payload.model_dump()
            postId = str(payload.get("postId", ""))
            id_val = payload.get("idValidator")
            id_assert = str(payload.get("idAssertion"))
            approval_raw = payload.get("approval")
            try:
                status_val = Validacion(approval_raw)
            except Exception:
                status_val = Validacion(approval_raw) if approval_raw else None

            assertion_text = payload.get("text", "")
            tx_hash = payload.get("tx_hash", "")
            validator_alias = payload.get("validator_alias", "")

            logger.info(f"[{order_id}] 🧩 Validación recibida -> postId={postId}, Assertion={id_assert}, Validator={id_val}, Approval={status_val}")

            if not id_val or not id_assert:
                logger.warning(f"[{order_id}] ⚠️ validation_completed sin idValidator o idAssertion, ignorando.")
                return

            lock = await get_order_lock(order_id)
            async with lock:
                doc = await get_order_doc(order_id)
                if not doc:
                    logger.warning(f"[{order_id}] ❌ Documento no encontrado para validation_completed.")
                    return

                validations = doc.get("validations", {})
                if id_assert not in validations:
                    validations[id_assert] = {}

                already_done = id_val in validations[id_assert]
                if already_done:
                    logger.info(f"[{order_id}] ⚠️ Validación duplicada ignorada (Assertion={id_assert}, Validator={id_val}).")
                    return

                validations[id_assert][id_val] = {
                    "approval": status_val,
                    "text": assertion_text,
                    "tx_hash": tx_hash,
                    "validator_alias": validator_alias
                }

                await update_order(order_id, {"$set": {"validations": validations}})
                logger.info(f"[{order_id}] ✅ Validación registrada Assertion={id_assert}, Validator={id_val}.")

                # Registrar validación en colección 'validations'
                await log_validation(order_id, postId, id_assert, id_val, status_val, tx_hash, payload)

                validators_cfg = doc.get("validators", [])
                total_pending = 0
                for v in validators_cfg:
                    aid = str(v["idAssertion"])
                    expected = set(v["validatorAddresses"])
                    done = set(validations.get(aid, {}).keys())
                    pending = expected - done
                    total_pending += len(pending)
                    logger.info(
                        f"[{order_id}] 🧮 Assertion {aid}: {len(done)}/{len(expected)} completadas. Pendientes: {list(pending) if pending else 'NINGUNO'}"
                    )

                await update_order(order_id, {"$set": {"validators_pending": total_pending}})
                logger.info(f"[{order_id}] 📊 Validadores pendientes totales: {total_pending}")

                if total_pending == 0:
                    await update_order(order_id, {"$set": {"status": "VALIDATED"}})
                    logger.info(f"[{order_id}] 🎯 Todas las validaciones completadas. Noticia VALIDADA.")
                else:
                    logger.info(f"[{order_id}] 🕓 Aún quedan {total_pending} validaciones pendientes.")

        else:
            logger.warning(f"[{order_id}] ⚠️ Acción desconocida recibida: {action}")

    except Exception as e:
        logger.exception(f"❌ Error procesando mensaje Kafka: {e}")

# =========================================================
# Kafka consumer loop
# =========================================================
async def consume_responses_loop():
    global consumer
    logger.info("Starting consume_responses_loop (listening to responses)")

    consumer = AIOKafkaConsumer(
        TOPIC_RESPONSES,
        bootstrap_servers=KAFKA_BROKER,
        group_id="fake-news-orchestrator-group",
        auto_offset_reset="earliest",
        **kafka_security_kwargs()
    )
    await consumer.start()
    logger.info(f"Kafka consumer subscribed to {TOPIC_RESPONSES}")

    try:
        async for msg in consumer:
            try:
                raw = msg.value.decode("utf-8")
                data = json.loads(raw)
                await process_kafka_message(data)
            except Exception as e:
                logger.exception("Error processing Kafka message: %s", e)
    except Exception as e:
        logger.exception("Fatal error in consume_responses_loop: %s", e)
    finally:
        await consumer.stop()
        
# =========================================================
# Sub-Endpoints/Funciones Auxiliares de Consistencia
# =========================================================




async def _check_order_retrieval(order_id: str) -> Tuple[List[ConsistencyCheckResult], Optional[Dict[str, Any]]]:
    """Prueba 1: Recuperar Order y validar el OrderId llamando directamente a get_order."""
    logger.info(f"-> INICIO: Chequeo de recuperación de Order para ID: {order_id}")
    results: List[ConsistencyCheckResult] = []
    order_data = None
    
    try:
        # 1. Llamada directa a la función get_order con 'await'
        order_data = await get_order(order_id)
        
        # 2. Validación del OrderId (si get_order devuelve datos)
        if order_data and order_data.get("order_id") == order_id:
            results.append(ConsistencyCheckResult(
                test="Recuperando Order por OrderId",
                toCompare="Valor buscado: " + order_id,
                compared="Valor Recuperado: " + order_data.get("order_id"),
                result="OK"
            ))
            logger.info(f"<- FIN: Order Retrieval OK. Order ID: {order_id}")
        else:
            details = "Order ID recuperado no coincide o el cuerpo está vacío/formato incorrecto."
            results.append(ConsistencyCheckResult(
                test="Recuperando Order con OrderId",
                toCompare=order_id,
                compared=order_data.get("order_id") if order_data else "N/A",
                result="KO",
                details=details
            ))
            logger.error(f"<- FIN: Order Retrieval KO. Detalles: {details}")

    except HTTPException as e:
        # 3. Captura la excepción de FastAPI (404 Not Found) lanzada por get_order
        details = f"Error {e.status_code} al llamar a get_order: {e.detail}"
        results.append(ConsistencyCheckResult(
            test="Recuperando Order con OrderId",
            toCompare=order_id,
            result="KO",
            details=details
        ))
        logger.error(f"<- FIN: Order Retrieval KO. {details}")
    except Exception as e:
        # 4. Captura cualquier otra excepción inesperada
        details = f"Error inesperado: {str(e)}"
        results.append(ConsistencyCheckResult(
            test="Recuperando Order con OrderId",
            toCompare=order_id,
            result="KO",
            details=details
        ))
        logger.error(f"<- FIN: Order Retrieval KO. {details}")
        
    return results, order_data

# --------------------------------------------------------------------------------

async def _check_ipfs_consistency(client: httpx.AsyncClient, order_data: Dict[str, Any]) -> Tuple[List[ConsistencyCheckResult], Optional[Dict[str, Any]]]:
    """Pruebas 2, 3, 4, 5: Comparar Order con el contenido de IPFS."""
    cid = order_data.get("cid")
    logger.info(f"-> INICIO: Chequeo de consistencia IPFS para CID: {cid}")
    results: List[ConsistencyCheckResult] = []
    ipfs_content = None
    order_text = order_data.get("text", "")
    order_assertions = order_data.get("assertions", [])

    if not cid:
        logger.warning("-> FIN: Chequeo IPFS SKIPPED. CID no disponible en Order.")
        results.append(ConsistencyCheckResult(test="Recuperando documento ipfs", result="SKIP", details="CID no disponible en Order."))
        return results, None

    # --- Prueba 2: Recuperar documento ipfs ---
    try:
        ipfs_url = f"{IPFS_FASTAPI_URL}/ipfs/{cid}"
        logger.info(f"--- Prueba 2: Llamando a IPFS en {ipfs_url}")
        response = await client.get(ipfs_url)
        response.raise_for_status()
        ipfs_response = response.json()
        ipfs_content = json.loads(ipfs_response.get("content", "{}"))
        
        test_ok = ipfs_response.get("cid") == cid
        results.append(ConsistencyCheckResult(
            test=f"Recuperando documento de ipfs por cid ",
            toCompare="Orden:"+cid,
            compared="Ipfs:"+ipfs_response.get("cid"),
            result="OK" if test_ok else "KO",
            details=None if test_ok else "CID devuelto no coincide."
        ))
        logger.info(f"--- Prueba 2 (IPFS Retrieval): {'OK' if test_ok else 'KO'}")

    except httpx.HTTPStatusError as e:
        details = f"HTTP Error: {e.response.status_code}"
        results.append(ConsistencyCheckResult(test=f"Recuperando documento ipfs con cid {cid}", toCompare=cid, result="KO", details=details))
        logger.error(f"--- Prueba 2 (IPFS Retrieval) KO. {details}")
        return results, None
    except Exception as e:
        details = f"Error inesperado: {str(e)}"
        results.append(ConsistencyCheckResult(test=f"Recuperando documento ipfs con cid {cid}", toCompare=cid, result="KO", details=details))
        logger.error(f"--- Prueba 2 (IPFS Retrieval) KO. {details}")
        return results, None
    
    if not ipfs_content:
        logger.warning("--- Pruebas 3-5 SKIPPED. Contenido IPFS vacío o no parseable.")
        results.append(ConsistencyCheckResult(test="Comparación de texto y aserciones", result="SKIP", details="Contenido IPFS vacío o no parseable."))
        return results, ipfs_content
        
    ipfs_text = ipfs_content.get("text", "")
    ipfs_assertions = ipfs_content.get("assertions", [])
    
    # --- Prueba 3: Comparar texto de la noticia ---
    text_ok = order_text == ipfs_text
    results.append(ConsistencyCheckResult(
        test="Comparando texto de la notícia",
        toCompare="Order Text:"+order_text,
        compared="Ipfs Text:"+ipfs_text,
        result="OK" if text_ok else "KO",
        details=None if text_ok else f"Longitudes: Order={len(order_text)}, IPFS={len(ipfs_text)}. Verifique el contenido."
    ))
    logger.info(f"--- Prueba 3 (Texto): {'OK' if text_ok else 'KO'}")

    # --- Prueba 4: Comparar num de assertions entre order e ipfs ---
    len_assertions_order = len(order_assertions)
    len_assertions_ipfs = len(ipfs_assertions)
    len_assertions_ok = len_assertions_order == len_assertions_ipfs
    results.append(ConsistencyCheckResult(
        test="Comparando num de assertions entre orden e ipfs",
        toCompare="# Orden:"+str(len_assertions_order),
        compared="#Ipfs:"+str(len_assertions_ipfs),
        result="OK" if len_assertions_ok else "KO"
    ))
    logger.info(f"--- Prueba 4 (Num Assertions): {'OK' if len_assertions_ok else 'KO'}")
    
    # --- Prueba 5: Comparar assertions de la noticia (solo si el número es OK) ---
    if len_assertions_ok and len_assertions_order > 0:
        for idx, a_order in enumerate(order_assertions):
            a_ipfs = ipfs_assertions[idx]
            assertion_id = a_order.get("idAssertion", f"Idx {idx}")
            text_a_order = a_order.get("text")
            text_a_ipfs = a_ipfs.get("text")
            assertion_ok = text_a_order == text_a_ipfs
            
            results.append(ConsistencyCheckResult(
                test=f"Comparando assertion num {assertion_id} (Texto)",
                toCompare="Orden:"+text_a_order,
                compared="Ipfs:"+text_a_ipfs,
                result="OK" if assertion_ok else "KO"
            ))
            logger.info(f"--- Prueba 5 (Assertion {assertion_id} Texto): {'OK' if assertion_ok else 'KO'}")
    elif not len_assertions_ok and len_assertions_order > 0:
        logger.warning("--- Prueba 5 SKIPPED. Número de aserciones no coincide.")
        results.append(ConsistencyCheckResult(
            test="Comparando assertions numéricas (texto)", 
            result="SKIP", 
            details="Se saltó la prueba porque el número de aserciones no coincidía."
        ))

    logger.info(f"<- FIN: Chequeo de consistencia IPFS para CID: {cid}")
    return results, ipfs_content

# --------------------------------------------------------------------------------

async def _check_blockchain_consistency(client: httpx.AsyncClient, order_data: Dict[str, Any]) -> Tuple[List[ConsistencyCheckResult], Optional[Dict[str, Any]]]:
    """Pruebas 6, 7, 8: Comparar Order con el Post de la Blockchain."""
    postId = order_data.get("postId")
    logger.info(f"-> INICIO: Chequeo de consistencia Blockchain para PostID: {postId}")
    results: List[ConsistencyCheckResult] = []
    post_data = None
    order_cid = order_data.get("cid")
    order_hash_text = order_data.get("hash_text")
    order_assertions = order_data.get("assertions", [])

    if not postId:
         logger.warning("-> FIN: Chequeo Blockchain SKIPPED. postId no disponible en Order.")
         results.append(ConsistencyCheckResult(test="Recuperar Post de Ethereum", result="SKIP", details="postId no disponible en Order."))
         return results, None
         
    # --- Prueba 6: Recuperar Post de Ethereum ---
    try:
        post_url = f"{NEWS_CHAIN_URL}/blockchain/post/{postId}"
        logger.info(f"--- Prueba 6: Llamando a Blockchain en {post_url}")
        response = await client.get(post_url)
        response.raise_for_status()
        post_response = response.json()
        
        is_success = post_response.get("result") is True and post_response.get("post")
        if is_success:
            post_data = post_response.get("post")
            results.append(ConsistencyCheckResult(
                test=f"Recuperando post de Ethereum a traves del smart contract con postId",
                toCompare="PostID buscado:"+str(postId),
                compared="PostID recuperado Ethereum:"+str(post_data.get("postId")),
                result="OK"
            ))
            logger.info(f"--- Prueba 6 (Blockchain Retrieval): OK")
        else:
            details = "Respuesta de Blockchain no exitosa o sin datos de 'post'."
            results.append(ConsistencyCheckResult(
                test=f"Recuperando post de Ethereum a traves del smart contract con postId: {postId}",
                toCompare=str(postId),
                result="KO",
                details=details
            ))
            logger.error(f"--- Prueba 6 (Blockchain Retrieval): KO. {details}")
            return results, None
            
    except httpx.HTTPStatusError as e:
        details = f"HTTP Error: {e.response.status_code}"
        results.append(ConsistencyCheckResult(test=f"Recuperando post de Ethereum... {postId}", result="KO", details=details))
        logger.error(f"--- Prueba 6 (Blockchain Retrieval): KO. {details}")
        return results, None
    except Exception as e:
        details = f"Error inesperado: {str(e)}"
        results.append(ConsistencyCheckResult(test=f"Recuperando post de Ethereum... {postId}", result="KO", details=details))
        logger.error(f"--- Prueba 6 (Blockchain Retrieval): KO. {details}")
        return results, None

    # --- Prueba 7: Comparar CID de Order con Post.document ---
    post_cid = post_data.get("document")
    cid_post_ok = order_cid == post_cid
    results.append(ConsistencyCheckResult(
        test="Comparando cid de Order con cid de blockchain",
        toCompare="Orden:"+order_cid,
        compared="Ethereum:"+post_cid,
        result="OK" if cid_post_ok else "KO"
    ))
    logger.info(f"--- Prueba 7 (CID): {'OK' if cid_post_ok else 'KO'}")

    # --- Prueba 8: Comparar hash_text de Order con Post.hash_new ---
    hash_text_ok = order_hash_text == post_data.get("hash_new")
    results.append(ConsistencyCheckResult(
        test='Comparando hash de "text" de Order con hash de blockchain',
        toCompare="Orden:"+order_hash_text,
        compared="Ethereum:"+ipfs_get_text(post_data.get("hash_new")),
        result="OK" if hash_text_ok else "KO"
    ))
    logger.info(f"--- Prueba 8 (Hash Text): {'OK' if hash_text_ok else 'KO'}")
    
    # --- Prueba 9: Comparar num de assertions entre order y post ---
    post_assertions = post_data.get("asertions", [])
    len_assertions_order = len(order_assertions)
    len_assertions_post = len(post_assertions)
    len_assertions_ok = len_assertions_order == len_assertions_post
    results.append(ConsistencyCheckResult(
        test="Comparando num de assertions entre orden y ethereum",
        toCompare="# Orden:"+str(len_assertions_order),
        compared="# Ethereum:"+str(len_assertions_post),
        result="OK" if len_assertions_ok else "KO"
    ))
    logger.info(f"--- Prueba 9 (Num Assertions): {'OK' if len_assertions_ok else 'KO'}")

    logger.info(f"<- FIN: Chequeo de consistencia Blockchain para PostID: {postId}")
    return results, post_data

# --------------------------------------------------------------------------------

def _check_assertion_details_consistency(order_data: Dict[str, Any], post_data: Dict[str, Any]) -> List[ConsistencyCheckResult]:
    """Pruebas 10 y 11: Comparar hashes de aserciones y cardinalidad de validaciones."""
    logger.info("-> INICIO: Chequeo de detalles de aserciones (Blockchain)")
    results: List[ConsistencyCheckResult] = []
    order_assertions = order_data.get("assertions", [])
    post_assertions = post_data.get("asertions", [])
    len_assertions_ok = len(order_assertions) == len(post_assertions)
    
    if not len_assertions_ok:
        logger.warning("-> FIN: Detalles de aserciones SKIPPED. Número de aserciones no coincide.")
        results.append(ConsistencyCheckResult(
            test="Comparación de detalles de aserciones", 
            result="SKIP", 
            details="Se saltó la prueba porque el número de aserciones no coincidía."
        ))
        return results
        
    for idx, a_order in enumerate(order_assertions):
        a_post = post_assertions[idx]
        
        assertion_id = a_order.get("idAssertion", f"Idx {idx}")
        order_text = a_order.get("text", "")
        logger.info(f"--- Calculando digest para idAssertion {assertion_id}: {order_text}")
        
        # --- Prueba 10: Comparar hash de text de assertion con hash de post ---
        calculated_digest = hash_text_to_hash(order_text).lower().removeprefix("0x")
        
        post_digest = a_post.get("cid", {}).get("digest", "").lower().removeprefix("0x")
        hash_ok = calculated_digest == post_digest
        
        results.append(ConsistencyCheckResult(
            test=f'Comparando hash de "assertions"."text" (Orden vs Ethereum) para idAssertion {assertion_id}',
            toCompare="Orden:"+"0x" + calculated_digest,
            compared="Ethereum:"+"0x" + ipfs_get_text(post_digest),
            result="OK" if hash_ok else "KO",
            details=None if hash_ok else "El hash calculado del texto de la aserción no coincide con el digest en Blockchain."
        ))
        logger.info(f"--- Prueba 10 (Hash Assertions {assertion_id}): {'OK' if hash_ok else 'KO'}")

        # --- Prueba 11: Comparar num de validations entre order y post ---
        order_validations_map = order_data.get("validations", {}).get(assertion_id, {})
        post_validations_list = a_post.get("validations", [])
        
        len_validations_order = len(order_validations_map)
        len_validations_post = len(post_validations_list)
        len_validations_ok = len_validations_order == len_validations_post
        
        results.append(ConsistencyCheckResult(
            test=f"Comparando num de validaciones para la asercion para idAssertion {assertion_id}",
            toCompare="# Orden:"+str(len_validations_order),
            compared="# Ethereum:"+str(len_validations_post),
            result="OK" if len_validations_ok else "KO"
        ))
        logger.info(f"--- Prueba 11 (Num Validations {assertion_id}): {'OK' if len_validations_ok else 'KO'}")
        
    logger.info("<- FIN: Chequeo de detalles de aserciones (Blockchain)")
    return results

# --------------------------------------------------------------------------------

def _check_validation_details_consistency(order_data: Dict[str, Any], post_data: Dict[str, Any]) -> List[ConsistencyCheckResult]:
    """Pruebas 12, 13, 14: Comparar detalles de validación (address, approval/veredict, hash_text)."""
    logger.info("-> INICIO: Chequeo de detalles de validación (Blockchain)")
    results: List[ConsistencyCheckResult] = []
    order_assertions = order_data.get("assertions", [])
    post_assertions = post_data.get("asertions", [])
    
    if len(order_assertions) != len(post_assertions):
        logger.warning("-> FIN: Detalles de validación SKIPPED. Número de aserciones no coincide.")
        results.append(ConsistencyCheckResult(
            test="Comparación de detalles de validación", 
            result="SKIP", 
            details="Se saltó la prueba porque el número de aserciones no coincidía entre Order y Blockchain."
        ))
        return results

    for idx, a_order in enumerate(order_assertions):
        a_post = post_assertions[idx]
        assertion_id = a_order.get("idAssertion", f"Idx {idx}")

        order_validations_map = order_data.get("validations", {}).get(assertion_id, {})
        post_validations_list = a_post.get("validations", [])
        
        # Saltarse si el número de validaciones no coincide (se chequeó en Prueba 11)
        if len(order_validations_map) != len(post_validations_list):
             logger.warning(f"--- Detalles de validación para {assertion_id} SKIPPED. Cardinalidad de validaciones KO.")
             results.append(ConsistencyCheckResult(
                 test=f"Detalles de validación para idAssertion {assertion_id}", 
                 result="SKIP", 
                 details=f"Se saltó la prueba porque el número de validaciones no coincidía para {assertion_id}."
             ))
             continue
        
        post_validations_by_address = {v.get("validatorAddress", "").lower(): v for v in post_validations_list}
        
        for validator_address, v_order in order_validations_map.items():
            validator_address_lower = validator_address.lower()
            v_post = post_validations_by_address.get(validator_address_lower)
            
            if not v_post:
                results.append(ConsistencyCheckResult(
                    test=f"Comparando address de validators (Order vs Blockchain) para idAssertion {assertion_id}",
                    toCompare=validator_address,
                    compared="N/A",
                    result="KO",
                    details="Validador de la Order no encontrado en las validaciones de Blockchain."
                ))
                logger.error(f"--- Prueba 12 (Address {assertion_id} {validator_address}): KO (No encontrado)")
                continue

            # --- Prueba 12: Comparar address de validator ---
            address_ok = validator_address_lower == v_post.get("validatorAddress", "").lower()
            results.append(ConsistencyCheckResult(
                test=f"Comparando address de validators entre order y ethereum para idAssertion {assertion_id}",
                toCompare="Orden:"+validator_address,
                compared="Ethereum:"+v_post.get("validatorAddress"),
                result="OK" if address_ok else "KO"
            ))
            logger.info(f"--- Prueba 12 (Address {assertion_id} {validator_address}): {'OK' if address_ok else 'KO'}")

            # --- Prueba 13: Comparar resultado de validation (approval vs veredict) ---
            order_approval = v_order.get("approval")
            post_veredict = v_post.get("veredict")
            approval_ok = order_approval == post_veredict
            results.append(ConsistencyCheckResult(
                test=f"Comparando resultado de validaciones (approval/veredict) para idAssertion {assertion_id} y validador {validator_address}",
                toCompare="Orden:"+str(order_approval),
                compared="Ethereum:"+str(post_veredict),
                result="OK" if approval_ok else "KO",
                details=None if approval_ok else f"Order: {order_approval}, Blockchain: {post_veredict}"
            ))
            logger.info(f"--- Prueba 13 (Veredict {assertion_id} {validator_address}): {'OK' if approval_ok else 'KO'}")

            # --- Prueba 14: Comparar hash de veredicto de validaciones ---
            order_validation_text = v_order.get("text", "")
            logger.info(f"--- Calculando digest de validación para idAssertion {assertion_id}, validador {validator_address}: {order_validation_text}")
            calculated_hash_digest = hash_text_to_hash(order_validation_text).lower().removeprefix("0x")
            post_hash_digest = ipfs_get_text(v_post.get("cid"))
            hash_veredict_ok = calculated_hash_digest == post_hash_digest
            
            results.append(ConsistencyCheckResult(
                test=f"Comparando hash de validacion (texto) entre orden y Ethereum paraidAssertion {assertion_id} y validador {validator_address}",
                toCompare="Orden:"+"0x" + calculated_hash_digest,
                compared="Ethereum:"+"0x" + post_hash_digest,
                result="OK" if hash_veredict_ok else "KO"
            ))
            logger.info(f"--- Prueba 14 (Hash Veredict {assertion_id} {validator_address}): {'OK' if hash_veredict_ok else 'KO'}")
            
    logger.info("<- FIN: Chequeo de detalles de validación (Blockchain)")
    return results

# =========================================================
# FastAPI endpoints
# =========================================================
@app.post("/publishNew", status_code=202)
async def publish_new(req: PublishRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text")

    order_id = str(uuid.uuid4())
    order_doc = {
        "order_id": order_id,
        "status": "PENDING",
        "text": text,
        "cid": None,
        "postId": None,
        "hash_text": None,
        "tx_hash": None,
        "validators_pending": None,
        "assertions": None,
        "document": None,
        "validators": None
    }
    await save_order_doc(order_doc)
    logger.info(f"[{order_id}] Order saved in MongoDB, status=PENDING")

    # Publicar petición a generar aserciones con GenerateAssertionsRequest
    try:
        msg = GenerateAssertionsRequest(
            action="generate_assertions",
            order_id=order_id,
            payload={"text": text}
        )
        await producer.send_and_wait(TOPIC_REQUESTS_GENERATE, msg.model_dump_json().encode("utf-8"))
        logger.info(f"[{order_id}] Published generate_assertions to Kafka topic {TOPIC_REQUESTS_GENERATE}")
        await log_event(order_id, msg.action, TOPIC_REQUESTS_GENERATE, msg.payload.model_dump())
    except ValidationError as e:
        logger.exception(f"[{order_id}] Error validando generate_assertions request: {e}")
        raise HTTPException(status_code=500, detail="Internal validation error")

    await update_order(order_id, {"status": "ASSERTIONS_REQUESTED"})
    return {"order_id": order_id, "status": "ASSERTIONS_REQUESTED"}

@app.get("/orders/{order_id}")
async def get_order(order_id: str):
    order = await orders_collection.find_one({"order_id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Extraer el tiempo de creación del ObjectId y formatearlo
    try:
        order_object_id = order["_id"]
        created_datetime = order_object_id.generation_time
        # Formato MM/DD/YYY HH:mm:ss
        order["created"] = created_datetime.strftime("%d/%m/%Y %H:%M:%S")
    except Exception as e:
        # Manejo de error si _id no es un ObjectId válido (aunque no debería pasar)
        print(f"Error processing ObjectId: {e}")
        order["created"] = "Format Error"

    order["_id"] = str(order_object_id)
    return order

@app.get("/news/{order_id}/events", response_model=List[EventModel])
async def get_news_events(order_id: str):
    # Ya no necesitamos buscar la noticia para su created_at
    
    cursor = db.events.find({"order_id": order_id}, {"_id": 0})
    events = await cursor.to_list(length=100)

    if not events:
        raise HTTPException(status_code=404, detail="No hay eventos para esta noticia")

    for e in events:
        ms_timestamp = e.get("timestamp") # Marca de tiempo UNIX absoluta en MS
        
        if isinstance(ms_timestamp, (int, float)):

            # 1. Convertir milisegundos a segundos (dividir por 1000)
            unix_seconds = ms_timestamp / 1000.0 
            
            # 2. Crear objeto datetime
            event_datetime = datetime.fromtimestamp(unix_seconds)
            
            # 3. Formatear a MM/DD/YYY HH:mm:ss
            e["timestamp"] = event_datetime.strftime("%m/%d/%Y %H:%M:%S")
        elif not isinstance(ms_timestamp, str):
            e["timestamp"] = str(ms_timestamp)

    return events

@app.get("/news")
async def list_news():
    cursor = db.news.find({}, {"_id": 1, "order_id": 1, "status": 1, "hash_text": 1})
    news_list = await cursor.to_list(length=1000)

    if not news_list:
        raise HTTPException(status_code=404, detail="No hay noticias registradas")

    for news in news_list:
        oid = ObjectId(news["_id"])
        news["created_at"] = oid.generation_time.isoformat()
        del news["_id"]

    return news_list

@app.post("/find-order-by-text")
async def find_order_by_text(request: PublishRequest):
    global orders_collection
    try:
        if not request.text:
            raise HTTPException(status_code=400, detail="El campo 'text' no puede estar vacío.")

        mh = hash_text_to_multihash(request.text)
        digest_hex = mh.digest

        logger.info(f"🧮 Buscando órdenes con hash_text={digest_hex}")

        cursor = orders_collection.find(
            {"hash_text": digest_hex},
            {"_id": 1, "order_id": 1, "status": 1, "hash_text": 1}
        )
        docs = await cursor.to_list(length=1000)

        if not docs:
            logger.warning("❌ No se encontró ninguna orden con ese hash_text.digest")
            raise HTTPException(status_code=404, detail="No se encontró ninguna orden con ese hash.")

        for doc in docs:
            oid = ObjectId(doc["_id"])
            doc["created_at"] = oid.generation_time.isoformat()
            del doc["_id"]

        logger.info(f"✅ {len(docs)} coincidencia(s) encontrada(s).")
        return docs

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error en find_order_by_text: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/extract_text_from_url",
    response_model=ExtractedTextResponse,
    summary="Extrae el texto principal de una URL de noticia"
)
def extract_text_from_url(request: ExtractTextRequest):
    """
    Recupera una página web, elimina contenido no esencial (anuncios, menús) 
    y retorna el título y el texto del artículo principal usando Readability.
    """
    
    url = request.url
    HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ArticleExtractor/1.0)"}
    TIMEOUT_SECONDS = 15
    
    try:
        resp = requests.get(url, timeout=TIMEOUT_SECONDS, headers=HEADERS)
        
        if resp.status_code != 200:
            logger.warning(f"Error HTTP {resp.status_code} al acceder a la URL: {url}")
            raise HTTPException(status_code=resp.status_code, detail=f"No se pudo acceder a la URL.")
        
        doc = Document(resp.text)
        title = doc.title()
        main_content_html = doc.summary()
        
        if not main_content_html:
            raise ValueError("No se pudo identificar el contenido principal.")

        root = lxml.html.fromstring(main_content_html)
        clean_text = root.text_content().strip()
        lines = [line.strip() for line in clean_text.splitlines() if line.strip()]
        final_clean_text = "\n".join(lines)
        
        if not final_clean_text:
            raise ValueError("El texto extraído está vacío.")

        return ExtractedTextResponse(url=str(url), title=title, text=final_clean_text)

    except requests.exceptions.Timeout:
        logger.error(f"Timeout al acceder a URL: {url}")
        raise HTTPException(status_code=504, detail="Tiempo de espera agotado al acceder a la URL.")
    
    except requests.RequestException as e:
        logger.error(f"Error de conexión accediendo a URL {url}: {e}")
        raise HTTPException(status_code=500, detail=f"Error de conexión: {e}")
    
    except ValueError as e:
        logger.warning(f"Error de extracción para {url}: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    
    except Exception as e:
        logger.error(f"Error inesperado al procesar {url}: {e}")
        raise HTTPException(status_code=500, detail="Error interno del servidor.")

@app.get("/checkOrderConsistency/{order_id}", response_model=List[ConsistencyCheckResult])
async def check_order_consistency(order_id: str):
    """
    Orquesta las pruebas de consistencia Order -> IPFS -> Blockchain.
    """
    logger.info(f"Iniciando checkOrderConsistency para OrderID: {order_id}")
    all_results: List[ConsistencyCheckResult] = []
    order_data = None
    ipfs_content = None
    post_data = None
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Chequeo de Order (Base)
        order_results, order_data = await _check_order_retrieval( order_id)
        all_results.extend(order_results)
        
        if not order_data:
            logger.error(f"Fallo crítico: No se pudo recuperar la Order {order_id}. Deteniendo.")
            return all_results

        # 2. Chequeo de IPFS vs Order
        ipfs_results, ipfs_content = await _check_ipfs_consistency(client, order_data)
        all_results.extend(ipfs_results)
        
        # 3. Chequeo de Blockchain vs Order (General)
        blockchain_results, post_data = await _check_blockchain_consistency(client, order_data)
        all_results.extend(blockchain_results)
        
        if not post_data:
            logger.error(f"Fallo crítico: No se pudo recuperar el Post de Blockchain. Deteniendo chequeos detallados.")
            return all_results
            
        # 4. Chequeo de Assertions (Detalles de las Aserciones)
        assertion_detail_results = _check_assertion_details_consistency(order_data, post_data)
        all_results.extend(assertion_detail_results)

        # 5. Chequeo de Validations (Detalles de las Validaciones)
        validation_detail_results = _check_validation_details_consistency(order_data, post_data)
        all_results.extend(validation_detail_results)

    logger.info(f"checkOrderConsistency para OrderID: {order_id} finalizado. {len(all_results)} tests ejecutados.")
    return all_results


@app.post("/publishWithAssertions", status_code=202)
async def publish_with_assertions(req: PublishWithAssertionsRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text")

    if not req.assertions or len(req.assertions) == 0:
        raise HTTPException(status_code=400, detail="No assertions provided")

    order_id = str(uuid.uuid4())
    order_doc = {
        "order_id": order_id,
        "status": "ASSERTIONS_REQUESTED",
        "text": text,
        "cid": None,
        "postId": None,
        "hash_text": None,
        "tx_hash": None,
        "validators_pending": None,
        "assertions": [a.model_dump() for a in req.assertions],
        "document": None,
        "validators": None
    }

    # Guardar en MongoDB
    await save_order_doc(order_doc)
    logger.info(f"[{order_id}] Order saved in MongoDB with pre-generated assertions")

    # Convertir a Assertion
    from common.async_models import Assertion
    assertions_for_payload = [
        Assertion(idAssertion=a.idAssertion, text=a.text, categoryId=a.categoryId)
        for a in req.assertions
    ]

    # Publicar mensaje
    try:
        msg = AssertionsGeneratedResponse(
            action="assertions_generated",
            order_id=order_id,
            payload={
                "text": text,
                "publisher": "news-handler",
                "assertions": assertions_for_payload
            }
        )
        await producer.send_and_wait(TOPIC_RESPONSES, msg.model_dump_json().encode("utf-8"))
        logger.info(f"[{order_id}] Published 'assertions_generated' to Kafka topic {TOPIC_RESPONSES}")
        #await log_event(order_id, msg.action, TOPIC_RESPONSES, msg.payload.model_dump())
    except ValidationError as e:
        logger.exception(f"[{order_id}] Error validando assertions_generated message: {e}")
        raise HTTPException(status_code=500, detail="Internal validation error")

    return {"order_id": order_id, "status": "ASSERTIONS_REQUESTED"}


# =========================================================
# Startup / Shutdown
# =========================================================
@app.on_event("startup")
async def startup_event():
    global producer, consumer, mongo_client, db, orders_collection

    # MongoDB
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[MONGO_DBNAME]
    orders_collection = db[MONGO_COLLECTION]
    logger.info(f"MongoDB connected at {MONGO_COLLECTION}")

    # Crear índices útiles
    try:
        await db["events"].create_index([("order_id", 1)])
        await db["events"].create_index([("action", 1)])
        await db["validations"].create_index([("order_id", 1)])
        logger.info("MongoDB indexes for events and validations ensured")
    except Exception as e:
        logger.warning(f"Could not create indexes: {e}")

    # Kafka producer
    producer = AIOKafkaProducer(
        bootstrap_servers=KAFKA_BROKER,
        **kafka_security_kwargs()
    )
    await producer.start()
    logger.info("Kafka producer started")

    # Consumer lanzado en background
    asyncio.create_task(consume_responses_loop())
    logger.info("Background consumer task started")

@app.on_event("shutdown")
async def shutdown_event():
    global producer, consumer, mongo_client
    if producer:
        await producer.stop()
    if consumer:
        await consumer.stop()
    if mongo_client:
        mongo_client.close()
    logger.info("Shutdown complete")
