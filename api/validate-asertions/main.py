import os
import json
import uuid
import logging
import asyncio
import time

from typing import List, Tuple, Optional, Dict, Any
from datetime import datetime, timezone
from hexbytes import HexBytes


import httpx
from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv
from web3 import Web3
from abc import ABC, abstractmethod

from common.utils.blockchain import send_signed_tx, wait_for_receipt_blocking, send_and_wait, receipt_succeeded, require_successful_receipt
from common.utils.hash_utils import hash_text_to_multihash, multihash_to_base58,multihash_to_base58_dict, uuid_to_uint256,safe_multihash_to_tuple,cid_to_multihash_tuple
from common.models.veredicto import Veredicto, Validacion
from common.models.async_models import VerifyInputModel, ValidatorAPIResponse,ValidatorRegistrationInput,Multihash, ValidatorConfig, ValidatorType, ValidatorStatus, LightValidationRequest, LightValidationResponse, ValidationMode, ValidatorConfigEvent, ValidatorConfigEventPayload
from common.utils.kafka_contracts import DEFAULT_KAFKA_BOOTSTRAP, DEFAULT_TOPIC_LIGHT_VALIDATION_REQUESTS, DEFAULT_TOPIC_RESPONSES, kafka_security_kwargs as build_kafka_security_kwargs
from common.utils.ipfs_client import upload_bytes_to_ipfs, upload_json_to_ipfs as upload_json_payload_to_ipfs
from common.utils.llm_json import strip_json_markdown
from pydantic import BaseModel, ValidationError
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer


# =========================================================
# Cargar .env y configurar logger
# =========================================================
load_dotenv()

class ProviderModelFilter(logging.Filter):
    """
    Filtro dinámico para inyectar AI_PROVIDER y MODEL en cada log.
    """
    def filter(self, record):
        provider = globals().get("AI_PROVIDER", os.getenv("AI_PROVIDER", "mistral")).upper()
        
        validator = globals().get("ai_validator")
        if validator and hasattr(validator, "model"):
            model = validator.model
        else:
            model = os.getenv("MODEL", "unknown_model")
            
        record.provider_model = f"{provider}_{model}"
        return True

# 1. Configuramos el formato global
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(provider_model)s: %(message)s"
)

# 2. LA MAGIA AQUÍ: Inyectamos el filtro en todos los handlers raíz
for handler in logging.root.handlers:
    handler.addFilter(ProviderModelFilter())

# 3. Inicializamos nuestro logger (ya no hace falta ponerle el filtro a mano)
logger = logging.getLogger("validate-asertions")

# =========================================================
# Config blockchain y AI
# =========================================================
RPC_URL = os.getenv("RPC_URL")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
ACCOUNT_ADDRESS = Web3.to_checksum_address(os.getenv("ACCOUNT_ADDRESS"))
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS")
CONTRACT_ABI_PATH = os.getenv("CONTRACT_ABI_PATH", "TrustNews.json")

API_URL = os.getenv("API_URL")
AI_PROVIDER = os.getenv("AI_PROVIDER", "mistral").lower()
DEFAULT_MEMORY_PROMPT = """Actúa como validador factual prudente.
Valida la aserción usando tu conocimiento general y razonamiento lógico.
No inventes información.
Si no puedes verificarlo con suficiente seguridad, devuelve UNKNOWN.
Devuelve exclusivamente JSON válido:
{
  "resultado": "TRUE | FALSE | UNKNOWN",
  "descripcion": "Justificación breve y objetiva"
}"""

DEFAULT_SEARCH_PROMPT = """Actúa como validador factual con búsqueda online.
Busca evidencias actuales en Internet cuando sea necesario.
Prioriza fuentes oficiales, agencias de noticias y fuentes reputadas.
Devuelve exclusivamente JSON válido:
{
  "resultado": "TRUE | FALSE | UNKNOWN",
  "descripcion": "Justificación breve y objetiva",
  "sources": [
    {
      "url": "string",
      "title": "string",
      "reason": "string"
    }
  ]
}"""

DEFAULT_RAG_PROMPT = """Actúa como validador factual estricto.
Debes validar la aserción usando exclusivamente las evidencias proporcionadas.
No uses conocimiento interno salvo razonamiento lógico básico.
No inventes fuentes.
No accedas a URLs externas.
Si las evidencias no son suficientes, devuelve UNKNOWN o INSUFFICIENT.
Devuelve exclusivamente JSON válido:
{
  "resultado": "TRUE | FALSE | UNKNOWN | SUPPORTED | REFUTED | INSUFFICIENT | CONFLICTED | PARTIAL",
  "descripcion": "Justificación breve y objetiva",
  "confidence": "HIGH | MEDIUM | LOW",
  "evidence_used": [
    {
      "source_id": "string",
      "url": "string",
      "supports": true,
      "reason": "string"
    }
  ]
}"""

