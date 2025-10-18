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

# -----------------------------
# FastAPI
# -----------------------------
app = FastAPI(title="API de Extracción de Aserciones Verificables y Generación de Documentos")

class TextoEntrada(BaseModel):
    texto: str

# -----------------------------
# Función que llama a Mistral API
# -----------------------------
def extraer_aserciones_verificables(texto: str):
    url = os.getenv("API_URL")
    API_KEY = os.getenv("MISTRAL_API_KEY")
    MODEL = os.getenv("MISTRAL_MODEL", "mistral-tiny")
    PROMPT = os.getenv(
        "MISTRAL_PROMPT",
        "Extrae solo las aserciones verificables que contengan cifras objetivables y eliminen cualquier valoración subjetiva."
    )

    full_prompt = f"{PROMPT}. Texto a analizar:\n{texto}"
    logger.info(f"Prompt a enviar a Mistral: {full_prompt}")

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": MODEL,
        "messages": [{"role": "user", "content": full_prompt}],
        "temperature": 0.3
    }

    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        logger.info("Mistral API respondió correctamente")
        return response.json()["choices"][0]["message"]["content"]
    else:
        logger.error(f"Error Mistral API {response.status_code}: {response.text}")
        raise HTTPException(status_code=response.status_code, detail=response.text)


import re

def parse_aserciones_mistral(aserciones_raw: str):
    """
    Intenta extraer la lista de aserciones de un texto semiestructurado devuelto por Mistral.
    """
    # 1️⃣ Quitar prefijos como "assertions:" o "aserciones:" si existen
    cleaned = re.sub(r'^\s*(assertions|aserciones)\s*:\s*', '', aserciones_raw.strip(), flags=re.IGNORECASE)

    # 2️⃣ Asegurarse de que empieza con "[" y termina con "]"
    start = cleaned.find('[')
    end = cleaned.rfind(']') + 1
    if start != -1 and end != -1:
        cleaned = cleaned[start:end]

    # 3️⃣ Intentar parsear JSON directamente
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # 4️⃣ Intentar fallback: convertir comillas simples a dobles, eliminar comentarios, etc.
        fixed = cleaned.replace("'", '"')
        try:
            return json.loads(fixed)
        except Exception:
            logger.warning(f"No se pudo convertir la respuesta en JSON válido. Texto recibido:\n{aserciones_raw}")
            return []


# -----------------------------
# Endpoint /extraer
# -----------------------------
@app.post("/extraer")
def extraer(texto_entrada: TextoEntrada):
    texto = texto_entrada.texto
    logger.info(f"Texto recibido en /extraer: {texto}")

    try:
        aserciones_raw = extraer_aserciones_verificables(texto)
        logger.info(f"Aserciones crudas recibidas de Mistral: {aserciones_raw}")
    except HTTPException as e:
        logger.error(f"Error al llamar a Mistral API: {e.detail}")
        raise

    try:
        aserciones_list = parse_aserciones_mistral(aserciones_raw)
        aserciones_final = [
            a.get("asercion", a) if isinstance(a, dict) else a
            for a in aserciones_list
        ]
        logger.info(f"Aserciones parseadas: {aserciones_final}")
    except Exception as e:
        logger.warning(f"No se pudo parsear JSON de aserciones: {e}")
        aserciones_final = []

    documento = {"new": texto, "asertions": []}
    for i, a in enumerate(aserciones_final, start=1):
        documento["asertions"].append({"idAssertion": str(i), "description": a})
        logger.info(f"Aserción añadida al documento: idAssertion={i}, description={a}")        


    logger.info(f"Documento final generado: {documento}")
    return documento

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
                texto = payload.get("text", "")
                
                logger.debug(f"Mensaje recibido de Kafka (action={action}, order_id={order_id}): {texto}")

                if action != "generate_assertions":
                    logger.warning(f"Ignorando mensaje con action inesperada: {action}")
                    continue

                # Generar aserciones usando la función extraer
                documento = extraer(TextoEntrada(texto=texto))

                # Construir respuesta estructurada
                response_msg = {
                    "action": "assertions_generated",
                    "order_id": order_id,
                    "payload": {"assertions": documento.get("asertions", [])}
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
