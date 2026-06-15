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
from common.models.protocol_models import (
    AssertionsDocumentV2,
    AssertionValidationPayloadV2,
    CategoryId,
    SourceDocumentStorage,
    build_assertion_validation_payload_v2,
    build_assertions_document_v2,
)
from common.utils.kafka_contracts import DEFAULT_KAFKA_BOOTSTRAP, DEFAULT_TOPIC_LIGHT_VALIDATION_REQUESTS, DEFAULT_TOPIC_RESPONSES, kafka_security_kwargs as build_kafka_security_kwargs
from common.utils.ipfs_client import upload_bytes_to_ipfs, upload_json_to_ipfs as upload_json_payload_to_ipfs
from common.utils.llm_json import strip_json_markdown
from pydantic import BaseModel, TypeAdapter, ValidationError
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
API_KEY = os.getenv("API_KEY")
AI_PROVIDER = os.getenv("AI_PROVIDER", "mistral").lower()
VALIDATOR_SERVICE_URL = os.getenv("VALIDATOR_SERVICE_URL", "")
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
Debes validar la aserción usando exclusivamente las evidencias y contextos proporcionados en el prompt.
No uses conocimiento interno salvo razonamiento lógico básico sobre el texto aportado.
No accedas a URLs externas ni supongas que una URL contiene información no incluida en los contextos.
No inventes fuentes, datos ni citas.
Si los contextos no contienen soporte directo ni contradicción directa para la aserción, responde UNKNOWN.
Devuelve exclusivamente JSON válido:
{
  "resultado": "TRUE | FALSE | UNKNOWN",
  "descripcion": "Justificación breve y objetiva",
  "confidence": "HIGH | MEDIUM | LOW",
  "evidence_used": [
    {
      "source_id": "string",
      "context_id": "string",
      "url": "string",
      "supports": true,
      "reason": "string"
    }
  ]
}"""


LLM_MEMORY_VALIDATION_PROMPT = os.getenv("LLM_MEMORY_VALIDATION_PROMPT", "")
LLM_SEARCH_VALIDATION_PROMPT = os.getenv("LLM_SEARCH_VALIDATION_PROMPT", "")
RAG_EVIDENCE_VALIDATION_PROMPT = os.getenv("RAG_EVIDENCE_VALIDATION_PROMPT", "")
VALIDATOR_NAME = os.getenv("VALIDATOR_NAME", f"default-{ACCOUNT_ADDRESS}")
VALIDATOR_TYPE = ValidatorType(int(os.getenv("VALIDATOR_TYPE", str(int(ValidatorType.LLM_MEMORY_VALIDATION)))))
USE_EVIDENCE_SEARCH = os.getenv("USE_EVIDENCE_SEARCH", "false").lower() == "true"
ONLINE_SEARCH_ENABLED = os.getenv("ONLINE_SEARCH_ENABLED", "false").lower() == "true"
EVIDENCE_SEARCH_URL = os.getenv("EVIDENCE_SEARCH_URL", "http://evidence-search.apis.svc.cluster.local:8074")
EVIDENCE_SEARCH_PREFERRED_PROFILE_ID = os.getenv("EVIDENCE_SEARCH_PREFERRED_PROFILE_ID", "default")
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
    VALIDATOR_CATEGORIES = TypeAdapter(List[CategoryId]).validate_python(VALIDATOR_CATEGORIES)
except Exception:
    VALIDATOR_CATEGORIES = []

# =========================================================
# Pydantic models
# =========================================================


class AdminConfigResponse(BaseModel):
    provider: str
    model: str
    categories: List[CategoryId]
    api_url: Optional[str] = None
    service_url: Optional[str] = None
    validator_type: int
    use_evidence_search: bool
    online_search_enabled: bool
    evidence_search_url: str
    evidence_search_use_preferred_domains: bool
    evidence_search_preferred_profile_id: str
    private_key: Optional[str] = None
    account_address: str
    api_key: Optional[str] = None

class AdminConfigUpdate(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    categories: Optional[List[CategoryId]] = None
    api_url: Optional[str] = None
    service_url: Optional[str] = None
    validator_type: Optional[int] = None
    use_evidence_search: Optional[bool] = None
    online_search_enabled: Optional[bool] = None
    evidence_search_url: Optional[str] = None
    evidence_search_use_preferred_domains: Optional[bool] = None
    evidence_search_preferred_profile_id: Optional[str] = None
    private_key: Optional[str] = None
    account_address: Optional[str] = None
    api_key: Optional[str] = None

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


def current_evidence_search_preferred_profile_id() -> str:
    return str(os.getenv("EVIDENCE_SEARCH_PREFERRED_PROFILE_ID", EVIDENCE_SEARCH_PREFERRED_PROFILE_ID) or "").strip() or "default"


def current_evidence_search_use_preferred_domains() -> bool:
    return os.getenv("EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS", "false").lower() == "true"


def mask_secret(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    return "*" * 8


def is_masked_secret(value: Optional[str]) -> bool:
    return bool(value) and set(str(value)) == {"*"}


def set_runtime_env(name: str, value: Any) -> None:
    if value is None:
        return
    os.environ[name] = str(value)


def normalize_validator_type(value: int) -> ValidatorType:
    try:
        return ValidatorType(int(value))
    except Exception:
        allowed = ", ".join(f"{int(v)}={v.name}" for v in ValidatorType)
        raise HTTPException(status_code=400, detail=f"VALIDATOR_TYPE inválido: {value}. Valores permitidos: {allowed}")


def reload_blockchain_client() -> None:
    global w3, contract
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    with open(CONTRACT_ABI_PATH, "r", encoding="utf-8") as fh:
        artifact = json.load(fh)
    abi = artifact.get("abi", artifact)
    contract = w3.eth.contract(address=Web3.to_checksum_address(CONTRACT_ADDRESS), abi=abi)
    logger.info(f"Conectado a blockchain: {w3.is_connected()} - Account: {ACCOUNT_ADDRESS} - Contract: {CONTRACT_ADDRESS}")


def normalize_account_address(value: str) -> str:
    try:
        return Web3.to_checksum_address(value)
    except Exception:
        raise HTTPException(status_code=400, detail="ACCOUNT_ADDRESS inválido.")


def normalize_admin_config_response() -> AdminConfigResponse:
    return AdminConfigResponse(
        provider=AI_PROVIDER,
        model=ai_validator.model if ai_validator else os.getenv("MODEL", "none"),
        categories=VALIDATOR_CATEGORIES,
        api_url=API_URL,
        service_url=VALIDATOR_SERVICE_URL or None,
        validator_type=int(VALIDATOR_TYPE),
        use_evidence_search=USE_EVIDENCE_SEARCH,
        online_search_enabled=ONLINE_SEARCH_ENABLED,
        evidence_search_url=EVIDENCE_SEARCH_URL,
        evidence_search_use_preferred_domains=current_evidence_search_use_preferred_domains(),
        evidence_search_preferred_profile_id=current_evidence_search_preferred_profile_id(),
        private_key=mask_secret(PRIVATE_KEY),
        account_address=ACCOUNT_ADDRESS,
        api_key=mask_secret(API_KEY),
    )


def normalize_assertion_input(texto: Any, contexto: Optional[str] = None) -> Tuple[str, Optional[str]]:
    if isinstance(texto, dict):
        metadata = texto.get("metadata") or {}
        text_value = texto.get("text") or texto.get("assertion_text") or ""
        return str(text_value), contexto or json.dumps(metadata, ensure_ascii=False)
    return str(texto or ""), contexto


def format_evidences_for_prompt(evidences: Optional[List[Dict[str, Any]]]) -> str:
    if not evidences:
        return "No hay evidencias disponibles."
    blocks = []
    for idx, source in enumerate(evidences, start=1):
        source_id = source.get("source_id") or f"source-{idx}"
        source_lines = [
            f"FUENTE {idx}",
            f"source_id: {source_id}",
            f"title: {source.get('title', '')}",
            f"url: {source.get('url', '')}",
            f"domain: {source.get('domain', '')}",
            f"source_type: {source.get('source_type', '')}",
            f"trust_score: {source.get('trust_score', '')}",
            f"why_selected: {source.get('why_selected', '')}",
        ]

        contexts = source.get("contexts") or []
        chunks = source.get("chunks") or []
        if contexts:
            for context_idx, context in enumerate(contexts, start=1):
                source_lines.extend([
                    f"CONTEXTO {context_idx}",
                    f"context_id: {context.get('context_id', '')}",
                    f"origin: {context.get('origin', '')}",
                    f"score: {context.get('score', '')}",
                    f"included_chunk_ids: {context.get('included_chunk_ids', [])}",
                    f"text: {context.get('text', '')}",
                ])
        elif chunks:
            for chunk_idx, chunk in enumerate(chunks, start=1):
                source_lines.extend([
                    f"CONTEXTO {chunk_idx}",
                    f"context_id: {chunk.get('context_id') or chunk.get('chunk_id', '')}",
                    f"origin: {chunk.get('origin', 'chunk')}",
                    f"score: {chunk.get('score', '')}",
                    f"included_chunk_ids: {chunk.get('included_chunk_ids') or [chunk.get('chunk_id')] if chunk.get('chunk_id') else []}",
                    f"text: {chunk.get('text', '')}",
                ])
        else:
            snippet = source.get("snippet") or source.get("excerpt") or source.get("content") or ""
            source_lines.extend([
                "CONTEXTO 1",
                "context_id: ",
                "origin: legacy_snippet",
                "score: ",
                "included_chunk_ids: []",
                f"text: {snippet}",
            ])
        blocks.append("\n".join(source_lines))
    return "\n\n".join(blocks)


def build_prompt_content(texto: Any, contexto: Optional[str] = None, evidences: Optional[List[Dict[str, Any]]] = None) -> str:
    assertion_text, context_text = normalize_assertion_input(texto, contexto)
    parts = [selected_validation_prompt()]
    if context_text:
        parts.append(f"Contexto de la noticia:\n{context_text}")
    if VALIDATOR_TYPE == ValidatorType.RAG_EVIDENCE_VALIDATION:
        parts.append(f"Evidencias proporcionadas:\n{format_evidences_for_prompt(evidences)}")
    parts.append(f"Aserción a validar:\n{assertion_text}")
    return "\n\n".join(parts)



def payload_context_for_prompt(payload_v2: AssertionValidationPayloadV2) -> str:
    return json.dumps({
        "mode": payload_v2.mode,
        "post_id": payload_v2.post_id,
        "assertion": payload_v2.assertion.model_dump(mode="json"),
        "source_document": payload_v2.source_document.model_dump(mode="json"),
    }, ensure_ascii=False)


def validate_payload_v2(payload_v2: AssertionValidationPayloadV2) -> tuple[Validacion, str, Dict[str, Any], Optional[Dict[str, Any]]]:
    if not is_automatic_validator() or ai_validator is None:
        raise RuntimeError(f"Validator type {VALIDATOR_TYPE.name} does not execute automatic LLM validation")
    logger.info(f"[validate-asertions] received assertion-validation-payload-v2 mode={payload_v2.mode} assertion_id={payload_v2.assertion.assertion_id}")
    evidences, evidence_response = fetch_evidences_for_payload(payload_v2)
    result_text = ai_validator.verificar_asercion(
        payload_v2.assertion.text,
        payload_context_for_prompt(payload_v2),
        evidences,
    )
    verdict, description, extras = parse_validator_api_response(result_text)
    if evidences and not extras.get("sources"):
        extras["sources"] = evidences
    if evidences and not extras.get("evidence_used"):
        extras["evidence_used"] = evidences
    return verdict, description, extras, evidence_response

def openrouter_model_for_current_type(model: str) -> str:
    if VALIDATOR_TYPE == ValidatorType.LLM_SEARCH_VALIDATION and ONLINE_SEARCH_ENABLED and not model.endswith(":online"):
        return f"{model}:online"
    return model


def current_evidence_search_policy() -> Dict[str, Any]:
    use_preferred_domains = current_evidence_search_use_preferred_domains()
    policy = {
        "mode": "official_first",
        "use_preferred_domains": use_preferred_domains,
        "max_domains": int(os.getenv("EVIDENCE_SEARCH_MAX_DOMAINS", "8")),
        "max_results": int(os.getenv("EVIDENCE_SEARCH_MAX_SOURCES", "5")),
        "max_queries_per_domain": int(os.getenv("EVIDENCE_SEARCH_MAX_QUERIES_PER_DOMAIN", "2")),
        "fallback_to_general_search": True,
    }
    if use_preferred_domains:
        policy["preferred_profile_id"] = current_evidence_search_preferred_profile_id()
    return policy


def fetch_evidences_for_payload(payload_v2: AssertionValidationPayloadV2) -> tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if VALIDATOR_TYPE != ValidatorType.RAG_EVIDENCE_VALIDATION or not USE_EVIDENCE_SEARCH:
        return [], None
    search_policy = current_evidence_search_policy()
    request_payload = {
        "schema_version": "evidence-search-request-v2",
        "assertion": payload_v2.assertion.model_dump(mode="json"),
        "search_policy": search_policy,
    }
    try:
        logger.info(f"[validate-asertions] validator_type=RAG_EVIDENCE_VALIDATION calling evidence-search")
        resp = httpx.post(f"{EVIDENCE_SEARCH_URL.rstrip('/')}/search/evidence", json=request_payload, timeout=30.0)
        resp.raise_for_status()
        response = resp.json()
        response.setdefault("search_policy", search_policy)
        return response.get("evidences", []) or response.get("sources", []) or [], response
    except Exception as e:
        logger.warning(f"⚠️ evidence-search failed; RAG validator will answer with no evidences: {e}")
        return [], None

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
        return MistralValidator(API_URL, API_KEY, os.getenv("MODEL", "mistral-tiny"), TEMPERATURE)
    elif AI_PROVIDER == "gemini":
        return GeminiValidator(API_URL, API_KEY, os.getenv("MODEL", "gemini-1.5-flash"), TEMPERATURE)
    elif AI_PROVIDER == "openrouter":
        return OpenRouterValidator(API_URL, API_KEY, os.getenv("MODEL", "gpt-4o-mini"), TEMPERATURE)
    elif AI_PROVIDER == "grok":
        return GrokValidator(API_URL, API_KEY, os.getenv("MODEL", "grok-beta"), TEMPERATURE)
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
    if normalized in {"TRUE"}:
        return Validacion.TRUE, parsed_result.descripcion, extras
    if normalized in {"FALSE"}:
        return Validacion.FALSE, parsed_result.descripcion, extras
    return Validacion.UNKNOWN, parsed_result.descripcion, extras


def validator_config_event_payload(
    ipfs_config_hash: Optional[str],
    source: str = "validate-asertions",
    status: ValidatorStatus = ValidatorStatus.Registered,
    categories: Optional[List[CategoryId]] = None,
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
    categories: Optional[List[CategoryId]] = None,
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
        f"assertion={payload.assertion_index} validator={ACCOUNT_ADDRESS} category={payload.categoryId}"
    )

    verdict = Validacion.UNKNOWN
    description = ""
    error = None
    extras = {}
    try:
        if payload.assertion_validation_payload is None:
            raise ValueError("Missing assertion-validation-payload-v2 in LIGHT request")
        verdict, description, extras, evidence_response = await asyncio.to_thread(
            validate_payload_v2,
            payload.assertion_validation_payload,
        )
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
            "categoryId": payload.categoryId,
            "verdict": verdict,
            "description": description,
            "confidence": extras.get("confidence"),
            "sources": extras.get("sources", []),
            "evidence_used": extras.get("evidence_used", []),
            "assertion_validation_payload": payload.assertion_validation_payload.model_dump(mode="json") if payload.assertion_validation_payload else None,
            "evidence_search_response": evidence_response if 'evidence_response' in locals() else None,
            "search_policy": current_evidence_search_policy() if USE_EVIDENCE_SEARCH else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": payload.correlation_id,
            "error": error
        }
    )
    await light_producer.send_and_wait(TOPIC_RESPONSES, response.model_dump_json().encode("utf-8"))
    logger.info(
        f"[LIGHT] Response sent | order_id={payload.order_id} assertion={payload.assertion_index} "
        f"validator={ACCOUNT_ADDRESS} category={payload.categoryId} verdict={int(verdict)}"
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
reload_blockchain_client()

# =========================================================
# FastAPI app
# =========================================================
app = FastAPI(title="Validate Asertions API")

# =========================================================
# Funciones internas
# =========================================================
def verificar_asercion_con_evidencias(texto: Any, contexto: Optional[str] = None) -> tuple[str, List[Dict[str, Any]]]:
    if isinstance(texto, dict) and texto.get("schema_version") == "assertion-validation-payload-v2":
        payload_v2 = AssertionValidationPayloadV2(**texto)
        verdict, description, extras, _evidence_response = validate_payload_v2(payload_v2)
        return json.dumps({"resultado": verdict.name, "descripcion": description, **extras}, ensure_ascii=False), extras.get("sources", []) or extras.get("evidence_used", []) or []
    raise ValueError("validate-asertions accepts assertion-validation-payload-v2 for automatic validation flows")


def verificar_asercion(texto: Any, contexto: Optional[str] = None) -> str:
    result_text, _ = verificar_asercion_con_evidencias(texto, contexto)
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
        service_url=VALIDATOR_SERVICE_URL or None,
        active_date=VALIDATOR_ACTIVE_DATE,
        updated_date=updated_date or VALIDATOR_UPDATED_DATE,
        end_date=end_date,
        status=status,
        use_evidence_search=USE_EVIDENCE_SEARCH,
        evidence_search_use_preferred_domains=current_evidence_search_use_preferred_domains(),
        evidence_search_preferred_profile_id=current_evidence_search_preferred_profile_id(),
        online_search_enabled=ONLINE_SEARCH_ENABLED,
        evidence_search_url=EVIDENCE_SEARCH_URL,
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
    veredicto: Veredicto,
    extras: Optional[Dict[str, Any]] = None,
    evidence_response: Optional[Dict[str, Any]] = None,
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
        extras = extras or {}
        validation_doc = {
            "postId": str(postId),
            "assertionIndex": assertion_id+1,
            "validator": ACCOUNT_ADDRESS,
            "estado": int(veredicto.estado),
            "descripcion": veredicto.texto,
            "sources": extras.get("sources", []),
            "evidence_used": extras.get("evidence_used", []),
            "evidence_search_response": evidence_response,
            "search_policy": current_evidence_search_policy() if USE_EVIDENCE_SEARCH else None,
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
def registrar_validador_blockchain(name: str, categories: List[CategoryId], ipfs_config_hash: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
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
    return normalize_admin_config_response()

@app.get("/health", tags=["Health"])
async def health():
    automatic = is_automatic_validator()
    ai_ready = ai_validator is not None
    if automatic and not ai_ready:
        raise HTTPException(status_code=503, detail="Automatic validator is not ready")
    return {
        "status": "ok",
        "validator": ACCOUNT_ADDRESS,
        "validator_type": int(VALIDATOR_TYPE),
        "automatic": automatic,
        "ai_ready": ai_ready,
        "categories": VALIDATOR_CATEGORIES,
    }

@app.put("/admin/config", tags=["Admin"])
async def update_admin_config(config: AdminConfigUpdate):
    """
    Modifica la configuración runtime del validador.
    Refresca la configuración IPFS/blockchain cuando cambian los campos públicos del validador.
    """
    global AI_PROVIDER, API_URL, API_KEY, PRIVATE_KEY, ACCOUNT_ADDRESS, VALIDATOR_TYPE, VALIDATOR_SERVICE_URL
    global USE_EVIDENCE_SEARCH, ONLINE_SEARCH_ENABLED, EVIDENCE_SEARCH_URL, EVIDENCE_SEARCH_PREFERRED_PROFILE_ID
    global ai_validator, VALIDATOR_CATEGORIES

    old_provider = AI_PROVIDER
    old_model = ai_validator.model if ai_validator else os.getenv("MODEL", "none")
    old_validator_type = VALIDATOR_TYPE
    old_service_url = VALIDATOR_SERVICE_URL
    old_use_evidence_search = USE_EVIDENCE_SEARCH
    old_online_search_enabled = ONLINE_SEARCH_ENABLED
    old_evidence_search_url = EVIDENCE_SEARCH_URL
    old_use_preferred_domains = current_evidence_search_use_preferred_domains()
    old_preferred_profile_id = current_evidence_search_preferred_profile_id()
    old_categories = list(VALIDATOR_CATEGORIES)

    new_provider = config.provider.lower() if config.provider else AI_PROVIDER
    new_model = config.model if config.model else old_model
    new_validator_type = normalize_validator_type(config.validator_type) if config.validator_type is not None else VALIDATOR_TYPE
    new_api_url = config.api_url if config.api_url is not None else API_URL
    new_service_url = config.service_url if config.service_url is not None else VALIDATOR_SERVICE_URL
    new_api_key = API_KEY if config.api_key is None or is_masked_secret(config.api_key) else config.api_key

    allowed_providers = {"mistral", "gemini", "openrouter", "grok"}
    if new_validator_type in AUTOMATIC_VALIDATOR_TYPES and new_provider not in allowed_providers:
        raise HTTPException(status_code=400, detail=f"Provider desconocido: {new_provider}")

    ai_client_changed = any([
        new_provider != old_provider,
        new_model != old_model,
        new_validator_type != old_validator_type,
        new_api_url != API_URL,
        new_api_key != API_KEY,
    ])

    if config.account_address is not None:
        ACCOUNT_ADDRESS = normalize_account_address(config.account_address)
        set_runtime_env("ACCOUNT_ADDRESS", ACCOUNT_ADDRESS)

    if config.private_key is not None and not is_masked_secret(config.private_key):
        PRIVATE_KEY = config.private_key
        set_runtime_env("PRIVATE_KEY", PRIVATE_KEY)

    if config.api_url is not None:
        API_URL = new_api_url
        set_runtime_env("API_URL", API_URL or "")

    if config.service_url is not None:
        VALIDATOR_SERVICE_URL = new_service_url
        set_runtime_env("VALIDATOR_SERVICE_URL", VALIDATOR_SERVICE_URL or "")

    if config.api_key is not None and not is_masked_secret(config.api_key):
        API_KEY = new_api_key
        set_runtime_env("API_KEY", API_KEY or "")

    if config.validator_type is not None:
        VALIDATOR_TYPE = new_validator_type
        set_runtime_env("VALIDATOR_TYPE", int(VALIDATOR_TYPE))

    if config.use_evidence_search is not None:
        USE_EVIDENCE_SEARCH = config.use_evidence_search
        set_runtime_env("USE_EVIDENCE_SEARCH", str(USE_EVIDENCE_SEARCH).lower())

    if config.online_search_enabled is not None:
        ONLINE_SEARCH_ENABLED = config.online_search_enabled
        set_runtime_env("ONLINE_SEARCH_ENABLED", str(ONLINE_SEARCH_ENABLED).lower())

    if config.evidence_search_url is not None:
        EVIDENCE_SEARCH_URL = config.evidence_search_url
        set_runtime_env("EVIDENCE_SEARCH_URL", EVIDENCE_SEARCH_URL)

    if config.evidence_search_use_preferred_domains is not None:
        set_runtime_env("EVIDENCE_SEARCH_USE_PREFERRED_DOMAINS", str(config.evidence_search_use_preferred_domains).lower())

    if config.evidence_search_preferred_profile_id is not None:
        EVIDENCE_SEARCH_PREFERRED_PROFILE_ID = config.evidence_search_preferred_profile_id
        set_runtime_env("EVIDENCE_SEARCH_PREFERRED_PROFILE_ID", EVIDENCE_SEARCH_PREFERRED_PROFILE_ID)

    if config.provider is not None:
        AI_PROVIDER = new_provider
        set_runtime_env("AI_PROVIDER", AI_PROVIDER)

    if config.model is not None:
        set_runtime_env("MODEL", new_model)

    if config.categories is not None:
        VALIDATOR_CATEGORIES = [int(category) for category in config.categories]
        set_runtime_env("VALIDATOR_CATEGORIES", json.dumps(VALIDATOR_CATEGORIES))

    try:
        if ai_client_changed:
            ai_validator = build_ai_validator()
            logger.info(
                f"🔄 AI Validator actualizado en memoria: "
                f"type={VALIDATOR_TYPE.name} provider={AI_PROVIDER.upper()} model={new_model}"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error al instanciar el nuevo AI Validator")
        raise HTTPException(status_code=500, detail=f"Error al cambiar la configuración de IA: {e}")

    reload_blockchain_client()

    public_config_changed = any([
        new_provider != old_provider,
        new_model != old_model,
        VALIDATOR_CATEGORIES != old_categories,
        VALIDATOR_TYPE != old_validator_type,
        VALIDATOR_SERVICE_URL != old_service_url,
        USE_EVIDENCE_SEARCH != old_use_evidence_search,
        ONLINE_SEARCH_ENABLED != old_online_search_enabled,
        EVIDENCE_SEARCH_URL != old_evidence_search_url,
        current_evidence_search_use_preferred_domains() != old_use_preferred_domains,
        current_evidence_search_preferred_profile_id() != old_preferred_profile_id,
    ])
    metrics_reset_at = datetime.now(timezone.utc).isoformat() if public_config_changed else None
    blockchain_receipts = {}

    if public_config_changed:
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

    event_ipfs_hash = blockchain_receipts.get("ipfs_config_hash") if blockchain_receipts else validator_config_ipfs_hash_from_chain()
    await publish_validator_config_event(event_ipfs_hash, source="admin_config", metrics_reset_at=metrics_reset_at)

    return {
        "status": "ok",
        "message": "Configuración actualizada correctamente.",
        "config": normalize_admin_config_response().model_dump(mode="json"),
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
            
            if isinstance(post_json, dict) and post_json.get("schema_version") == "assertions-document-v2":
                content_obj = post_json
            elif isinstance(post_json, dict) and "assertions" in post_json and "text" in post_json:
                content_obj = post_json
            else:
                content_obj = json.loads(post_json.get("content", "{}"))

            if isinstance(content_obj, dict) and "assertions" in content_obj and "post" not in content_obj:
                logger.info(f"[validate-asertions] detected minimal document shape from IPFS cid={cid}, reconstructing AssertionsDocumentV2")
                assertions_document = build_assertions_document_v2(
                    text=content_obj.get("text", ""),
                    assertions=content_obj.get("assertions", []),
                    mode=ValidationMode.BLOCKCHAIN,
                    provider="news-handler",
                )
            else:
                assertions_document = AssertionsDocumentV2(**content_obj)
            logger.info(f"[validate-asertions] loaded assertions-document-v2 from IPFS cid={cid}")

            assertion = next((item for item in assertions_document.assertions if int(item.assertion_index) == int(assertion_index)), None)
            if assertion is None:
                logger.warning(f"⚠️ Assertion index fuera de rango | post={post_id} assertion={assertion_index}")
                return

            payload_v2 = build_assertion_validation_payload_v2(
                mode=ValidationMode.BLOCKCHAIN,
                assertion=assertion,
                storage=SourceDocumentStorage.IPFS,
                post_id=post_id,
                cid=cid,
                order_id=None,
            )

        try:
            estado_enum, descripcion, extras, evidence_response = await asyncio.to_thread(validate_payload_v2, payload_v2)

            veredicto = Veredicto(descripcion, estado_enum)
            tx_hash, receipt = await registrar_validacion_internal(post_id, assertion_index, veredicto, extras, evidence_response)
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