LEGACY_VALIDATION_PROMPT = os.getenv("VALIDATION_PROMPT")
LLM_MEMORY_VALIDATION_PROMPT = os.getenv("LLM_MEMORY_VALIDATION_PROMPT", LEGACY_VALIDATION_PROMPT or DEFAULT_MEMORY_PROMPT)
LLM_SEARCH_VALIDATION_PROMPT = os.getenv("LLM_SEARCH_VALIDATION_PROMPT", LEGACY_VALIDATION_PROMPT or DEFAULT_SEARCH_PROMPT)
RAG_EVIDENCE_VALIDATION_PROMPT = os.getenv("RAG_EVIDENCE_VALIDATION_PROMPT", LEGACY_VALIDATION_PROMPT or DEFAULT_RAG_PROMPT)
VALIDATOR_NAME = os.getenv("VALIDATOR_NAME", f"default-{ACCOUNT_ADDRESS}")
VALIDATOR_TYPE = ValidatorType(int(os.getenv("VALIDATOR_TYPE", str(int(ValidatorType.LLM_MEMORY_VALIDATION)))))
USE_EVIDENCE_SEARCH = os.getenv("USE_EVIDENCE_SEARCH", "false").lower() == "true"
ONLINE_SEARCH_ENABLED = os.getenv("ONLINE_SEARCH_ENABLED", "false").lower() == "true"
EVIDENCE_SEARCH_URL = os.getenv("EVIDENCE_SEARCH_URL", "http://evidence-search.apis.svc.cluster.local:8074")
AUTOMATIC_VALIDATOR_TYPES = {
    ValidatorType.LLM_MEMORY_VALIDATION,
    ValidatorType.LLM_SEARCH_VALIDATION,
    ValidatorType.RAG_EVIDENCE_VALIDATION,
}
VALIDATOR_ACTIVE_DATE = os.getenv("VALIDATOR_ACTIVE_DATE", datetime.now(timezone.utc).isoformat())
VALIDATOR_UPDATED_DATE = os.getenv("VALIDATOR_UPDATED_DATE", VALIDATOR_ACTIVE_DATE)
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.3"))

KAFKA_BROKER = os.getenv("KAFKA_BROKER", os.getenv("KAFKA_BOOTSTRAP", DEFAULT_KAFKA_BOOTSTRAP))
KAFKA_USERNAME = os.getenv("KAFKA_USERNAME", "app")
KAFKA_PASSWORD = os.getenv("KAFKA_PASSWORD", "")
KAFKA_SECURITY_PROTOCOL = os.getenv("KAFKA_SECURITY_PROTOCOL", "SASL_PLAINTEXT")
KAFKA_MECHANISM = os.getenv("KAFKA_MECHANISM", "PLAIN")
TOPIC_LIGHT_VALIDATION_REQUESTS = os.getenv("TOPIC_LIGHT_VALIDATION_REQUESTS", DEFAULT_TOPIC_LIGHT_VALIDATION_REQUESTS)
TOPIC_RESPONSES = os.getenv("TOPIC_RESPONSES", os.getenv("KAFKA_RESPONSE_TOPIC", DEFAULT_TOPIC_RESPONSES))
light_consumer: Optional[AIOKafkaConsumer] = None
light_producer: Optional[AIOKafkaProducer] = None

# =========================================================
# Parsear categorías
# =========================================================
try:
    VALIDATOR_CATEGORIES = json.loads(os.getenv("VALIDATOR_CATEGORIES", "[]"))
    VALIDATOR_CATEGORIES = [int(x) for x in VALIDATOR_CATEGORIES]
except Exception:
    VALIDATOR_CATEGORIES = []

# =========================================================
# Pydantic models
# =========================================================


class AdminConfigResponse(BaseModel):
    provider: str
    model: str
    categories: List[int]

class AdminConfigUpdate(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    categories: Optional[List[int]] = None

# =========================================================
# AI Validators
# =========================================================
class AIValidator(ABC):
    @abstractmethod
    def verificar_asercion(self, texto: str, contexto: Optional[str] = None, evidences: Optional[List[Dict[str, Any]]] = None) -> str:
        pass


def is_automatic_validator() -> bool:
    return VALIDATOR_TYPE in AUTOMATIC_VALIDATOR_TYPES


def selected_validation_prompt() -> str:
    if VALIDATOR_TYPE == ValidatorType.LLM_SEARCH_VALIDATION:
        return LLM_SEARCH_VALIDATION_PROMPT
    if VALIDATOR_TYPE == ValidatorType.RAG_EVIDENCE_VALIDATION:
        return RAG_EVIDENCE_VALIDATION_PROMPT
    return LLM_MEMORY_VALIDATION_PROMPT


def normalize_assertion_input(texto: Any, contexto: Optional[str] = None) -> Tuple[str, Optional[str]]:
    if isinstance(texto, dict):
        metadata = texto.get("metadata") or {}
        text_value = texto.get("text") or texto.get("assertion_text") or ""
        return str(text_value), contexto or json.dumps(metadata, ensure_ascii=False)
    return str(texto or ""), contexto


def format_evidences_for_prompt(evidences: Optional[List[Dict[str, Any]]]) -> str:
    if not evidences:
        return "No hay evidencias disponibles."
    lines = []
    for source in evidences:
        lines.append(
            f"- source_id={source.get('source_id', '')} | url={source.get('url', '')} | "
            f"title={source.get('title', '')} | excerpt={source.get('excerpt', '')}"
        )
    return "\n".join(lines)


def build_prompt_content(texto: Any, contexto: Optional[str] = None, evidences: Optional[List[Dict[str, Any]]] = None) -> str:
    assertion_text, context_text = normalize_assertion_input(texto, contexto)
    parts = [selected_validation_prompt()]
    if context_text:
        parts.append(f"Contexto de la noticia:\n{context_text}")
    if VALIDATOR_TYPE == ValidatorType.RAG_EVIDENCE_VALIDATION:
        parts.append(f"Evidencias proporcionadas:\n{format_evidences_for_prompt(evidences)}")
    parts.append(f"Aserción a validar:\n{assertion_text}")
    return "\n\n".join(parts)


def openrouter_model_for_current_type(model: str) -> str:
    if VALIDATOR_TYPE == ValidatorType.LLM_SEARCH_VALIDATION and ONLINE_SEARCH_ENABLED and not model.endswith(":online"):
        return f"{model}:online"
    return model


def fetch_evidences_for_assertion(assertion_text: str, contexto: Optional[str] = None, category: Optional[int] = None) -> List[Dict[str, Any]]:
    if VALIDATOR_TYPE != ValidatorType.RAG_EVIDENCE_VALIDATION or not USE_EVIDENCE_SEARCH:
        return []
    payload = {
        "order_id": None,
        "assertion_text": assertion_text,
        "temporal_context": contexto,
        "category": str(category) if category is not None else None,
        "max_sources": int(os.getenv("EVIDENCE_SEARCH_MAX_SOURCES", "5")),
    }
    try:
        resp = httpx.post(f"{EVIDENCE_SEARCH_URL.rstrip('/')}/search/evidences", json=payload, timeout=30.0)
        resp.raise_for_status()
        return resp.json().get("sources", []) or []
    except Exception as e:
        logger.warning(f"⚠️ evidence-search failed; RAG validator will answer with no evidences: {e}")
        return []

class MistralValidator(AIValidator):
    def __init__(self, api_url: str, api_key: str, model: str, temperature: float = 0.3):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.temperature = temperature

    def verificar_asercion(self, texto: str, contexto: Optional[str] = None, evidences: Optional[List[Dict[str, Any]]] = None) -> str:
        import requests
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        contenido = build_prompt_content(texto, contexto, evidences)
        data = {"model": self.model, "messages": [{"role": "user", "content": contenido}], "temperature": self.temperature}
        resp = requests.post(self.api_url, headers=headers, json=data)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

class GeminiValidator(AIValidator):
    def __init__(self, api_url: str, api_key: str, model: str, temperature: float = 0.3):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.temperature = temperature

    def verificar_asercion(self, texto: str, contexto: Optional[str] = None, evidences: Optional[List[Dict[str, Any]]] = None) -> str:
        prompt = build_prompt_content(texto, contexto, evidences)
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": self.temperature, "topK": 40, "topP": 0.8},
        }
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        resp = httpx.post(f"{self.api_url}/models/{self.model}:generateContent", headers=headers, json=payload)
        if resp.status_code == 200:
            result = resp.json()
            return result["candidates"][0]["content"]["parts"][0]["text"]
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

