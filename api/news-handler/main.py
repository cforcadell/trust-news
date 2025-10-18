import os
import uuid
import json
import asyncio
import logging
import hashlib
import requests
from bs4 import BeautifulSoup
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from bson import ObjectId

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

EMULATE_BLOCKCHAIN_REQUESTS = os.getenv("EMULATE_BLOCKCHAIN_REQUESTS", "true").lower() == "true"

# =========================================================
# App & globals
# =========================================================
app = FastAPI(title="Fake News Orchestrator")
producer: Optional[AIOKafkaProducer] = None
consumer: Optional[AIOKafkaConsumer] = None
mongo_client: Optional[AsyncIOMotorClient] = None
db = None
orders_collection = None

# ---------- Models ----------
class PublishRequest(BaseModel):
    text: str

# =========================================================
# Helpers DB & Kafka security
# =========================================================
def kafka_security_kwargs():
    # Return only keys if values exist (aiokafka will ignore empty values but be explicit)
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

    # Mantener $push si existe
    if "$push" in update:
        mongo_update["$push"] = update.pop("$push")

    # Si el update ya tiene $set, usarlo directamente
    if "$set" in update:
        mongo_update["$set"] = update.pop("$set")
    elif update:  # Si no, envolver todo en $set
        mongo_update["$set"] = update

    result = await orders_collection.update_one({"order_id": order_id}, mongo_update)
    if result.matched_count == 0:
        logger.error(f"Order {order_id} not found in MongoDB")


async def get_order_doc(order_id: str) -> Optional[dict]:
    doc = await orders_collection.find_one({"order_id": order_id})
    return doc

# ===========================
# Helpers para hashes
# ===========================
def hash_text_to_multihash(text: str) -> dict:
    """Genera un hash SHA-256 tipo multihash para enviar al smart contract."""
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {
        "hash_function": "0x12",  # sha2-256
        "hash_size": "0x20",      # 32 bytes
        "digest": "0x" + h
    }

# ===========================
# Emulación / manejo blockchain
# ===========================
async def handle_blockchain_request(order_id: str, text: str, cid: str, assertions: list):
    global producer

    hash_text = hash_text_to_multihash(text)
    asertions_hashed = []
    validator_addresses_matrix = []

    for a in assertions:
        mh = hash_text_to_multihash(a.get("text", ""))
        id_assertion = a.get("idAssertion") or str(uuid.uuid4().hex[:8])
        asertions_hashed.append({
            "hash_asertion": mh,
            "idAssertion": id_assertion,
            "text": a.get("text", ""),
            "categoryId": a.get("categoryId", 0)
        })
        # Simulamos validadores si estamos en modo emulado
        fake_validators = ["VAL1", "VAL2", "VAL3"]
        validator_addresses_matrix.append([{"Address": v} for v in fake_validators])

    if EMULATE_BLOCKCHAIN_REQUESTS:
        simulated_msg = {
            "action": "blockchain_registered",
            "order_id": order_id,
            "payload": {
                "postId": 1,
                "hash_text": hash_text,
                "assertions": asertions_hashed,
                "validatorAddressesByAsertion": validator_addresses_matrix,
                "tx_hash": "0xSIMULATEDTXHASH1234567890abcdef"
            }
        }
        await producer.send_and_wait(TOPIC_RESPONSES, json.dumps(simulated_msg).encode("utf-8"))
        logger.info(f"[{order_id}] Mensaje 'blockchain_registered' EMULADO publicado")
    else:
        # Mensaje real al topic de blockchain
        message = {
            "action": "register_blockchain",
            "order_id": order_id,
            "payload": {
                "hash_text": hash_text,
                "cid": cid,
                "assertions": asertions_hashed,
                "publisher": "news-handler"
            }
        }
        await producer.send_and_wait(TOPIC_REQUESTS_BLOCKCHAIN, json.dumps(message).encode("utf-8"))
        logger.info(f"[{order_id}] Mensaje enviado al topic {TOPIC_REQUESTS_BLOCKCHAIN}")

