import os
import json
import asyncio
import logging
import uuid
import httpx
import time
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from dotenv import load_dotenv
from pydantic import ValidationError

# Importar modelos comunes
from common.async_models import UploadIpfsRequest, IpfsUploadedResponse, Metadata, Document 

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
REQUEST_TOPIC = os.getenv("KAFKA_REQUEST_TOPIC", "upload_ipfs") # Topic ajustado
RESPONSE_TOPIC = os.getenv("KAFKA_RESPONSE_TOPIC", "ipfs_responses") # Topic ajustado
MAX_RETRIES = 10
RETRY_DELAY = 3

IPFS_API_ADD = os.getenv("IPFS_API_ADD", "http://127.0.0.1:5001/api/v0/add")
IPFS_API_CAT = os.getenv("IPFS_API_CAT", "http://127.0.0.1:5001/api/v0/cat")

app = FastAPI(title="IPFS Agent Unified")

# -----------------------------
# Función interna para subir a IPFS
# -----------------------------
async def upload_to_ipfs(document: bytes, filename: str) -> str:
    """Sube un documento a la API de IPFS y devuelve el CID."""
    logger.debug(f"Subiendo a IPFS archivo={filename}, tamaño={len(document)} bytes")
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            IPFS_API_ADD,
            files={"file": (filename, document)}
        )
    if response.status_code != 200:
        logger.error(f"Fallo en subida a IPFS (status={response.status_code}) - {response.text}")
        raise Exception(f"Error subiendo a IPFS: {response.text}")

    try:
        cid = response.json().get("Hash")
        if not cid:
             raise ValueError("Respuesta de IPFS no contiene 'Hash'.")
    except Exception as e:
        logger.error(f"No se pudo parsear la respuesta de IPFS: {e}")
        raise

    logger.info(f"Archivo {filename} subido a IPFS con CID={cid}")
    return cid

# -----------------------------
# Endpoint unificado /ipfs/upload (Se mantiene para compatibilidad HTTP)
# -----------------------------
@app.post("/ipfs/upload")
async def upload_file(
    filename: str = Form(...),
    file: Optional[UploadFile] = File(None),
    content_bytes: Optional[bytes] = Form(None)
):
    """Permite subir un archivo mediante un endpoint HTTP directo (no Kafka)."""
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
    """Consulta el contenido de un CID en IPFS."""
    logger.debug(f"Consulta a IPFS con CID={cid}")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
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
# Consumer Kafka
# -----------------------------
async def consume_and_process():
    """Consume mensajes de Kafka para subir documentos a IPFS."""
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
            order_id = str(uuid.uuid4())
            try:
                # 1. Parsear y validar el mensaje con Pydantic
                message_json = json.loads(msg.value.decode())
                
                # Usamos el modelo común para la validación
                request_model = UploadIpfsRequest(**message_json)
                
                action = request_model.action
                order_id = request_model.order_id
                
                if action != "upload_ipfs":
                    logger.warning(f"[{order_id}] Ignorando mensaje con action inesperada: {action}")
                    continue

                # 2. Reconstruir el documento para añadir la metadata
                doc: Document = request_model.payload.document
                
                # Se utiliza el modelo Metadata definido en common
                current_metadata = Metadata(
                    generated_by="ipfs-agent",
                    timestamp=time.time()
                )
                
                # Aseguramos que la metadata se actualice en el objeto Document
                doc.metadata = current_metadata
                
                # 3. Serializar y subir a IPFS
                # Usamos model_dump_json para obtener un JSON serializado de Pydantic
                document_bytes = doc.model_dump_json(exclude_none=True, by_alias=True).encode("utf-8")
                filename = f"{order_id}.json"
                
                cid = await upload_to_ipfs(document_bytes, filename)

                # 4. Publicar CID en Kafka usando el modelo de respuesta
                response_model = IpfsUploadedResponse(
                    action="ipfs_uploaded",
                    order_id=order_id,
                    payload={"cid": cid}
                )
                
                await producer.send_and_wait(
                    RESPONSE_TOPIC, 
                    response_model.model_dump_json(exclude_none=True).encode("utf-8")
                )
                logger.info(f"[{order_id}] Mensaje publicado en {RESPONSE_TOPIC} con CID={cid}")

            except ValidationError as ve:
                logger.error(f"[{order_id}] Error de validación Pydantic del payload: {ve}")
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