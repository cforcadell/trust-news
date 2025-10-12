import os
import uuid
import json
import asyncio
import logging
import aiohttp
import itertools
import hashlib
import requests
import bs4


from bs4 import BeautifulSoup
from typing import Any, Dict
from fastapi import FastAPI, HTTPException,Query
from pydantic import BaseModel
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import Query



logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fake-news-orchestrator")

# ---------- Config ----------
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

MONGO_URI = os.getenv("MONGO_URI", "")
MONGO_DBNAME = os.getenv("MONGO_DBNAME", "")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "")

MAX_WORKERS = int(os.getenv("MAX_WORKERS", "1"))
worker_counter = itertools.cycle(range(1, MAX_WORKERS + 1))

# ---------- App & globals ----------
app = FastAPI(title="Fake News Orchestrator")
producer: AIOKafkaProducer | None = None
consumer: AIOKafkaConsumer | None = None
mongo_client: AsyncIOMotorClient | None = None
db = None
orders_collection = None

# ---------- Models ----------
class PublishRequest(BaseModel):
    text: str
    callback_url: str  

# ---------- Helpers ----------
def kafka_security_kwargs():
    return dict(
        security_protocol=KAFKA_SECURITY_PROTOCOL,
        sasl_mechanism=KAFKA_MECHANISM,
        sasl_plain_username=KAFKA_USERNAME,
        sasl_plain_password=KAFKA_PASSWORD,
    )

async def save_order_doc(order_doc: dict):
    global orders_collection
    await orders_collection.insert_one(order_doc)

async def update_order(order_id: str, update: dict):
    global orders_collection
    mongo_update = {}
    if "$push" in update:
        mongo_update["$push"] = update.pop("$push")
    if update:
        mongo_update["$set"] = update
    result = await orders_collection.update_one({"order_id": order_id}, mongo_update)
    if result.matched_count == 0:
        logger.error(f"Order {order_id} not found in MongoDB")

async def get_order_doc(order_id: str) -> dict:
    doc = await orders_collection.find_one({"order_id": order_id})
    return doc

# ---------- Startup / Shutdown ----------
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

    # Kafka consumer
    consumer = AIOKafkaConsumer(
        TOPIC_RESPONSES,
        bootstrap_servers=KAFKA_BROKER,
        group_id="fake-news-orchestrator-group",
        auto_offset_reset="earliest",
        **kafka_security_kwargs()
    )
    await consumer.start()
    logger.info("Kafka consumer started and subscribed to responses")

    # Launch background consumer loop
    asyncio.create_task(consume_responses_loop())

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

