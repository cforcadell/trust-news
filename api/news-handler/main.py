import os
import uuid
import json
import asyncio
import logging
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from aiocouch import CouchDB, NotFoundError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fake-news-orchestrator")

# ---------- Config ----------
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
KAFKA_USERNAME = os.getenv("KAFKA_USERNAME", "app")
KAFKA_PASSWORD = os.getenv("KAFKA_PASSWORD", "")
KAFKA_SECURITY_PROTOCOL = os.getenv("KAFKA_SECURITY_PROTOCOL", "SASL_PLAINTEXT")
KAFKA_MECHANISM = os.getenv("KAFKA_MECHANISM", "PLAIN")

TOPIC_REQUESTS = os.getenv("TOPIC_REQUESTS", "fake_news_requests")
TOPIC_RESPONSES = os.getenv("TOPIC_RESPONSES", "fake_news_responses")

COUCHDB_USER = os.getenv("COUCHDB_USER", "admin")
COUCHDB_PASSWORD = os.getenv("COUCHDB_PASSWORD", "")
COUCHDB_HOST = os.getenv("COUCHDB_HOST", "couchdb:5984")
ORDERS_DB = os.getenv("ORDERS_DB", "orders")

# ---------- App & globals ----------
app = FastAPI(title="Fake News Orchestrator")
producer: AIOKafkaProducer | None = None
consumer: AIOKafkaConsumer | None = None
couch: CouchDB | None = None
db = None

# ---------- Models ----------
class PublishRequest(BaseModel):
    text: str

# ---------- Helpers ----------
def kafka_security_kwargs():
    return dict(
        security_protocol=KAFKA_SECURITY_PROTOCOL,
        sasl_mechanism=KAFKA_MECHANISM,
        sasl_plain_username=KAFKA_USERNAME,
        sasl_plain_password=KAFKA_PASSWORD,
    )

async def save_order_doc(order_doc: dict):
    global db
    doc = await db.create(order_doc["order_id"], data=order_doc)
    await doc.save()

async def update_order(order_id: str, update: dict):
    global db
    try:
        doc = await db[order_id]
        for k, v in update.items():
            if k == "$push":
                for push_key, push_val in v.items():
                    if push_key not in doc:
                        doc[push_key] = []
                    doc[push_key].append(push_val)
            else:
                doc[k] = v
        await doc.save()
    except NotFoundError:
        logger.error(f"Order {order_id} not found in CouchDB")

# ---------- Startup / Shutdown ----------
@app.on_event("startup")
async def startup_event():
    global producer, consumer, couch, db

    # CouchDB
    couch = CouchDB(COUCHDB_USER, COUCHDB_PASSWORD, url=f"http://{COUCHDB_HOST}", connect=True)
    # Crear DB si no existe
    if ORDERS_DB not in await couch.keys():
        db = await couch.create(ORDERS_DB)
        logger.info(f"CouchDB database '{ORDERS_DB}' created")
    else:
        db = await couch[ORDERS_DB]
        logger.info(f"CouchDB database '{ORDERS_DB}' exists")
    
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
    global producer, consumer, couch
    if producer:
        await producer.stop()
    if consumer:
        await consumer.stop()
    if couch:
        await couch.close()
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
        "text": text,
        "status": "PENDING",
        "assertions": None,
        "document": None,
        "ipfs_hash": None,
        "smart_token": None,
        "validator_status": None,
        "history": [],
    }
    await save_order_doc(order_doc)
    logger.info(f"[{order_id}] Order saved in CouchDB, status=PENDING")

    # Publicar petición a generar aserciones
    message = {
        "action": "generate_assertions",
        "order_id": order_id,
        "payload": {"text": text}
    }
    await producer.send_and_wait(TOPIC_REQUESTS, json.dumps(message).encode("utf-8"))
    logger.info(f"[{order_id}] Published generate_assertions to Kafka topic {TOPIC_REQUESTS}")

    # update status
    await update_order(order_id, {"status": "ASSERTIONS_REQUESTED", "$push": {"history": {"event": "sent_generate_assertions"}}})
    return {"order_id": order_id, "status": "ASSERTIONS_REQUESTED"}

@app.get("/orders/{order_id}")
async def get_order(order_id: str):
    try:
        doc = await db[order_id]
        return dict(doc)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Order not found")

# ---------- Kafka consumer loop ----------
async def consume_responses_loop():
    global consumer, producer, db
    logger.info("Starting consume_responses_loop")
    try:
        async for msg in consumer:
            try:
                raw = msg.value.decode("utf-8")
                data = json.loads(raw)
                logger.info(f"Received response message: {data}")
                action = data.get("action")
                order_id = data.get("order_id")
                payload = data.get("payload", {})
                status = data.get("status")

                if not order_id or not action:
                    logger.warning("Message without order_id/action, ignoring")
                    continue

                # Ejemplo: handle assertions_generated
                if action == "assertions_generated":
                    doc_text = (await db[order_id])["text"]
                    doc = {"order_id": order_id, "text": doc_text, "assertions": payload.get("assertions", []), "metadata": {"generated_by": "ai-service", "timestamp": asyncio.get_event_loop().time()}}
                    await update_order(order_id, {"assertions": doc["assertions"], "document": doc, "status": "DOCUMENT_CREATED", "$push": {"history": {"event": "assertions_received", "payload": payload}}})
                    # Publicar request IPFS
                    msg_ipfs = {"action": "upload_ipfs", "order_id": order_id, "payload": {"document": doc}}
                    await producer.send_and_wait(TOPIC_REQUESTS, json.dumps(msg_ipfs).encode("utf-8"))
                    await update_order(order_id, {"status": "IPFS_PENDING", "$push": {"history": {"event": "sent_upload_ipfs"}}})

                # ...otros actions se adaptan de manera similar usando update_order
                # Puedes copiar el resto de tu lógica reemplazando `update_order` y `db[...]` en lugar de Mongo
            except Exception as e:
                logger.exception("Error processing response message: %s", e)
    except Exception as e:
