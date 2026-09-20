import os
import json
import asyncio
import logging
import math
import uuid
from typing import Any, List, Optional

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, ValidationError
from dotenv import load_dotenv
from common.utils.logging_utils import (
    configure_single_line_json_logging,
    exception_message,
    log_event,
)

# Cargar env
load_dotenv()

# Logging dinámico
log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_str, logging.INFO)
configure_single_line_json_logging(log_level)
logger = logging.getLogger("generate-assertions-worker")

# Importa modelos pydantic
from common.models.async_models import (
    GenerateAssertionsRequest,
    AssertionsGeneratedResponse,
    AssertionsNotGeneratedPayload,
    AssertionsNotGeneratedResponse,
    Assertion,
    AssertionGeneratedPayload,
    TextoEntrada,
    build_assertions_document_v2,
)
from common.models.protocol_models import CATEGORY_CATALOG_PROMPT
from common.routing_taxonomy import (
    EVIDENCE_KIND_PROMPT,
    TAXONOMY_VERSION,
    TOPIC_CATEGORY_PROMPT,
    TOPIC_PROMPT,
    EntityRole,
    EntityType,
    JurisdictionScope,
    TemporalType,
)
from common.utils.quotas_client import fetch_client_quotas as fetch_admin_client_quotas, update_client_consumed as update_admin_client_consumed
from common.utils.kafka_contracts import DEFAULT_KAFKA_BOOTSTRAP, DEFAULT_TOPIC_REQUESTS_GENERATE, DEFAULT_TOPIC_RESPONSES
from common.utils.llm_json import parse_model_list
from common.llm import LLMConfigurationError, LLMRequest, acomplete
from common.utils.llm_runtime import fetch_llm_runtime_override

# ============================================================
# Config / constantes (desde env)
# ============================================================
AI_PROVIDER = os.getenv("AI_PROVIDER", "mistral").lower()
log_event(
    logger,
    logging.INFO,
    "llm_provider_selected",
    provider=AI_PROVIDER,
)

# Kafka
BROKER_URL = os.getenv("KAFKA_BROKER", os.getenv("KAFKA_BOOTSTRAP", DEFAULT_KAFKA_BOOTSTRAP))
INPUT_TOPIC = os.getenv("KAFKA_INPUT_TOPIC", os.getenv("ASSERTIONS_REQUEST_TOPIC", DEFAULT_TOPIC_REQUESTS_GENERATE))
OUTPUT_TOPIC = os.getenv("KAFKA_OUTPUT_TOPIC", os.getenv("ASSERTIONS_RESPONSE_TOPIC", DEFAULT_TOPIC_RESPONSES))

# Mistral config
MISTRAL_API_URL = os.getenv("MISTRAL_API_URL", "")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "")

# Gemini config
GEMINI_API_URL = os.getenv("GEMINI_API_URL", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "")

# OpenRouter config
OPENROUTER_API_URL = os.getenv("OPENROUTER_API_URL", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "")

ADMIN_URL = os.getenv("ADMIN_URL", "http://admin:8000")

PROMPT = os.getenv(
    "PROMPT",
    "Pendiente de Configurar "
)

TEMPERATURE = float(os.getenv("TEMPERATURE", "0.1"))
MAX_ASSERTIONS = int(os.getenv("MAX_ASSERTIONS", "20"))
LLM_CONFIG_VERSION = int(os.getenv("LLM_CONFIG_VERSION", "0"))

def build_assertions_prompt(text: str) -> str:
    return (
        f"{PROMPT}\n\n"
        "CATEGORÍAS CANÓNICAS OBLIGATORIAS ALINEADAS CON BLOCKCHAIN:\n"
        f"{CATEGORY_CATALOG_PROMPT}\n\n"
        "El campo categoryId DEBE ser uno de esos enteros. "
        "No devuelvas un campo category, no traduzcas ni inventes categorías.\n\n"
        f"TOPIC_CODE CANÓNICO ({TAXONOMY_VERSION}):\n{TOPIC_PROMPT}\n\n"
        f"CATEGORYID PERMITIDOS PARA CADA TOPIC_CODE:\n{TOPIC_CATEGORY_PROMPT}\n\n"
        f"EVIDENCE_KIND CANÓNICO:\n{EVIDENCE_KIND_PROMPT}\n\n"
        "topic_code y evidence_kind DEBEN ser valores exactos de estas listas. "
        "Usa UNKNOWN si el texto no permite decidir y OTHER solo para un tema identificable fuera del catálogo.\n\n"
        "CONTEXTO DE VALIDACIÓN OBLIGATORIO:\n"
        "- Para cada aserción, rellena context.locations, context.entities y context.temporal_context con el contexto necesario para verificarla.\n"
        "- Marca origin=\"explicit\" cuando el dato aparece en el texto literal de la aserción.\n"
        "- Marca origin=\"inferred\" cuando el dato no aparece en la aserción pero se deduce del texto completo de la noticia.\n"
        "- Si una aserción tiene contexto explícito propio, ese contexto prima sobre cualquier contexto inferido de la noticia.\n"
        "- No inventes contexto externo al texto proporcionado; usa unknown/listas vacías si no hay base textual suficiente.\n"
        "- search_hints.search_keywords y search_hints.suggested_queries deben incorporar el contexto temporal, entidades y lugares relevantes para que un buscador externo pueda encontrar evidencias precisas.\n"
        "- Las queries sugeridas deben ser autónomas: deben poder buscarse sin leer el resto de la noticia.\n\n"
        "VALORES CANÓNICOS DEL CONTEXTO:\n"
        f"- EntityType: {', '.join(item.value for item in EntityType)}\n"
        f"- EntityRole: {', '.join(item.value for item in EntityRole)}\n"
        f"- JurisdictionScope: {', '.join(item.value for item in JurisdictionScope)}\n"
        f"- TemporalType: {', '.join(item.value for item in TemporalType)}\n"
        "- region_code debe usar el código ISO 3166-2 completo (por ejemplo, ES-CT para Catalunya).\n"
        "- Si jurisdiction contiene region_code, su scope debe ser REGION; COUNTRY no puede contener region_code.\n"
        "- No uses valores fuera de estas listas ni códigos territoriales abreviados no canónicos.\n\n"
        f"Texto a analizar:\n{text}\n\n"
        f"IMPRESCINDIBLE: Devuelve como máximo {MAX_ASSERTIONS} aserciones.\n"
    )

# Timeouts / retries
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "60"))
NUM_REINTENTOS = int(os.getenv("NUM_REINTENTOS", os.getenv("MAX_RETRIES", "3")))
MAX_RETRIES = NUM_REINTENTOS
RETRY_DELAY = float(os.getenv("RETRY_DELAY", "1.0"))

# ============================================================
# FastAPI
# ============================================================
app = FastAPI(title="Generate Assertions Worker (Typed)")

# ============================================================
# Admin config
# ============================================================
class AdminConfigResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    temperature: float
    config_version: int = 0
    credentials_configured: dict[str, bool]


class AdminConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    config_version: Optional[int] = None


def set_runtime_env(name: str, value: Any) -> None:
    if value is None:
        return
    os.environ[name] = str(value)


def normalize_provider(value: str) -> str:
    provider = str(value or "").strip().lower()
    allowed = {"mistral", "gemini", "openrouter"}
    if provider not in allowed:
        raise HTTPException(status_code=400, detail=f"Provider desconocido: {provider}. Valores permitidos: {', '.join(sorted(allowed))}")
    return provider