class OpenRouterValidator(AIValidator):
    def __init__(self, api_url: str, api_key: str, model: str, temperature: float = 0.3):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.temperature = temperature

    def verificar_asercion(self, texto: str, contexto: Optional[str] = None, evidences: Optional[List[Dict[str, Any]]] = None) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        contenido = build_prompt_content(texto, contexto, evidences)
        data = {"model": openrouter_model_for_current_type(self.model), "messages": [{"role": "user", "content": contenido}], "temperature": self.temperature}
        resp = httpx.post(self.api_url, headers=headers, json=data)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

class GrokValidator(AIValidator):
    def __init__(self, api_url: str, api_key: str, model: str, temperature: float = 0.3):
        # xAI usa el formato estándar de OpenAI
        self.api_url = api_url if api_url else "https://api.x.ai/v1/chat/completions"
        self.api_key = api_key
        self.model = model
        self.temperature = temperature

    def verificar_asercion(self, texto: str, contexto: Optional[str] = None, evidences: Optional[List[Dict[str, Any]]] = None) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        contenido = build_prompt_content(texto, contexto, evidences)
        data = {"model": self.model, "messages": [{"role": "user", "content": contenido}], "temperature": self.temperature}
        
        # Usamos httpx igual que en OpenRouter
        resp = httpx.post(self.api_url, headers=headers, json=data, timeout=30.0)
        
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    
def build_ai_validator() -> Optional[AIValidator]:
    if not is_automatic_validator():
        logger.info(f"Validator type {VALIDATOR_TYPE.name} only registers on-chain; AI client disabled")
        return None
    if AI_PROVIDER == "none":
        raise RuntimeError("AI_PROVIDER must be different from 'none' for LLM validator types")
    if AI_PROVIDER == "mistral":
        return MistralValidator(API_URL, os.getenv("API_KEY"), os.getenv("MODEL", "mistral-tiny"), TEMPERATURE)
    elif AI_PROVIDER == "gemini":
        return GeminiValidator(API_URL, os.getenv("API_KEY"), os.getenv("MODEL", "gemini-1.5-flash"), TEMPERATURE)
    elif AI_PROVIDER == "openrouter":
        return OpenRouterValidator(API_URL, os.getenv("API_KEY"), os.getenv("MODEL", "gpt-4o-mini"), TEMPERATURE)
    elif AI_PROVIDER == "grok":
        return GrokValidator(API_URL, os.getenv("API_KEY"), os.getenv("MODEL", "grok-beta"), TEMPERATURE)
    else:
        raise RuntimeError(f"AI_PROVIDER desconocido: {AI_PROVIDER}")

def clean_ai_response_text(text: str) -> str:
    return strip_json_markdown(text)

ai_validator = build_ai_validator()
if ai_validator:
    logger.info(f"AI Validator inicializado: {AI_PROVIDER.upper()}")


def kafka_security_kwargs():
    return build_kafka_security_kwargs(
        KAFKA_SECURITY_PROTOCOL,
        KAFKA_MECHANISM,
        KAFKA_USERNAME,
        KAFKA_PASSWORD,
        logger,
    )


def parse_validator_api_response(result_text: str) -> Tuple[Validacion, str, Dict[str, Any]]:
    parsed_result = ValidatorAPIResponse(**json.loads(clean_ai_response_text(result_text)))
    normalized = parsed_result.resultado.upper()
    extras = {
        "resultado_raw": parsed_result.resultado,
        "confidence": parsed_result.confidence,
        "sources": parsed_result.sources or [],
        "evidence_used": parsed_result.evidence_used or [],
    }
    if normalized in {"TRUE", "SUPPORTED"}:
        return Validacion.TRUE, parsed_result.descripcion, extras
    if normalized in {"FALSE", "REFUTED"}:
        return Validacion.FALSE, parsed_result.descripcion, extras
    return Validacion.UNKNOWN, parsed_result.descripcion, extras


