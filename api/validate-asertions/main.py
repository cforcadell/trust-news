from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
import os
import asyncio
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
import json
import logging
from dotenv import load_dotenv
import uuid

# -----------------------------
# Cargar variables de entorno
# -----------------------------
load_dotenv()

# -----------------------------
# Configurar logging dinámico
# -----------------------------
log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_str, logging.INFO)
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Inicializar FastAPI
app = FastAPI(title="API de Validación de Aserciones ")

# Modelo de entrada
class TextoEntrada(BaseModel):
    texto: str

# Función que llama a Mistral API
def verificar_asercion(texto: str):
    url = os.getenv("API_URL")
    API_KEY = os.getenv("MISTRAL_API_KEY")
    MODEL = os.getenv("MISTRAL_MODEL", "mistral-tiny")
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": (
                   "Validame la siguiente aserción. Devueve dos tags. En 'resultado': TRUE, FALSE o UNKNOWN. A continuacion en el tag 'descripcion' la explicacion si es necesaria. Ajustate al formato.\n\n"
                    f"Texto a analizar:\n{texto}"
                )
            }
        ],
        "temperature": 0.3,
    }

    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    else:
        raise HTTPException(status_code=response.status_code, detail=response.text)

# Endpoint
@app.post("/verificar")
def verificar(texto_entrada: TextoEntrada):
    resultado = verificar_asercion(texto_entrada.texto)
    return {"verificación": resultado}

# -----------------------------
# Kafka consumer/producer
# -----------------------------
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
REQUEST_TOPIC = os.getenv("KAFKA_REQUEST_TOPIC", "fake_news_requests")
RESPONSE_TOPIC = os.getenv("KAFKA_RESPONSE_TOPIC", "fake_news_responses")
MAX_RETRIES = 10
RETRY_DELAY = 3  # segundos

async def consume_and_process():
    consumer = AIOKafkaConsumer(
        REQUEST_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id="news-handler-group",
        auto_offset_reset="earliest"
    )
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP)

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
                texto = payload.get("assertion_content", "")
                assertion_id = payload.get("assertion_id", "")
                
                logger.debug(f"Mensaje recibido de Kafka (action={action}, order_id={order_id}): {texto}")

                if action != "request_validation":
                    logger.warning(f"Ignorando mensaje con action inesperada: {action}")
                    continue

                # Generar aserciones usando la función extraer
                veredict = verificar_asercion(TextoEntrada(texto=texto))

                # Construir respuesta estructurada
                response_msg = {
                    "action": "validation_completed",
                    "order_id": order_id,
                    "payload": {"assertion_id": assertion_id, "veredict": veredict}
                }

                # Publicar en topic de respuestas
                await producer.send_and_wait(RESPONSE_TOPIC, json.dumps(response_msg).encode())
                logger.info(f"Documento publicado en topic {RESPONSE_TOPIC} (order_id={order_id})")

            except Exception as e:
                logger.error(f"Error procesando mensaje Kafka: {e}")

    finally:
        await consumer.stop()
        await producer.stop()
        logger.info("Kafka consumer y producer detenidos")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(consume_and_process())