def normalize_positive_int(name: str, value: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        raise HTTPException(status_code=400, detail=f"{name} debe ser un entero.")
    if parsed <= 0:
        raise HTTPException(status_code=400, detail=f"{name} debe ser mayor que 0.")
    return parsed


def normalize_non_negative_float(name: str, value: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        raise HTTPException(status_code=400, detail=f"{name} debe ser numerico.")
    if not math.isfinite(parsed) or parsed < 0:
        raise HTTPException(status_code=400, detail=f"{name} no puede ser negativo.")
    return parsed


def normalize_admin_config_response() -> AdminConfigResponse:
    return AdminConfigResponse(
        provider=AI_PROVIDER,
        model=current_model(),
        temperature=TEMPERATURE,
        config_version=LLM_CONFIG_VERSION,
        credentials_configured={
            "mistral": bool(MISTRAL_API_KEY),
            "gemini": bool(GEMINI_API_KEY),
            "openrouter": bool(OPENROUTER_API_KEY),
        },
    )


def current_model() -> str:
    return {
        "mistral": MISTRAL_MODEL,
        "gemini": GEMINI_MODEL,
        "openrouter": OPENROUTER_MODEL,
    }.get(AI_PROVIDER, "")


# ============================================================
# Helpers Pydantic JSON Schema
# ============================================================


class AssertionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assertions: List[Assertion]


def get_assertions_schema() -> dict:
    """Genera el JSON Schema cerrado que los LLM deben seguir."""
    return AssertionBatch.model_json_schema(by_alias=True)


def parse_assertions_content(content) -> List[Assertion]:
    return parse_model_list(content, Assertion, list_key="assertions", id_field="idAssertion")


def build_assertions_llm_request(text: str, model: str) -> LLMRequest:
    """Build a provider-compatible request while keeping local validation strict."""
    request = {
        "prompt": build_assertions_prompt(text),
        "model": model,
        "temperature": TEMPERATURE,
        "response_model": AssertionBatch,
    }
    if AI_PROVIDER == "openrouter":
        # Gemini 2.5 Flash Lite via OpenRouter currently returns empty objects
        # for both the full and minimal strict json_schema contracts. Prompted
        # JSON remains populated and is still validated by response_model.
        request["json_mode"] = True
    else:
        request["response_schema"] = get_assertions_schema()
    return LLMRequest(**request)


async def _call_configured_llm(text: str) -> List[Assertion]:
    model = {
        "mistral": MISTRAL_MODEL,
        "gemini": GEMINI_MODEL,
        "openrouter": OPENROUTER_MODEL,
    }.get(AI_PROVIDER)
    if not model:
        return []
    try:
        response = await acomplete(
            AI_PROVIDER,
            build_assertions_llm_request(text, model),
        )
        return parse_assertions_content(response.content)
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=exception_message(exc)) from exc


# ============================================================
# Dispatch a proveedor elegido
# ============================================================
# El tipo de retorno ahora es List[Assertion]
async def extract_assertions_from_text(text: str) -> List[Assertion]:
    return await _call_configured_llm(text)


async def publish_assertions_not_generated(
    producer: AIOKafkaProducer,
    order_id: str,
    text: str,
    error: str,
):
    payload = AssertionsNotGeneratedPayload(
        text=text,
        publisher=AI_PROVIDER,
        error=error,
        attempts=NUM_REINTENTOS,
    )
    response = AssertionsNotGeneratedResponse(
        action="assertions_not_generated",
        order_id=order_id,
        payload=payload,
    )
    msg_bytes = response.model_dump_json(exclude_none=True).encode("utf-8")
    await producer.send_and_wait(OUTPUT_TOPIC, msg_bytes)
    logger.info(f"[{order_id}] Publicado assertions_not_generated en topic {OUTPUT_TOPIC}")




def build_generated_document(
    text: str,
    assertions: List[Assertion],
    validation_mode,
    source_url: Optional[str] = None,
    source_domain: Optional[str] = None,
):
    return build_assertions_document_v2(
        text=text,
        assertions=[a.to_enriched() if hasattr(a, "to_enriched") else a for a in assertions],
        mode=validation_mode,
        provider=AI_PROVIDER,
        model={
            "mistral": MISTRAL_MODEL,
            "gemini": GEMINI_MODEL,
            "openrouter": OPENROUTER_MODEL,
        }.get(AI_PROVIDER),
        config_version=LLM_CONFIG_VERSION,
        source_url=source_url,
        source_domain=source_domain,
    )

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
        try:
            await publish_assertions_not_generated(producer, req.order_id, req.payload.text, str(he.detail))
        except Exception as e:
            logger.exception(f"[{req.order_id}] Error publicando assertions_not_generated: {e}")
        return
    except Exception as e:
        logger.exception(f"[{req.order_id}] Error inesperado extrayendo aserciones: {e}")
        try:
            await publish_assertions_not_generated(producer, req.order_id, req.payload.text, str(e))
        except Exception as publish_error:
            logger.exception(f"[{req.order_id}] Error publicando assertions_not_generated: {publish_error}")
        return

    # Si la lista está vacía, no hacemos nada más
    if not assertion_objs:
        logger.info(f"[{req.order_id}] No se extrajeron aserciones.")
        try:
            await publish_assertions_not_generated(
                producer,
                req.order_id,
                req.payload.text,
                "No se extrajeron aserciones.",
            )
        except Exception as e:
            logger.exception(f"[{req.order_id}] Error publicando assertions_not_generated: {e}")
        return

    # Construir respuesta tipada (AssertionsGeneratedResponse)
    try:
        assertions_document = build_generated_document(
            req.payload.text,
            assertion_objs,
            req.payload.validation_mode,
            req.payload.source_url,
            req.payload.source_domain,
        )
        log_event(
            logger,
            logging.INFO,
            "assertions_document_generated",
            provider=AI_PROVIDER,
            model={
                "mistral": MISTRAL_MODEL,
                "gemini": GEMINI_MODEL,
                "openrouter": OPENROUTER_MODEL,
            }.get(AI_PROVIDER),
            assertions=len(assertions_document.assertions),
        )
        for assertion in assertions_document.assertions:
            logger.debug(
                "[generate-asertions] assertion_id=%s categoryId=%s "
                "topic_code=%s evidence_kind=%s jurisdiction=%s entities=%s temporal=%s",
                assertion.assertion_id,
                assertion.categoryId,
                assertion.topic_code.value,
                assertion.evidence_kind.value,
                assertion.context.jurisdiction.routing_key(),
                [ent.name for ent in assertion.context.entities],
                [item.value for item in assertion.context.temporal_context],
            )
        payload = AssertionGeneratedPayload(
            assertions_document=assertions_document,
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
# Quotas cons 
# ============================================================


async def fetch_client_quotas(client_id: str) -> dict:
    return await fetch_admin_client_quotas(ADMIN_URL, client_id)

async def update_client_consumed(client_id: str, field: str, new_value: int):
    await update_admin_client_consumed(ADMIN_URL, client_id, field, new_value)

# ============================================================
# Endpoint HTTP 
# ============================================================
@app.get("/admin/config", response_model=AdminConfigResponse, tags=["Admin"])
def get_admin_config():
    """Consulta la configuracion runtime del generador de aserciones."""
    return normalize_admin_config_response()


@app.put("/admin/config", tags=["Admin"])
async def update_admin_config(config: AdminConfigUpdate):
    """Hot-update non-secret LLM selection; credentials remain deployment-only."""
    global AI_PROVIDER, TEMPERATURE, LLM_CONFIG_VERSION
    global MISTRAL_MODEL, GEMINI_MODEL, OPENROUTER_MODEL

    new_provider = normalize_provider(config.provider) if config.provider is not None else AI_PROVIDER
    if config.model is not None and not config.model.strip():
        raise HTTPException(status_code=400, detail="MODEL no puede estar vacío")
    if config.provider is not None:
        AI_PROVIDER = new_provider
        set_runtime_env("AI_PROVIDER", AI_PROVIDER)
    if config.model is not None:
        model = config.model.strip()
        if new_provider == "mistral":
            MISTRAL_MODEL = model
            set_runtime_env("MISTRAL_MODEL", model)
        elif new_provider == "gemini":
            GEMINI_MODEL = model
            set_runtime_env("GEMINI_MODEL", model)
        else:
            OPENROUTER_MODEL = model
            set_runtime_env("OPENROUTER_MODEL", model)
    if config.temperature is not None:
        TEMPERATURE = normalize_non_negative_float("TEMPERATURE", config.temperature)
        set_runtime_env("TEMPERATURE", TEMPERATURE)
    if config.config_version is not None:
        LLM_CONFIG_VERSION = normalize_positive_int("LLM_CONFIG_VERSION", config.config_version)
        set_runtime_env("LLM_CONFIG_VERSION", LLM_CONFIG_VERSION)

    log_event(
        logger,
        logging.INFO,
        "runtime_config_updated",
        provider=AI_PROVIDER,
        model=current_model(),
        config_version=LLM_CONFIG_VERSION,
        temperature=TEMPERATURE,
    )
    return {
        "status": "ok",
        "message": "Configuracion actualizada correctamente.",
        "config": normalize_admin_config_response().model_dump(mode="json"),
    }


@app.post("/extraer")
async def extraer_texto(
    body: TextoEntrada,
    client_id: str = Query(..., description="ID del cliente para cuotas") 
):
    # ================================================================
    # 1️⃣ Control de Cuotas PRE-Extracción
    # ================================================================
    try:
        quotas = await fetch_client_quotas(client_id)
        cons_news = quotas.get("consumed", {}).get("news_generation", 0)
        lim_news = quotas.get("limits", {}).get("news_generation", 0)

        if cons_news >= lim_news:
            logger.warning(f"⛔ QUOTA_EXCEDED para {client_id} en /extraer. ({cons_news}/{lim_news})")
            raise HTTPException(status_code=429, detail="Quota news_generation exceded")
            
    except HTTPException as he:
        raise he # Re-lanzar error 429
    except Exception as e:
        logger.error(f"❌ Error validando cuotas en /extraer: {e}")
        raise HTTPException(status_code=500, detail="Error interno verificando cuotas.")
    
    text = body.text
    order_id = str(uuid.uuid4())
    logger.info(f"[{order_id}] Endpoint /extraer (provider={AI_PROVIDER})")
    
    try:
        assertion_objs = await extract_assertions_from_text(text)
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception("Error generando aserciones")
        raise HTTPException(status_code=500, detail=str(e))

    try:
        await update_client_consumed(client_id, "news_generation", cons_news + 1)
        logger.info(f"💰 Cuota news_generation incrementada a {cons_news + 1} para {client_id} (Endpoint: /extraer)")
    except Exception as e:
        logger.error(f"❌ Error incrementando cuota en /extraer para {client_id}: {e}")
        # No bloqueamos el return aunque falle la actualización, para no perjudicar al usuario si la BBDD de cuotas falla puntualmente.

    try:
        assertions_document = build_generated_document(text, assertion_objs, "BLOCKCHAIN")
        payload = AssertionGeneratedPayload(assertions_document=assertions_document)
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
    override = await fetch_llm_runtime_override(ADMIN_URL, "llm:generate-asertions", logger)
    if override:
        try:
            await update_admin_config(AdminConfigUpdate(**override))
            logger.info("Applied persisted LLM runtime override for generate-asertions")
        except Exception as exc:
            logger.warning("Invalid persisted LLM runtime override; using deployment defaults: %s", exc.__class__.__name__)
    # lanzar consumer en background
    asyncio.create_task(consume_and_process())
    logger.info("Background consume_and_process task started")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutdown requested")

# ============================================================
# Entrypoint (útil si arrancas este worker directamente)
# ============================================================
if __name__ == "__main__":
    import uvicorn
    logger.info("Iniciando worker (uvicorn) - FastAPI + Kafka consumer")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8001")),
        log_config=None,
    )