def validator_config_event_payload(
    ipfs_config_hash: Optional[str],
    source: str = "validate-asertions",
    status: ValidatorStatus = ValidatorStatus.Registered,
    categories: Optional[List[int]] = None,
    metrics_reset_at: Optional[str] = None,
) -> ValidatorConfigEvent:
    return ValidatorConfigEvent(
        payload=ValidatorConfigEventPayload(
            validator=ACCOUNT_ADDRESS,
            ipfs_hash=ipfs_config_hash,
            config=build_validator_config(status=status),
            categories=categories if categories is not None else (VALIDATOR_CATEGORIES or []),
            source=source,
            timestamp=datetime.now(timezone.utc).isoformat(),
            metrics_reset_at=metrics_reset_at
        )
    )


async def publish_validator_config_event(
    ipfs_config_hash: Optional[str],
    source: str = "validate-asertions",
    status: ValidatorStatus = ValidatorStatus.Registered,
    categories: Optional[List[int]] = None,
    metrics_reset_at: Optional[str] = None,
):
    msg = validator_config_event_payload(ipfs_config_hash, source=source, status=status, categories=categories, metrics_reset_at=metrics_reset_at)
    producer = None
    try:
        producer = AIOKafkaProducer(
            bootstrap_servers=KAFKA_BROKER,
            **kafka_security_kwargs()
        )
        await producer.start()
        await producer.send_and_wait(TOPIC_RESPONSES, msg.model_dump_json(exclude_none=True).encode("utf-8"))
        logger.info(
            f"📣 Validator config event sent | topic={TOPIC_RESPONSES} "
            f"validator={ACCOUNT_ADDRESS} categories={msg.payload.categories or []} source={source}"
        )
    except Exception as e:
        logger.warning(f"⚠️ Could not publish validator config event to news-handler: {e}")
    finally:
        if producer:
            try:
                await producer.stop()
            except Exception:
                pass


async def handle_light_validation_request(req: LightValidationRequest):
    payload = req.payload
    validator_id = str(payload.validator_id or "")
    if validator_id.lower() != ACCOUNT_ADDRESS.lower():
        return

    logger.info(
        f"[LIGHT] Request received | order_id={payload.order_id} "
        f"assertion={payload.assertion_index} validator={ACCOUNT_ADDRESS} category={payload.category}"
    )

    verdict = Validacion.UNKNOWN
    description = ""
    error = None
    extras = {}
    try:
        result_text, consulted_evidences = await asyncio.to_thread(
            verificar_asercion_con_evidencias,
            payload.assertion_text,
            payload.original_text,
            payload.category,
        )
        verdict, description, extras = parse_validator_api_response(result_text)
        if consulted_evidences and not extras.get("sources"):
            extras["sources"] = consulted_evidences
        if consulted_evidences and not extras.get("evidence_used"):
            extras["evidence_used"] = consulted_evidences
    except Exception as e:
        error = str(e)
        description = error
        logger.exception(
            f"[LIGHT] Error validating assertion | order_id={payload.order_id} "
            f"assertion={payload.assertion_index} validator={ACCOUNT_ADDRESS}"
        )

    response = LightValidationResponse(
        order_id=payload.order_id,
        payload={
            "order_id": payload.order_id,
            "validation_mode": ValidationMode.LIGHT,
            "assertion_index": payload.assertion_index,
            "idAssertion": payload.idAssertion,
            "validator_id": ACCOUNT_ADDRESS,
            "category": payload.category,
            "verdict": verdict,
            "description": description,
            "confidence": extras.get("confidence"),
            "sources": extras.get("sources", []),
            "evidence_used": extras.get("evidence_used", []),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": payload.correlation_id,
            "error": error
        }
    )
    await light_producer.send_and_wait(TOPIC_RESPONSES, response.model_dump_json().encode("utf-8"))
    logger.info(
        f"[LIGHT] Response sent | order_id={payload.order_id} assertion={payload.assertion_index} "
        f"validator={ACCOUNT_ADDRESS} category={payload.category} verdict={int(verdict)}"
    )


async def consume_light_validation_requests():
    global light_consumer, light_producer
    light_consumer = AIOKafkaConsumer(
        TOPIC_LIGHT_VALIDATION_REQUESTS,
        bootstrap_servers=KAFKA_BROKER,
        group_id=f"validate-asertions-light-{ACCOUNT_ADDRESS.lower()}",
        auto_offset_reset="earliest",
        **kafka_security_kwargs()
    )
    light_producer = AIOKafkaProducer(
        bootstrap_servers=KAFKA_BROKER,
        **kafka_security_kwargs()
    )

    await light_consumer.start()
    await light_producer.start()
    logger.info(f"[LIGHT] Kafka consumer subscribed to {TOPIC_LIGHT_VALIDATION_REQUESTS} as {ACCOUNT_ADDRESS}")

    try:
        async for msg in light_consumer:
            try:
                data = json.loads(msg.value.decode("utf-8"))
                req = LightValidationRequest(**data)
                if req.payload.validation_mode != ValidationMode.LIGHT:
                    continue
                await handle_light_validation_request(req)
            except ValidationError as e:
                logger.warning(f"[LIGHT] Invalid Kafka request ignored: {e}")
            except Exception as e:
                logger.exception(f"[LIGHT] Error processing Kafka request: {e}")
    finally:
        await light_consumer.stop()
        await light_producer.stop()

# =========================================================
# Web3 + contrato
# =========================================================
w3 = Web3(Web3.HTTPProvider(RPC_URL))
with open(CONTRACT_ABI_PATH, "r", encoding="utf-8") as fh:
    artifact = json.load(fh)
abi = artifact.get("abi", artifact)
contract = w3.eth.contract(address=Web3.to_checksum_address(CONTRACT_ADDRESS), abi=abi)