# =========================================================
# Procesador genérico de mensajes Kafka (reutilizable)
# =========================================================
async def process_kafka_message(data: dict):
    """
    data: dict ya decodificado del JSON del mensaje Kafka.
    Maneja: assertions_generated, ipfs_uploaded, blockchain_registered, validation_completed.
    """
    try:
        action = data.get("action")
        order_id = data.get("order_id")
        payload = data.get("payload", {})

        if not action or not order_id:
            logger.warning("Message without 'action' or 'order_id', skipping.")
            return

        # ================================================================
        # 1️ assertions_generated
        # ================================================================
        if action == "assertions_generated":
            doc = await get_order_doc(order_id)
            if not doc:
                logger.warning(f"[{order_id}] Document not found in DB.")
                return

            assertions = payload.get("assertions", [])
            if not assertions:
                logger.warning(f"[{order_id}] Empty assertions payload.")
                return

            document = {
                "order_id": order_id,
                "text": doc["text"],
                "assertions": assertions,
                "metadata": {
                    "generated_by": "news-handler",
                    "timestamp": asyncio.get_event_loop().time()
                }
            }

            await update_order(order_id, {
                "assertions": assertions,
                "document": document,
                "status": "DOCUMENT_CREATED",
                "$push": {"history": {"event": "assertions_generated", "payload": payload}}
            })
            logger.info(f"[{order_id}] Assertions saved and document created.")

            # Enviar upload_ipfs request
            msg_ipfs = {
                "action": "upload_ipfs",
                "order_id": order_id,
                "payload": {"document": document}
            }
            await producer.send_and_wait(TOPIC_REQUESTS_IPFS, json.dumps(msg_ipfs).encode("utf-8"))
            logger.info(f"[{order_id}] Document sent to IPFS service ({TOPIC_REQUESTS_IPFS}).")

            await update_order(order_id, {
                "status": "IPFS_PENDING",
                "$push": {"history": {"event": "upload_ipfs_requested"}}
            })

        # ================================================================
        # 2 ipfs_uploaded
        # ================================================================
        elif action == "ipfs_uploaded":
            doc = await get_order_doc(order_id)
            if not doc:
                logger.warning(f"[{order_id}] Document not found for IPFS update.")
                return

            cid = payload.get("cid")
            if not cid:
                logger.warning(f"[{order_id}] Missing 'cid' in payload.")
                return

            text = doc.get("text", "")
            

            await update_order(order_id, {
                "cid": cid,
                "status": "IPFS_UPLOADED",
                "$push": {"history": {"event": "ipfs_uploaded", "payload": payload}}
            })
            logger.info(f"[{order_id}] IPFS uploaded with CID={cid} ")

            # Manejo especial: si EMULATE_BLOCKCHAIN_REQUESTS=true, se genera blockchain_registered
            await handle_blockchain_request(order_id, text, cid, doc.get("assertions", []))

            await update_order(order_id, {
                "status": "BLOCKCHAIN_PENDING",
                "$push": {"history": {"event": "register_blockchain_sent"}}
            })

        # ================================================================
        # 3 blockchain_registered
        # ================================================================
        elif action == "blockchain_registered":
            post_id = payload.get("postId")
            validator_matrix = payload.get("validatorAddressesByAsertion")
            if not validator_matrix:
                logger.warning(f"[{order_id}] blockchain_registered sin validatorAddressesByAsertion")
                return

            doc = await get_order_doc(order_id)
            if not doc:
                logger.warning(f"[{order_id}] Documento no encontrado para blockchain_registered")
                return

            validators_info = []
            for i, validator_list in enumerate(validator_matrix):
                assertion_id = (
                    doc["assertions"][i].get("idAssertion") or str(uuid.uuid4().hex[:8])
                )
                validators_info.append({
                    "idAssertion": assertion_id,
                    "validatorAddresses": [v["Address"] for v in validator_list]
                })

            # Guardar info en MongoDB
            await update_order(order_id, {
                "validators": validators_info,
                "validators_pending": sum(len(v["validatorAddresses"]) for v in validators_info),
                "status": "VALIDATION_PENDING",
                "$push": {"history": {"event": "blockchain_registered", "payload": payload}}
            })

            # Enviar requests de validación
            for val in validators_info:
                for validator_addr in val["validatorAddresses"]:
                    msg_validation = {
                        "action": "request_validation",
                        "order_id": order_id,
                        "payload": {
                            "idValidator": validator_addr,
                            "idAssertion": val["idAssertion"],
                            "text": doc["text"],
                            "context": doc["text"]
                        }
                    }
                    await producer.send_and_wait(TOPIC_REQUESTS_VALIDATE, json.dumps(msg_validation).encode("utf-8"))

        # ================================================================
        # 4️ validation_completed (adaptado: requiere todas las validaciones)
        # ================================================================
        elif action == "validation_completed":
            id_val = payload.get("idValidator")
            id_assert = payload.get("idAssertion")
            status_val = payload.get("approval")
            assertion_text = payload.get("text", "")
            tx_hash = payload.get("tx_hash", "")

            logger.info(f"[{order_id}] Validación recibida: Assertion={id_assert}, Validator={id_val}, Approval={status_val}")

            if not id_val or not id_assert:
                logger.warning(f"[{order_id}] validation_completed sin idValidator o idAssertion, ignorando")
                return

            doc = await get_order_doc(order_id)
            if not doc:
                logger.warning(f"[{order_id}] Documento no encontrado para validation_completed")
                return

            # Guardar resultado en MongoDB
            validations = doc.get("validations", {})
            id_assert_str = str(id_assert)
            if id_assert_str not in validations:
                validations[id_assert_str] = {}

            validations[id_assert_str][id_val] = {
                "approval": status_val,
                "text": assertion_text,
                "tx_hash": tx_hash
            }

            await update_order(order_id, {"$set": {"validations": validations}})
            logger.info(f"[{order_id}] Validación registrada en MongoDB para Assertion={id_assert}, Validator={id_val}")

            # Comprobar si todas las aserciones han completado todas sus validaciones
            all_done = True
            for assertion in doc.get("assertions", []):
                aid = str(assertion.get("idAssertion"))
                expected_validators = assertion.get("validators", [])
                done_validators = validations.get(aid, {})
                if set(done_validators.keys()) != set(expected_validators):
                    all_done = False
                    break

            if all_done:
                await update_order(order_id, {"$set": {"status": "VALIDATED"}})
                logger.info(f"[{order_id}] Toda la noticia validada correctamente.")

        else:
            logger.warning(f"[{order_id}] Unknown action received: {action}")

    except Exception as e:
        logger.exception(f"Error processing Kafka message: {e}")

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
        "assertions": None,
        "document": None,
        "cid": None,
        "smart_token": None,
        "history": []
    }
    await save_order_doc(order_doc)
    logger.info(f"[{order_id}] Order saved in MongoDB, status=PENDING")

    # Publicar petición a generar aserciones
    message = {
        "action": "generate_assertions",
        "order_id": order_id,
        "payload": {"text": text}
    }
    await producer.send_and_wait(TOPIC_REQUESTS_GENERATE, json.dumps(message).encode("utf-8"))
    logger.info(f"[{order_id}] Published generate_assertions to Kafka topic {TOPIC_REQUESTS_GENERATE}")

    # update status
    await update_order(order_id, {"status": "ASSERTIONS_REQUESTED", "$push": {"history": {"event": "sent_generate_assertions"}}})
    return {"order_id": order_id, "status": "ASSERTIONS_REQUESTED"}

