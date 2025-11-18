

import os
import json
import asyncio
import logging
import uuid
from typing import List, Optional

import aiohttp
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError, BaseModel
from dotenv import load_dotenv

# Cargar env
load_dotenv()

# Logging dinámico
log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_str, logging.INFO)
logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("generate-assertions-worker")

# Importa modelos pydantic
from common.async_models import (
    GenerateAssertionsRequest,
    AssertionsGeneratedResponse,
    Assertion,
    AssertionGeneratedPayload,
)

# ============================================================
# Config / constantes (desde env)
# ============================================================
AI_PROVIDER = os.getenv("AI_PROVIDER", "mistral").lower()
logger.info(f"Proveedor de IA seleccionado: {AI_PROVIDER.upper()}")

# Kafka
BROKER_URL = os.getenv("KAFKA_BROKER", os.getenv("KAFKA_BOOTSTRAP", "kafka:9092"))
INPUT_TOPIC = os.getenv("KAFKA_INPUT_TOPIC", os.getenv("ASSERTIONS_REQUEST_TOPIC", "fake_news_requests_generate"))
OUTPUT_TOPIC = os.getenv("KAFKA_OUTPUT_TOPIC", os.getenv("ASSERTIONS_RESPONSE_TOPIC", "fake_news_responses"))

# Mistral config
MISTRAL_API_URL = os.getenv("MISTRAL_API_URL", "")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-large-latest")
# Nuevo prompt: Pide explícitamente el array de objetos con las 3 claves necesarias (idAssertion, text, categoryId)
MISTRAL_PROMPT = os.getenv(
    "MISTRAL_PROMPT",
    "Extrae solo las aserciones verificables que contengan cifras objetivables y eliminen cualquier valoración subjetiva. "
    "Responde **EXCLUSIVAMENTE** con un array JSON de objetos que contengan las claves 'idAssertion' (string, debe ser un índice único y consecutivo empezando en '1'), 'text' (string) y 'categoryId' (integer, usa 1 para 'verificable'). NO incluyas ninguna otra clave o texto."
)

# Gemini config
GEMINI_API_URL = os.getenv("GEMINI_API_URL", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-preview-09-2025")
# Nuevo prompt: Menciona la estructura y el esquema para reforzar
GEMINI_PROMPT = os.getenv(
    "GEMINI_PROMPT",
    "Extrae solo las aserciones verificables que contengan cifras objetivables y eliminen cualquier valoración subjetiva. "
    "Devuelve un array JSON de objetos que cumplan con el esquema proporcionado. Asegúrate de generar valores para 'idAssertion', 'text' y 'categoryId'."
)

# Timeouts / retries
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY = float(os.getenv("RETRY_DELAY", "1.0"))

# ============================================================
# FastAPI
# ============================================================
app = FastAPI(title="Generate Assertions Worker (Typed)")

# ============================================================
# Helpers Pydantic JSON Schema
# ============================================================

def get_assertions_schema() -> dict:
    """Genera el JSON Schema para List[Assertion] que los LLM deben seguir."""
    # El esquema generado por Pydantic es suficiente para los LLM
    assertion_schema = Assertion.model_json_schema(by_alias=True)
    
    # Creamos el esquema para un array de esos objetos
    return {
        "type": "array",
        "items": assertion_schema,
    }

# ============================================================
# Llamada asíncrona a Mistral (aiohttp)
# ============================================================
async def call_mistral(text: str) -> List[Assertion]:
    """Llama a la API de Mistral y valida la respuesta como List[Assertion]."""
    if not (MISTRAL_API_URL and MISTRAL_API_KEY):
        raise HTTPException(status_code=500, detail="Mistral no está configurado en variables de entorno.")

    full_prompt = f"{MISTRAL_PROMPT}\n\nTexto a analizar:\n{text}"
    headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MISTRAL_MODEL,
        "messages": [{"role": "user", "content": full_prompt}],
        "temperature": 0.2,
        # Solicitar formato estructurado JSON
        "response_format": {"type": "json_object"}
    }

    async with aiohttp.ClientSession() as session:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with session.post(MISTRAL_API_URL, headers=headers, json=payload, timeout=HTTP_TIMEOUT) as resp:
                    text_resp = await resp.text()
                    if resp.status != 200:
                        logger.error(f"Mistral status {resp.status}: {text_resp}")
                        raise HTTPException(status_code=resp.status, detail="Error Mistral")
                    
                    data = await resp.json()
                    
                    # 1. Extraer el contenido (debe ser un string JSON)
                    try:
                        content = data["choices"][0]["message"]["content"]
                    except (KeyError, TypeError):
                        logger.error(f"Mistral response format unexpected: {data}")
                        raise ValueError("Estructura de respuesta Mistral inesperada.")
                    
                    # 2. Parsear el string JSON a una lista de diccionarios
                    try:
                        parsed_list = json.loads(content)
                        if not isinstance(parsed_list, list):
                             # Si es un dict, intentar ver si contiene la lista de aserciones.
                            if isinstance(parsed_list, dict) and "assertions" in parsed_list:
                                parsed_list = parsed_list["assertions"]
                            else:
                                raise ValueError("Mistral no devolvió un array JSON raíz.")

                    except json.JSONDecodeError:
                        logger.error(f"Mistral devolvió JSON inválido: {content}")
                        raise ValueError("Respuesta de Mistral no es JSON válido.")
                    
                    # 3. Validar y convertir la lista de diccionarios a List[Assertion]
                    try:
                        for idx, item in enumerate(parsed_list, start=1):
                            item["idAssertion"] = str(idx)
                        return [Assertion(**item) for item in parsed_list]
                    except ValidationError as e:
                        logger.error(f"Mistral devolvió un JSON que no cumple el esquema Assertion: {e}")
                        raise ValueError("Mistral devolvió un JSON con esquema incorrecto.")

            except HTTPException:
                raise
            except Exception as e:
                logger.warning(f"Intento {attempt} fallido Mistral: {e}")
                if attempt == MAX_RETRIES:
                    logger.exception("Fallo definitivo llamando a Mistral")
                    raise HTTPException(status_code=503, detail=str(e))
                await asyncio.sleep(RETRY_DELAY)
    return []