logger.info(f"Conectado a blockchain: {w3.is_connected()} - Account: {ACCOUNT_ADDRESS} - Contract: {CONTRACT_ADDRESS}")

# =========================================================
# FastAPI app
# =========================================================
app = FastAPI(title="Validate Asertions API")

# =========================================================
# Funciones internas
# =========================================================
def verificar_asercion_con_evidencias(texto: Any, contexto: Optional[str] = None, category: Optional[int] = None) -> tuple[str, List[Dict[str, Any]]]:
    if not is_automatic_validator() or ai_validator is None:
        raise RuntimeError(f"Validator type {VALIDATOR_TYPE.name} does not execute automatic LLM validation")
    assertion_text, normalized_context = normalize_assertion_input(texto, contexto)
    evidences = fetch_evidences_for_assertion(assertion_text, normalized_context, category)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return ai_validator.verificar_asercion(assertion_text, normalized_context, evidences), evidences
        except HTTPException as e:
            # Si es un error de Rate Limit (429), esperamos y reintentamos
            if e.status_code == 429:
                if attempt < max_retries - 1:
                    wait_time = 10 ** attempt  # Espera 1s, luego 2s...
                    logger.warning(f"⚠️ API Rate Limit (429). Reintentando en {wait_time}s (Intento {attempt + 1}/{max_retries})...")
                    time.sleep(wait_time)
                    continue
            # Si es otro error o ya superamos los intentos, lanzamos la excepción
            logger.error(f"❌ Error devuelto por la API de IA - HTTP {e.status_code}: {e.detail}")
            raise e


def verificar_asercion(texto: Any, contexto: Optional[str] = None, category: Optional[int] = None) -> str:
    result_text, _ = verificar_asercion_con_evidencias(texto, contexto, category)
    return result_text

async def upload_validation_to_ipfs(validation_doc_bytes: bytes) -> str:
    ipfs_api_url = os.getenv("IPFS_API_URL", "http://127.0.0.1:8000")
    return await upload_bytes_to_ipfs(ipfs_api_url, f"validation-{uuid.uuid4()}.json", validation_doc_bytes)


async def upload_json_to_ipfs(filename: str, payload: dict) -> str:
    ipfs_api_url = os.getenv("IPFS_API_URL", "http://127.0.0.1:8000")
    return await upload_json_payload_to_ipfs(ipfs_api_url, filename, payload)


def build_validator_config(status: ValidatorStatus = ValidatorStatus.Registered, end_date: Optional[str] = None, updated_date: Optional[str] = None) -> ValidatorConfig:
    return ValidatorConfig(
        name=VALIDATOR_NAME,
        type=VALIDATOR_TYPE,
        provider=AI_PROVIDER,
        model=ai_validator.model if ai_validator else os.getenv("MODEL", "none"),
        active_date=VALIDATOR_ACTIVE_DATE,
        updated_date=updated_date or VALIDATOR_UPDATED_DATE,
        end_date=end_date,
        status=status,
    )


async def upload_validator_config(status: ValidatorStatus = ValidatorStatus.Registered, end_date: Optional[str] = None, updated_date: Optional[str] = None) -> str:
    config = build_validator_config(status=status, end_date=end_date, updated_date=updated_date)
    return await upload_json_to_ipfs(f"validator-config-{ACCOUNT_ADDRESS}.json", config.model_dump(mode="json"))


def validator_config_ipfs_hash_from_chain() -> Optional[str]:
    try:
        val_info = contract.functions.validators(ACCOUNT_ADDRESS).call()
        if not val_info:
            return None
        ipfs_config = val_info[3] if len(val_info) > 3 else None
        if not ipfs_config:
            return None
        return multihash_to_base58_dict(ipfs_config)
    except Exception as e:
        logger.warning(f"No se pudo leer ipfsConfig del validador en blockchain: {e}")
        return None

