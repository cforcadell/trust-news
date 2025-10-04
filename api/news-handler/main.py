import os
import uuid
import json
import asyncio
import logging

from typing import Any, Dict
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from motor.motor_asyncio import AsyncIOMotorClient

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

MONGO_URI = os.getenv("MONGO_URI", "")
MONGO_DBNAME = os.getenv("MONGO_DBNAME", "")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "")

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
    logger.info(f"[{order_id}] Order saved in MongoDB, status=PENDING")

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
    doc = await get_order_doc(order_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return doc

# ---------- Kafka consumer loop ----------
async def consume_responses_loop():
    global consumer, producer, orders_collection
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
                #status = data.get("status")

                if not order_id or not action:
                    logger.warning("Message without order_id/action, ignoring")
                    continue

                # Ejemplo: handle assertions_generated
                if action == "assertions_generated":
                    doc = await get_order_doc(order_id)
                    if not doc:
                        logger.warning(f"Order {order_id} not found")
                        continue
                    doc_update = {
                        "assertions": payload.get("assertions", []),
                        "document": {"order_id": order_id, "text": doc["text"], "assertions": payload.get("assertions", []),
                                     "metadata": {"generated_by": "ai-service", "timestamp": asyncio.get_event_loop().time()}},
                        "status": "DOCUMENT_CREATED",
                        "$push": {"history": {"event": "assertions_received", "payload": payload}}
                    }
                    await update_order(order_id, doc_update)

                    # Publicar request IPFS sin order_id en payload.document
                    msg_ipfs = {
                        "action": "upload_ipfs",
                        "order_id": order_id,  # mantenemos order_id para seguimiento de la orden
                        "payload": {"document": doc_update["document"]}  # document sin order_id
                    }
                    await producer.send_and_wait(TOPIC_REQUESTS, json.dumps(msg_ipfs).encode("utf-8"))

                    # Actualizar estado en MongoDB
                    await update_order(
                        order_id,
                        {"status": "IPFS_PENDING", "$push": {"history": {"event": "sent_upload_ipfs"}}}
                    )

                # ...otros actions se adaptan de manera similar usando update_order
            except Exception as e:
                logger.exception("Error processing response message: %s", e)
    except Exception as e:
        logger.exception("Error in consume_responses_loop: %s", e)