# ---------- Endpoints ----------
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
        "history": [],
        "callback_url": req.callback_url
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
    doc = await get_order_doc(order_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return doc

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



# ---------- Kafka consumer loop ----------
async def consume_responses_loop():
    global consumer, producer, orders_collection
    logger.info("Starting consume_responses_loop")

    try:
        async for msg in consumer:
            try:
                raw = msg.value.decode("utf-8")
                data = json.loads(raw)
                logger.debug(f"Raw message received: {raw}")

                action = data.get("action")
                order_id = data.get("order_id")
                payload = data.get("payload", {})

                if not action or not order_id:
                    logger.warning("Message without 'action' or 'order_id', skipping.")
                    continue

                # ================================================================
                # 1️⃣ assertions_generated
                # ================================================================
                if action == "assertions_generated":
                    doc = await get_order_doc(order_id)
                    if not doc:
                        logger.warning(f"[{order_id}] Document not found in DB.")
                        continue

                    assertions = payload.get("assertions", [])
                    if not assertions:
                        logger.warning(f"[{order_id}] Empty assertions payload.")
                        continue

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

                    # Send upload_ipfs request
                    msg_ipfs = {
                        "action": "upload_ipfs",
                        "order_id": order_id,
                        "payload": {"document": document}
                    }
                    await producer.send_and_wait(TOPIC_REQUESTS_IPFS, json.dumps(msg_ipfs).encode("utf-8"))
                    logger.info(f"[{order_id}] Document sent to IPFS service.")

                    await update_order(order_id, {
                        "status": "IPFS_PENDING",
                        "$push": {"history": {"event": "upload_ipfs_requested"}}
                    })

                # ================================================================
                # 2️⃣ ipfs_uploaded
                # ================================================================
                elif action == "ipfs_uploaded":
                    doc = await get_order_doc(order_id)
                    if not doc:
                        logger.warning(f"[{order_id}] Document not found for IPFS update.")
                        continue

                    cid = payload.get("cid")
                    if not cid:
                        logger.warning(f"[{order_id}] Missing 'cid' in payload.")
                        continue

                    text = doc.get("text", "")
                    hash_text = hashlib.sha256(text.encode("utf-8")).hexdigest()

                    await update_order(order_id, {
                        "cid": cid,
                        "hash_text": hash_text,
                        "status": "IPFS_UPLOADED",
                        "$push": {"history": {"event": "ipfs_uploaded", "payload": payload}}
                    })
                    logger.info(f"[{order_id}] IPFS uploaded with CID={cid} and hash={hash_text}")

                    # Send register_blockchain request
                    msg_blockchain = {
                        "action": "register_blockchain",
                        "order_id": order_id,
                        "payload": {
                            "hash_text": hash_text,
                            "cid": cid,
                            "assertions": doc.get("assertions", [])
                        }
                    }
                    await producer.send_and_wait(TOPIC_REQUESTS_BLOCKCHAIN, json.dumps(msg_blockchain).encode("utf-8"))
                    logger.info(f"[{order_id}] Sent register_blockchain request.")

                    await update_order(order_id, {
                        "status": "BLOCKCHAIN_PENDING",
                        "$push": {"history": {"event": "register_blockchain_sent"}}
                    })

                # ================================================================
                # 3️⃣ blockchain_registered
                # ================================================================
                elif action == "blockchain_registered":
                    validators_info = payload.get("validators", [])
                    if not validators_info:
                        logger.warning(f"[{order_id}] Blockchain registered without validators.")
                        continue

                    # Guardar info de validadores y actualizar estado de orden
                    await update_order(order_id, {
                        "validators": validators_info,
                        "validators_pending": len(validators_info),
                        "status": "VALIDATION_PENDING",
                        "$push": {"history": {"event": "blockchain_registered", "payload": payload}}
                    })
                    logger.info(f"[{order_id}] Blockchain registration confirmed. Validators: {len(validators_info)}")

                    # Enviar requests de validación a cada validador
                    for val in validators_info:
                        # val debe contener al menos: {"asertionId": "0x..", "validatorAddresses": ["0x..", ...]}
                        for validator_addr in val.get("validatorAddresses", []):
                            msg_validation = {
                                "action": "request_validation",
                                "order_id": order_id,
                                "payload": {
                                    "asertionId": val.get("asertionId"),
                                    "idValidator": validator_addr,  # Aquí usamos el address devuelto por el contrato
                                    "postId": payload.get("postId")
                                }
                            }
                            await producer.send_and_wait(TOPIC_REQUESTS_VALIDATION, json.dumps(msg_validation).encode("utf-8"))
                            logger.info(f"[{order_id}] Validation request sent to validator {validator_addr} for asertion {val.get('asertionId')}")

                    await update_order(order_id, {
                        "$push": {"history": {"event": "validation_requests_sent"}}
                    })
                    logger.info(f"[{order_id}] Validation requests dispatched to all validators.")


                # ================================================================
                # 4️⃣ validation_completed
                # ================================================================
                elif action == "validation_completed":
                    id_val = payload.get("idValidator")
                    id_assert = payload.get("idAsertion")
                    status_val = payload.get("status")

                    doc = await get_order_doc(order_id)
                    if not doc:
                        logger.warning(f"[{order_id}] Document not found for validation_completed.")
                        continue

                    validators_pending = doc.get("validators_pending", 0)
                    if validators_pending > 0:
                        validators_pending -= 1

                    # Update validation result
                    await update_order(order_id, {
                        "validators_pending": validators_pending,
                        "$push": {"history": {
                            "event": "validation_completed",
                            "payload": payload
                        }}
                    })
                    logger.info(f"[{order_id}] Validation completed by {id_val} for {id_assert} → {status_val}")

                    # If all validations completed
                    if validators_pending <= 0:
                        await update_order(order_id, {
                            "status": "VALIDATED",
                            "$push": {"history": {"event": "all_validations_completed"}}
                        })
                        logger.info(f"[{order_id}] ✅ All validations completed. Order marked as VALIDATED.")

                # ================================================================
                # ⚠️ Unknown Action
                # ================================================================
                else:
                    logger.warning(f"[{order_id}] Unknown action received: {action}")

            except Exception as e:
                logger.exception("Error processing Kafka message: %s", e)

    except Exception as e:
        logger.exception("Fatal error in consume_responses_loop: %s", e)