async def registrar_validacion_internal(
    postId: Any,
    assertion_id: Any,
    veredicto: Veredicto
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Sube primero el documento de validación a IPFS
    y registra en blockchain el CID (multihash base58).
    """
    try:
        logger.info(f"Inicio registrar_validacion_internal -> postId: {postId}, assertion_id: {assertion_id}, veredicto: {veredicto}")  
        # -----------------------------------------
        # 1. Documento de validación
        # -----------------------------------------
        validation_doc = {
            "postId": str(postId),
            "assertionIndex": assertion_id+1,
            "validator": ACCOUNT_ADDRESS,
            "estado": int(veredicto.estado),
            "descripcion": veredicto.texto
        }

        validation_doc_bytes = json.dumps(
            validation_doc, ensure_ascii=False
        ).encode("utf-8")

        # -----------------------------------------
        # 2. Subir a IPFS → CID (base58)
        # -----------------------------------------
        validation_cid = await upload_validation_to_ipfs(
            validation_doc_bytes
        )

        logger.info(f"📦 Validación subida a IPFS: {validation_cid}")

        hash_function, hash_size, digest = cid_to_multihash_tuple(validation_cid)
        logger.info(f"hash_function: {hash_function.hex()}")
        logger.info(f"hash_size: {hash_size.hex()}")
        logger.info(f"digest length: {len(digest)}")

        # ------------------------------------------------
        # Construir llamada al contrato
        # ------------------------------------------------


        func_call = contract.functions.addValidation(
            postId,
            assertion_id ,
            int(veredicto.estado),
            (hash_function, hash_size, digest)   
        )

        tx_hash = send_signed_tx(w3, func_call, ACCOUNT_ADDRESS, PRIVATE_KEY)
        receipt = wait_for_receipt_blocking(w3, tx_hash)

        logger.info(f"⛓️ Validación registrada en blockchain: {tx_hash}")

        return tx_hash, receipt

    except Exception as e:
        logger.exception(f"❌ Error en registrar_validacion_internal: {e}")
        return None, None


def consultar_tx_status_internal(tx_hash: str) -> Dict[str, Any]:
    """Consulta receipt y devuelve un dict con status y detalles (no bloqueante)."""


    try:
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        if receipt is None:
            return {"status": "pending", "result": False, "tx_hash": tx_hash}

        # receipt exists
        status_val = getattr(receipt, "status", None)
        if status_val == 1:
            return {"status": "mined", "result": True, "tx_hash": tx_hash, "blockNumber": receipt.blockNumber}
        else:
            return {"status": "failed", "result": False, "tx_hash": tx_hash, "blockNumber": receipt.blockNumber}
    except Exception as e:
        logger.debug(f"consultar_tx_status_internal: receipt aún no disponible o error: {e}")
        return {"status": "pending", "result": False, "tx_hash": tx_hash}

# =========================================================
# Registrar validador (espera confirmación)
# =========================================================
def registrar_validador_blockchain(name: str, categories: List[int], ipfs_config_hash: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Registra validador y espera minado.
    Devuelve (tx_hash, receipt_dict) o (None, None) en error.
    Bloqueante: usar asyncio.to_thread en el event loop.
    """
    try:
        logger.info(f"Inicio registrar_validador_blockchain -> name: {name}, categories: {categories}, ipfs_config_hash: {ipfs_config_hash}")



        # Preparar llamada al contrato
        fn = contract.functions.registerValidator(name, categories, cid_to_multihash_tuple(ipfs_config_hash))

        # Enviar transacción
        tx_hash, receipt = send_and_wait(w3, fn, ACCOUNT_ADDRESS, PRIVATE_KEY)
        logger.info(f"Transacción enviada: {tx_hash}")
        logger.info(f"Receipt recibido: {receipt}")

        return tx_hash, receipt

    except Exception as e:
        logger.exception(f"Error al registrar validador en blockchain: {e}")
        return None, None



# =========================================================
# Actualizar configuración validador (espera confirmación)
# =========================================================
def update_validator_config_blockchain(ipfs_config_hash: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Actualiza el ipfs-config-hash del validador y espera minado.
    Devuelve (tx_hash, receipt_dict) o (None, None) en error.
    Bloqueante: usar asyncio.to_thread en el event loop.
    """
    try:
        logger.info(f"Inicio update_validator_config_blockchain -> ipfs_config_hash: {ipfs_config_hash}")
        fn = contract.functions.updateValidatorConfig(cid_to_multihash_tuple(ipfs_config_hash))
        tx_hash, receipt = send_and_wait(w3, fn, ACCOUNT_ADDRESS, PRIVATE_KEY)
        logger.info(f"Transacción enviada: {tx_hash}")
        logger.info(f"Receipt recibido: {receipt}")
        return tx_hash, receipt
    except Exception as e:
        logger.exception(f"Error al actualizar configuración del validador en blockchain: {e}")
        return None, None


# =========================================================
# Registrar validador (espera confirmación)
# =========================================================
def desregistrar_validador_blockchain() -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Registra validador y espera minado.
    Devuelve (tx_hash, receipt_dict) o (None, None) en error.
    Bloqueante: usar asyncio.to_thread en el event loop.
    """
    try:
        logger.info(f"Inicio desregistrar_validador_blockchain ")

        # Preparar llamada al contrato
        fn = contract.functions.unregisterValidator()

        # Enviar transacción
        tx_hash, receipt = send_and_wait(w3, fn, ACCOUNT_ADDRESS, PRIVATE_KEY)
        logger.info(f"Transacción enviada: {tx_hash}")
        logger.info(f"Receipt recibido: {receipt}")

        return tx_hash, receipt

    except Exception as e:
        logger.exception(f"Error al registrar validador en blockchain: {e}")
        return None, None


# =========================================================
# Endpoints HTTP
# =========================================================
@app.post("/verificar")
def endpoint_verificar(body: VerifyInputModel):
    resultado = verificar_asercion(body.text, body.context)
    return {"verificación": resultado}

@app.get("/tx/status/{tx_hash}")
async def endpoint_tx_status(tx_hash: str):
    receipt = w3.eth.get_transaction_receipt(tx_hash)
    if receipt is None:
        return {"status": "pending", "result": False, "tx_hash": tx_hash}
    return {"status": "mined" if receipt.status == 1 else "failed", "tx_hash": tx_hash, "blockNumber": receipt.blockNumber}

@app.post("/registrar_validador")
# ✅ Usando ValidatorRegistrationInput
async def endpoint_registrar_validador(input: ValidatorRegistrationInput):
    """Registra validador (usa VALIDATOR_CATEGORIES si no se pasan). Espera minado."""
    categorias = input.categories if input.categories is not None else VALIDATOR_CATEGORIES
    try:
        ipfs_config_hash = await upload_validator_config(status=ValidatorStatus.Registered)
        tx_hash, receipt = await asyncio.to_thread(registrar_validador_blockchain, input.name, categorias or [], ipfs_config_hash)
        if tx_hash is None:
            raise HTTPException(status_code=500, detail="Error registrando validador.")
        require_successful_receipt(receipt, "La transacción de registro del validador falló.")
        await publish_validator_config_event(ipfs_config_hash, source="registrar_validador", categories=categorias or [])
        return {"status": "ok", "tx_hash": tx_hash, "ipfs_config_hash": ipfs_config_hash, "receipt": receipt}
    except Exception as e:
        logger.exception(f"endpoint_registrar_validador error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/desregistrar_validador")
# ✅ Usando ValidatorRegistrationInput
async def endpoint_desregistrar_validador():
    """Desregistra validador. Espera minado."""
    try:
        end_date = datetime.now(timezone.utc).isoformat()
        ipfs_config_hash = await upload_validator_config(status=ValidatorStatus.Unregistered, end_date=end_date, updated_date=end_date)
        tx_update, receipt_update = await asyncio.to_thread(update_validator_config_blockchain, ipfs_config_hash)
        if tx_update is None:
            raise HTTPException(status_code=500, detail="Error actualizando configuración de baja del validador.")
        require_successful_receipt(receipt_update, "La transacción de actualización de baja del validador falló.")
        tx_hash, receipt = await asyncio.to_thread(desregistrar_validador_blockchain)
        if tx_hash is None:
            raise HTTPException(status_code=500, detail="Error desregistrando validador.")
        require_successful_receipt(receipt, "La transacción de desregistro del validador falló.")
        await publish_validator_config_event(ipfs_config_hash, source="desregistrar_validador", status=ValidatorStatus.Unregistered)
        return {"status": "ok", "update_tx_hash": tx_update, "unregister_tx_hash": tx_hash, "ipfs_config_hash": ipfs_config_hash, "receipt": receipt}
    except Exception as e:
        logger.exception(f"endpoint_desregistrar_validador error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/config", response_model=AdminConfigResponse, tags=["Admin"])
def get_admin_config():
    """Consulta la configuración actual del validador AI y sus categorías."""
    return AdminConfigResponse(
        provider=AI_PROVIDER,
        model=ai_validator.model if ai_validator else os.getenv("MODEL", "none"),
        categories=VALIDATOR_CATEGORIES
    )

@app.put("/admin/config", tags=["Admin"])
async def update_admin_config(config: AdminConfigUpdate):
    """
    Modifica provider, modelo y/o categorías. 
    Si las categorías cambian, realiza la re-inscripción en la blockchain.
    """
    # Usamos global para modificar el estado de la app en memoria
    global AI_PROVIDER, ai_validator, VALIDATOR_CATEGORIES

    # 1. Gestión del Provider y Modelo de IA
    old_provider = AI_PROVIDER
    old_model = ai_validator.model if ai_validator else os.getenv("MODEL", "none")
    new_provider = config.provider.lower() if config.provider else AI_PROVIDER
    new_model = config.model if config.model else (ai_validator.model if ai_validator else os.getenv("MODEL", "none"))
    model_config_changed = new_provider != old_provider or new_model != old_model
    metrics_reset_at = datetime.now(timezone.utc).isoformat() if model_config_changed else None

    # Si se solicitó un cambio en la IA, instanciamos de nuevo el objeto
    if config.provider or config.model:
        api_key = os.getenv("API_KEY") 
        api_url = API_URL
        
        try:
            if new_provider == "mistral":
                ai_validator = MistralValidator(api_url, api_key, new_model)
            elif new_provider == "gemini":
                ai_validator = GeminiValidator(api_url, api_key, new_model)
            elif new_provider == "openrouter":
                ai_validator = OpenRouterValidator(api_url, api_key, new_model)
            elif new_provider == "grok":
                ai_validator = GrokValidator(api_url, api_key, new_model)
            else:
                raise HTTPException(status_code=400, detail=f"Provider desconocido: {new_provider}")
            
            AI_PROVIDER = new_provider
            logger.info(f"🔄 AI Validator actualizado en memoria: {AI_PROVIDER.upper()} - Modelo: {new_model}")
        except Exception as e:
            logger.exception("Error al instanciar el nuevo AI Validator")
            raise HTTPException(status_code=500, detail="Error al cambiar el provider/modelo de IA.")

    # 2. Gestión de Categorías y Blockchain
    blockchain_receipts = {}

    if config.categories is not None and config.categories != VALIDATOR_CATEGORIES:
        logger.info(f"🔄 Cambio de categorías detectado: {VALIDATOR_CATEGORIES} -> {config.categories}. Se actualizará la configuración IPFS en blockchain.")
        VALIDATOR_CATEGORIES = config.categories

    if config.provider or config.model or config.categories is not None:
        updated_date = datetime.now(timezone.utc).isoformat()
        ipfs_config_hash = await upload_validator_config(status=ValidatorStatus.Registered, updated_date=updated_date)
        current_ipfs_hash = validator_config_ipfs_hash_from_chain()

        if current_ipfs_hash != ipfs_config_hash:
            tx_update, receipt_update = await asyncio.to_thread(update_validator_config_blockchain, ipfs_config_hash)
            if not tx_update:
                raise HTTPException(status_code=500, detail="Error actualizando ipfs-config-hash del validador en blockchain.")
            require_successful_receipt(receipt_update, "La transacción de actualización de configuración del validador falló.")
            blockchain_receipts["update_config_tx"] = tx_update
            blockchain_receipts["ipfs_config_hash"] = ipfs_config_hash
        else:
            blockchain_receipts["ipfs_config_hash"] = ipfs_config_hash
            logger.info("✅ Configuración IPFS ya registrada en blockchain; no se actualiza.")

    event_ipfs_hash = blockchain_receipts.get("ipfs_config_hash") if isinstance(blockchain_receipts, dict) else validator_config_ipfs_hash_from_chain()
    await publish_validator_config_event(event_ipfs_hash, source="admin_config", metrics_reset_at=metrics_reset_at)

    return {
        "status": "ok",
        "message": "Configuración actualizada correctamente.",
        "config": {
            "provider": AI_PROVIDER,
            "model": ai_validator.model if ai_validator else os.getenv("MODEL", "none"),
            "categories": VALIDATOR_CATEGORIES
        },
        "blockchain_updates": blockchain_receipts if blockchain_receipts else "Sin cambios en blockchain"
    }
    
# =========================================================
# Blockchain Event Agent
# =========================================================
class BlockchainEventAgent:
    def __init__(self, w3: Web3, contract, validator_address: str, ipfs_api: str):
        self.w3 = w3
        self.contract = contract
        self.validator = Web3.to_checksum_address(validator_address)
        self.ipfs_api = ipfs_api

    async def start(self):
        event_filter = self.contract.events.ValidationRequested.create_filter(
            fromBlock="latest",
            argument_filters={
                "validator": self.validator
            }
        )
        logger.info(f"🔔 Escuchando ValidationRequested solo para {self.validator}")

        while True:
            for event in event_filter.get_new_entries():
                await self.process_event(event)
            await asyncio.sleep(2)

    async def process_event(self, event):
        args = event["args"]
        if args["validator"] != self.validator:
            return
        post_id = args["postId"]
        assertion_index = args["asertionIndex"]
        multihash = args["postDocument"]
        cid = multihash_to_base58_dict(multihash)

        logger.info(f"📥 Validación solicitada post={post_id}, aserción={assertion_index}, cid={cid}")

        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.ipfs_api}/ipfs/{cid}")
            resp.raise_for_status()
            post_json = json.loads(resp.text)
            logger.info("🧩 JSON parseado correctamente desde IPFS")
            
            content_obj = json.loads(post_json.get("content", "{}"))

            # ------------------------------------------------
            # Buscar assertion correspondiente
            # ------------------------------------------------
            assertions = content_obj.get("assertions", [])
            logger.info(f"🔍 Total assertions encontradas en documento: {len(assertions)}")

            if assertion_index < 0 or assertion_index >= len(assertions):
                logger.warning(
                    f"⚠️ Assertion index fuera de rango | "
                    f"post={post_id} assertion={assertion_index}"
                )
                return

            assertion = assertions[assertion_index]

            logger.info(f"✅ Assertion localizada correctamente | assertion={assertion_index}")

            text = assertion.get("text", "")
            if not text:
                logger.warning(
                    f"⚠️ Assertion sin texto | "
                    f"post={post_id} assertion={assertion_index}"
                )
                return


            logger.info(
                f"📝 Texto assertion obtenido ({len(text)} chars) | "
                f"assertion={assertion_index}"
            )
            

        try:
            document = {
                "text": text,
                "metadata": content_obj.get("metadata", {})
            }
            result_text = await asyncio.to_thread(verificar_asercion, document)
            estado_enum, descripcion, _extras = parse_validator_api_response(result_text)

            veredicto = Veredicto(descripcion, estado_enum)
            tx_hash, receipt = await registrar_validacion_internal(post_id, assertion_index, veredicto)
            if receipt and receipt.get("status") == 1:
                logger.info(f"✅ Validación registrada en blockchain: {tx_hash}")
            else:
                logger.error(f"❌ Falló la transacción de validación para post {post_id}")
        except Exception as e:
            logger.exception(f"Error procesando validación: {e}")

# =========================================================
# Startup FastAPI
# =========================================================
@app.on_event("startup")
async def startup_event():
    ipfs_api_url = os.getenv("IPFS_API_URL", "http://127.0.0.1:8000")
    if is_automatic_validator():
        agent = BlockchainEventAgent(w3, contract, ACCOUNT_ADDRESS, ipfs_api_url)
        asyncio.create_task(agent.start())
        logger.info("🟢 Blockchain Event Agent iniciado")
        asyncio.create_task(consume_light_validation_requests())
        logger.info("[LIGHT] Kafka validation request listener started")
    else:
        logger.info(f"Validator type {VALIDATOR_TYPE.name}; automatic blockchain/Kafka validation listeners disabled")
    
        # registrar validador en startup (si no está registrado)

    try:
        # Comprobar registro existente (si la llamada falla, procedemos a registrar)
        try:
            val_info = contract.functions.validators(ACCOUNT_ADDRESS).call()
            already = val_info[2] if isinstance(val_info, (list, tuple)) and len(val_info) > 2 else False
            if already:
                logger.info("Validador ya registrado en blockchain.")
                ipfs_config_hash = await upload_validator_config(status=ValidatorStatus.Registered)
                current_ipfs_hash = validator_config_ipfs_hash_from_chain()
                if current_ipfs_hash != ipfs_config_hash:
                    logger.info(f"ipfs-config-hash distinto en blockchain: {current_ipfs_hash} -> {ipfs_config_hash}. Actualizando...")
                    tx_update, receipt_update = await asyncio.to_thread(update_validator_config_blockchain, ipfs_config_hash)
                    if not tx_update or not receipt_succeeded(receipt_update):
                        logger.error("Actualización de configuración del validador en startup falló; no se publica evento de caché.")
                        return
                await publish_validator_config_event(ipfs_config_hash, source="startup_existing")
                return
        except Exception as e:
            logger.warning(f"No se pudo comprobar validador (se intentará registrar): {e}")

        # Registrar usando VALIDATOR_CATEGORIES
        logger.info(
            f"Validador no encontrado -> registrando en startup. "
            f"Cuenta: {ACCOUNT_ADDRESS}, Categorías: {VALIDATOR_CATEGORIES or []} (esperando minado)..."
        )
        # Usar 'default-' como nombre si es el registro automático
        ipfs_config_hash = await upload_validator_config(status=ValidatorStatus.Registered)
        tx_hash, receipt = await asyncio.to_thread(registrar_validador_blockchain, VALIDATOR_NAME, VALIDATOR_CATEGORIES or [], ipfs_config_hash)
        if tx_hash and receipt_succeeded(receipt):
            logger.info(f"Validador registrado en startup: {tx_hash}")
            await publish_validator_config_event(ipfs_config_hash, source="startup_registered")
        elif tx_hash:
            logger.error(f"Registro de validador en startup falló en blockchain: tx={tx_hash}, receipt={receipt}")
        else:
            logger.error("Registro de validador en startup falló.")
    except Exception as e:
        logger.exception(f"Error en startup registrar validador: {e}")