# ============================================================
# Llamada asíncrona a Gemini (aiohttp)
# ============================================================
async def call_gemini(text: str) -> List[Assertion]:
    """Llama a la API de Gemini, usando JSON Schema para forzar el modelo Assertion."""
    if not (GEMINI_API_URL and GEMINI_API_KEY):
        raise HTTPException(status_code=500, detail="Gemini no está configurado en variables de entorno.")

    full_prompt = f"{GEMINI_PROMPT}\n\nTexto a analizar:\n{text}"

    api_endpoint = f"{GEMINI_API_URL}/models/{GEMINI_MODEL}:generateContent"
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}

    # Usar el esquema JSON de Pydantic
    response_schema = get_assertions_schema()

    payload = {
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
            "responseSchema": response_schema
        }
    }


    async with aiohttp.ClientSession() as session:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with session.post(api_endpoint, headers=headers, json=payload, timeout=HTTP_TIMEOUT) as resp:
                    text_resp = await resp.text()
                    if resp.status != 200:
                        logger.error(f"Gemini status {resp.status}: {text_resp}")
                        raise HTTPException(status_code=resp.status, detail="Error Gemini")
                    
                    data = await resp.json()
                    
                    # 1. El JSON esperado contiene candidates -> content -> parts -> text (que es el string JSON)
                    try:
                        json_string = data["candidates"][0]["content"]["parts"][0]["text"]
                        parsed_list = json.loads(json_string)

                    except (KeyError, IndexError, json.JSONDecodeError) as e:
                        logger.error(f"Error parsing Gemini response structure or JSON: {e}; raw: {text_resp}")
                        raise ValueError("Respuesta de Gemini no contiene el JSON esperado.")

                    # 2. Validar y convertir la lista de diccionarios a List[Assertion]
                    # El LLM ya debería haber garantizado el formato gracias al responseSchema
                    if not isinstance(parsed_list, list):
                        raise ValueError("Gemini devolvió un tipo inesperado (no es lista JSON).")

                    try:
                        for idx, item in enumerate(parsed_list, start=1):
                            item["idAssertion"] = str(idx)
                        # Convertimos los dicts resultantes a modelos Pydantic
                        return [Assertion(**item) for item in parsed_list]
                    except ValidationError as e:
                        logger.error(f"Gemini devolvió un JSON que no cumple el esquema Assertion: {e}")
                        raise ValueError("Gemini devolvió un JSON con esquema incorrecto.")
            
            except HTTPException:
                raise
            except Exception as e:
                logger.warning(f"Intento {attempt} fallido Gemini: {e}")
                if attempt == MAX_RETRIES:
                    logger.exception("Fallo definitivo llamando a Gemini")
                    raise HTTPException(status_code=503, detail=str(e))
                await asyncio.sleep(RETRY_DELAY)
    return []

# ============================================================
# Dispatch a proveedor elegido
# ============================================================
# El tipo de retorno ahora es List[Assertion]
async def extract_assertions_from_text(text: str) -> List[Assertion]:
    if AI_PROVIDER == "mistral":
        return await call_mistral(text)
    elif AI_PROVIDER == "gemini":
        return await call_gemini(text)
    else:
        # Aquí puedes dejar un logger.warning para indicar que no hay proveedor
        return []

