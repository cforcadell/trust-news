from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
import os
import asyncio
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
import json

# -----------------------------
# FastAPI
# -----------------------------
app = FastAPI(title="API de Extracción de Aserciones Verificables y Generación de Documentos")

# Modelo de entrada para /extraer
class TextoEntrada(BaseModel):
    texto: str

# -----------------------------
# Función que llama a Mistral API
# -----------------------------
def extraer_aserciones_verificables(texto: str):
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
                    "Extrae solo las aserciones verificables que contengan cifras objetivables y eliminen cualquier valoración subjetiva. "
                    "Formatea el resultado como una lista de aserciones con sus fuentes sugeridas para verificación con su pais asociado, en formato JSON. "
                    "Los valores de fuentes: ECONOMIA, INE, EUROSTAT, FMI, BANCO MUNDIAL, ONU, OMS, UNESCO, OIT, OCDE, UNICEF, FAO, PNUD, CEPAL, ECDC, JHU, WHO..."
                    "Los valores de pais: España, Francia, Alemania, Italia, Portugal, Reino Unido, Estados Unidos, Canada, Mexico, Argentina, Brasil, Chile, Colombia, Peru, Venezuela..."
                    "Si no hay aserciones verificables, devuelve lista vacía.\n\n"
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

# -----------------------------
# Endpoint /extraer (texto -> JSON final)
# -----------------------------
@app.post("/extraer")
def extraer(texto_entrada: TextoEntrada):
    texto = texto_entrada.texto

    # Llamada a Mistral
    aserciones_raw = extraer_aserciones_verificables(texto)

    # Intentamos parsear JSON de las aserciones
    try:
        aserciones_list = json.loads(aserciones_raw)
        aserciones_final = [
            a.get("asercion", a) if isinstance(a, dict) else a
            for a in aserciones_list
        ]
    except:
        aserciones_final = []

    # Construir documento final
    documento = {
        "new": texto,
        "asertions": []
    }
    for i, a in enumerate(aserciones_final, start=1):
        documento["asertions"].append({
            "id": str(i),
            "description": a
        })

    return documento

# -----------------------------
# Kafka consumer/producer (consume texto, publica documento final)
# -----------------------------
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
REQUEST_TOPIC = os.getenv("KAFKA_REQUEST_TOPIC", "fake_news_requests")
RESPONSE_TOPIC = os.getenv("KAFKA_RESPONSE_TOPIC", "fake_news_responses")

# -----------------------------
# Kafka consumer/producer con reintentos
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
        group_id="news-handler-group"
    )
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP)

    # Reintentos para conectar Kafka
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await consumer.start()
            await producer.start()
            print("✅ Conectado a Kafka correctamente")
            break
        except Exception as e:
            print(f"⚠️  Kafka no disponible (intento {attempt}/{MAX_RETRIES}): {e}")
            if attempt == MAX_RETRIES:
                raise
            await asyncio.sleep(RETRY_DELAY)

    try:
        async for msg in consumer:
            payload = json.loads(msg.value.decode())
            texto = payload.get("texto", "")

            # Llamada al endpoint /extraer internamente
            documento = extraer(TextoEntrada(texto=texto))

            # Publicar documento final en topic de respuestas
            await producer.send_and_wait(RESPONSE_TOPIC, json.dumps(documento).encode())
    finally:
        await consumer.stop()
        await producer.stop()


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(consume_and_process())
