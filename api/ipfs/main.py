import os
import json
import asyncio
import logging
import uuid
import httpx

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from typing import Optional
from dotenv import load_dotenv

# -----------------------------
# Configuración inicial
# -----------------------------
load_dotenv()

# Configuración de logging desde .env
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
log_format = os.getenv("LOG_FORMAT", "%(asctime)s [%(levelname)s] %(name)s: %(message)s")

numeric_level = getattr(logging, log_level, logging.INFO)
logging.basicConfig(
    level=numeric_level,
    format=log_format,
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger("ipfs-agent")

# -----------------------------
# Variables de configuración
# -----------------------------
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
REQUEST_TOPIC = os.getenv("KAFKA_REQUEST_TOPIC", "fake_news_requests")
RESPONSE_TOPIC = os.getenv("KAFKA_RESPONSE_TOPIC", "fake_news_responses")
MAX_RETRIES = 10
RETRY_DELAY = 3

IPFS_API_ADD = os.getenv("IPFS_API_ADD", "http://127.0.0.1:5001/api/v0/add")
IPFS_API_CAT = os.getenv("IPFS_API_CAT", "http://127.0.0.1:5001/api/v0/cat")

app = FastAPI(title="IPFS Agent Unified")

# -----------------------------
# Función interna para subir a IPFS
# -----------------------------
async def upload_to_ipfs(document: bytes, filename: str) -> str:
    logger.debug(f"Subiendo a IPFS archivo={filename}, tamaño={len(document)} bytes")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            IPFS_API_ADD,
            files={"file": (filename, document)}
        )
    if response.status_code != 200:
        logger.error(f"Fallo en subida a IPFS (status={response.status_code}) - {response.text}")
        raise Exception(f"Error subiendo a IPFS: {response.text}")

    cid = response.json().get("Hash")
    logger.info(f"Archivo {filename} subido a IPFS con CID={cid}")
    return cid

# -----------------------------
# Endpoint unificado /ipfs/upload
# -----------------------------
@app.post("/ipfs/upload")
async def upload_file(
    filename: str = Form(...),
    file: Optional[UploadFile] = File(None),
    content_bytes: Optional[bytes] = Form(None)
):
    logger.debug(f"Solicitud de subida recibida (filename={filename})")
    try:
        if file is not None:
            data_bytes = await file.read()
            logger.debug(f"Archivo físico recibido: {filename}, tamaño={len(data_bytes)} bytes")
        elif content_bytes is not None:
            data_bytes = content_bytes
            logger.debug(f"Contenido en memoria recibido (filename={filename}, tamaño={len(data_bytes)} bytes)")
        else:
            logger.warning("Intento de subida sin contenido")
            raise HTTPException(status_code=400, detail="No se proporcionó contenido para subir")

        cid = await upload_to_ipfs(data_bytes, filename)
        return {"cid": cid, "filename": filename}

    except Exception as e:
        logger.exception("Error subiendo archivo a IPFS")
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------
# Endpoint /ipfs/{cid} para consultar
# -----------------------------
@app.get("/ipfs/{cid}")
async def get_ipfs_file(cid: str):
    logger.debug(f"Consulta a IPFS con CID={cid}")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{IPFS_API_CAT}?arg={cid}")
        if response.status_code != 200:
            logger.error(f"Fallo consultando CID={cid} en IPFS (status={response.status_code})")
            raise HTTPException(status_code=response.status_code, detail=response.text)

        logger.info(f"CID {cid} consultado con éxito en IPFS")
        return {"cid": cid, "content": response.text}
    except Exception as e:
        logger.exception(f"Error consultando CID={cid} en IPFS")
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------
# Consumer Kafka (usa función interna)
# -----------------------------
async def consume_and_process():
    consumer = AIOKafkaConsumer(
        REQUEST_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id="ipfs-agent-group",
        auto_offset_reset="earliest"
    )
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP)

    # Reintentos de conexión
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await consumer.start()
            await producer.start()
            logger.info("✅ Conectado a Kafka correctamente")
            break
        except Exception as e:
            logger.warning(f"⚠️ Kafka no disponible (intento {attempt}/{MAX_RETRIES}): {e}")
            if attempt == MAX_RETRIES:
                logger.error("No se pudo conectar a Kafka después de múltiples intentos")
                raise
            await asyncio.sleep(RETRY_DELAY)

    try:
        async for msg in consumer:
            try:
                payload_msg = json.loads(msg.value.decode())
                action = payload_msg.get("action")
                order_id = payload_msg.get("order_id", str(uuid.uuid4()))
                payload = payload_msg.get("payload", {})
                document = payload.get("document", {})

                logger.debug(f"Mensaje recibido (action={action}, order_id={order_id})")

                if action != "upload_ipfs":
                    logger.warning(f"Ignorando mensaje con action inesperada: {action}")
                    continue

                # Añadir metadata
                document["_metadata"] = {
                    "generated_by": "ai-service",
                    "timestamp": asyncio.get_event_loop().time()
                }
                document_bytes = json.dumps(document).encode("utf-8")
                filename = f"{order_id}.json"

                # Subida a IPFS
                cid = await upload_to_ipfs(document_bytes, filename)

                # Publicar CID en Kafka
                response_msg = {
                    "action": "ipfs_uploaded",
                    "order_id": order_id,
                    "payload": {"cid": cid}
                }
                await producer.send_and_wait(RESPONSE_TOPIC, json.dumps(response_msg).encode())
                logger.info(f"Mensaje publicado en topic {RESPONSE_TOPIC} (order_id={order_id}, cid={cid})")

            except Exception as e:
                logger.exception(f"Error procesando mensaje Kafka: {e}")

    finally:
        await consumer.stop()
        await producer.stop()
        logger.info("Kafka consumer y producer detenidos")

# -----------------------------
# Startup FastAPI
# -----------------------------
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(consume_and_process())
    logger.info("🚀 IPFS agent startup complete")