# ============================================================
# Procesar mensaje Kafka entrante
# ============================================================
async def process_message_bytes(message: bytes, producer: AIOKafkaProducer):
    try:
        payload_msg = json.loads(message.decode("utf-8"))
    except Exception as e:
        logger.error(f"Mensaje Kafka no JSON: {e}")
        return

    # Validar request mínimo con Pydantic (GenerateAssertionsRequest)
    try:
        req = GenerateAssertionsRequest(**payload_msg)
    except ValidationError as e:
        logger.error(f"Request inválido (no cumple GenerateAssertionsRequest): {e}")
        return

    logger.info(f"[{req.order_id}] Generando aserciones (provider={AI_PROVIDER})")
    
    # Llamada al LLM: ahora devuelve directamente objetos Assertion
    try:
        assertion_objs = await extract_assertions_from_text(req.payload.text)
    except HTTPException as he:
        logger.error(f"[{req.order_id}] Error LLM: {he.detail}")
        return
    except Exception as e:
        logger.exception(f"[{req.order_id}] Error inesperado extrayendo aserciones: {e}")
        return

    # Si la lista está vacía, no hacemos nada más
    if not assertion_objs:
        logger.info(f"[{req.order_id}] No se extrajeron aserciones.")
        return

    # NOTA: Ya no hay necesidad de 'structured_assertions' ni de iterar para crear Assertion(**a)
    # Los objetos ya están en assertion_objs

    # Construir respuesta tipada (AssertionsGeneratedResponse)
    try:
        payload = AssertionGeneratedPayload(
            text=req.payload.text,
            assertions=assertion_objs, # Se usa directamente la lista de modelos
            publisher=AI_PROVIDER
        )
        response = AssertionsGeneratedResponse(action="assertions_generated", order_id=req.order_id, payload=payload)
    except ValidationError as e:
        logger.exception(f"[{req.order_id}] Error validando AssertionsGeneratedResponse: {e}")
        return

    # Enviar al topic de respuestas
    try:
        msg_bytes = response.model_dump_json(exclude_none=True).encode("utf-8")
        await producer.send_and_wait(OUTPUT_TOPIC, msg_bytes)
        logger.info(f"[{req.order_id}] Publicado assertions_generated en topic {OUTPUT_TOPIC}")
    except Exception as e:
        logger.exception(f"[{req.order_id}] Error publicando en Kafka: {e}")

# ============================================================
# Consumer loop Kafka
# ============================================================
async def consume_and_process():
    consumer = AIOKafkaConsumer(
        INPUT_TOPIC,
        bootstrap_servers=BROKER_URL,
        group_id="generate-assertions-group",
        auto_offset_reset="earliest"
    )
    producer = AIOKafkaProducer(bootstrap_servers=BROKER_URL)

    # Intentos de arranque (retries)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await consumer.start()
            await producer.start()
            logger.info("✅ Conectado a Kafka correctamente")
            break
        except Exception as e:
            logger.warning(f"⚠️ Kafka no disponible (intento {attempt}/{MAX_RETRIES}): {e}")
            if attempt == MAX_RETRIES:
                logger.exception("No se pudo conectar a Kafka después de múltiples intentos")
                raise
            await asyncio.sleep(RETRY_DELAY)

    try:
        async for msg in consumer:
            try:
                await process_message_bytes(msg.value, producer)
            except Exception as e:
                logger.exception(f"Error procesando mensaje Kafka: {e}")
    finally:
        await consumer.stop()
        await producer.stop()
        logger.info("Kafka consumer y producer detenidos")

# ============================================================
# Endpoint HTTP (sin Kafka) para probar /extraer
# ============================================================
class TextoEntrada(BaseModel):
    text: str

@app.post("/extraer")
async def extraer_endpoint(body: TextoEntrada):
    """
    Endpoint para test rápido: devuelve AssertionsGeneratedResponse sin pasar por Kafka.
    """
    text = body.text
    order_id = str(uuid.uuid4())
    logger.info(f"[{order_id}] Endpoint /extraer (provider={AI_PROVIDER})")
    
    try:
        # Ahora devuelve directamente List[Assertion]
        assertion_objs = await extract_assertions_from_text(text)
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception("Error generando aserciones")
        raise HTTPException(status_code=500, detail=str(e))

    # Ya no hace falta estructurar/validar, usamos assertion_objs directamente
    try:
        payload = AssertionGeneratedPayload(text=text, assertions=assertion_objs, publisher=AI_PROVIDER)
        response = AssertionsGeneratedResponse(action="assertions_generated", order_id=order_id, payload=payload)
        return response
    except ValidationError as e:
        logger.exception("Error validando respuesta /extraer")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# Startup / shutdown
# ============================================================
@app.on_event("startup")
async def startup_event():
    # lanzar consumer en background
    asyncio.create_task(consume_and_process())
    logger.info("Background consume_and_process task started")

@app.on_event("shutdown")
async def shutdown_event():
    # nada explícito: aiokafka será detenido en consume_and_process finally
    logger.info("Shutdown requested")

# ============================================================
# Entrypoint (útil si arrancas este worker directamente)
# ============================================================
if __name__ == "__main__":
    import uvicorn
    logger.info("Iniciando worker (uvicorn) - FastAPI + Kafka consumer")
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8001")))