@app.get("/orders/{order_id}")
async def get_order(order_id: str):
    order = await orders_collection.find_one({"order_id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Convertimos el ObjectId en string
    order["_id"] = str(order["_id"])
    return order

@app.post("/news_registered/{order_id}")
async def news_registered(order_id: str):
    doc = await get_order_doc(order_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Order not found")

    # Solo actualizar si no estaba ya registrado
    if doc.get("status") != "NEWS_REGISTERED":
        await update_order(order_id, {
            "status": "NEWS_REGISTERED",
            "$push": {"history": {"event": "news_registered"}}
        })
        logger.info(f"[{order_id}] Status actualizado a NEWS_REGISTERED por frontend")
        return {"order_id": order_id, "status": "NEWS_REGISTERED"}
    else:
        return {"order_id": order_id, "status": doc.get("status"), "msg": "Already registered"}

@app.get("/extract_text_from_url")
def extract_text_from_url(url: str = Query(..., description="URL de la noticia")):
    """
    Recupera el contenido de una URL y devuelve solo el texto limpio de la noticia.
    """
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=f"No se pudo acceder a la URL: {url}")

        soup = BeautifulSoup(resp.content, "html.parser")

        # Extraer solo texto visible, ignorando scripts y estilos
        for script_or_style in soup(["script", "style"]):
            script_or_style.extract()

        text = soup.get_text(separator="\n")
        # Limpiar líneas vacías
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        clean_text = "\n".join(lines)

        return {"url": url, "text": clean_text}

    except requests.RequestException as e:
        logger.error(f"Error accediendo a URL {url}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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

    # Kafka producer
    producer = AIOKafkaProducer(
        bootstrap_servers=KAFKA_BROKER,
        **kafka_security_kwargs()
    )
    await producer.start()
    logger.info("Kafka producer started")

    # Kafka consumer (consume_responses_loop will create and start its own consumer)
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
