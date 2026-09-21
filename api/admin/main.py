# gateway_quotas.py
import os
import json
import math
import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from fastapi import FastAPI, HTTPException, Query, Request
import httpx
from motor.motor_asyncio import AsyncIOMotorClient
from aiokafka import AIOKafkaConsumer
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from typing import Optional, List, Dict, Any

# =========================================================
# Importación de Modelos de Mensajes
# (Asegúrate de que la ruta 'common.async_models' es correcta en tu entorno)
# =========================================================
from common.utils.kafka_contracts import ACTION_TO_QUOTA_MODEL, BILLABLE_SERVICES, DEFAULT_KAFKA_BOOTSTRAP, DEFAULT_TOPIC_RESPONSES
from common.models.async_models import ValidatorType, default_validator_type_weights
from common.models.quota_models import ClientCreate, ClientResponse, ClientStatus, ClientUpdate, QuotaDetail
from common.utils.logging_utils import configure_single_line_json_logging
from common.utils.mongo import build_mongo_uri_from_env

log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
configure_single_line_json_logging(log_level)
logger = logging.getLogger("admin")

# =========================================================
# Modelos API REST (Gestión de Cuotas y Clientes)
# =========================================================
class OpenRouterPrice(BaseModel):
    prompt_per_token_usd: str
    completion_per_token_usd: str
    prompt_per_million_usd: float
    completion_per_million_usd: float

class OpenRouterValidatorEnv(BaseModel):
    AI_PROVIDER: str = "openrouter"
    MODEL: str
    API_URL: str = "https://openrouter.ai/api/v1/chat/completions"

class OpenRouterModelRecommendation(BaseModel):
    rank: int
    model: str
    name: str
    quality_score: float
    value_score: float
    price: OpenRouterPrice
    estimated_validation_cost_usd: float
    context_length: Optional[int] = None
    max_completion_tokens: Optional[int] = None
    env: OpenRouterValidatorEnv
    reason: str


class OpenRouterRecommendationOption(BaseModel):
    tier: str
    model: str
    name: str
    price: OpenRouterPrice
    estimated_cost_usd: float
    estimated_cost_delta_usd: Optional[float] = None
    estimated_cost_delta_percent: Optional[float] = None


class DeployedLLMRecommendation(BaseModel):
    target_id: str
    target_kind: str
    workload: str
    workload_key: Optional[str] = None
    current_provider: str
    current_model: str
    input_tokens: int
    output_tokens: int
    current_price: Optional[OpenRouterPrice] = None
    estimated_current_cost_usd: Optional[float] = None
    options: List[OpenRouterRecommendationOption]
    reason: str
    reason_key: Optional[str] = None


class OpenRouterRecommendationsResponse(BaseModel):
    generated_at: datetime
    source_url: str
    pricing_note: str
    estimation_note: str
    recommendations: List[OpenRouterModelRecommendation]
    deployment_recommendations: List[DeployedLLMRecommendation] = Field(default_factory=list)


class ValidatorTypeWeightsUpdate(BaseModel):
    weights: Dict[str, float]


class LLMRuntimeUpdate(BaseModel):
    """The only mutable LLM fields exposed through the administrative API."""

    model_config = ConfigDict(extra="forbid")

    provider: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None

    @field_validator("provider")
    @classmethod
    def non_empty_provider(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip().lower()
        if not value:
            raise ValueError("provider no puede estar vacío")
        return value

    @field_validator("model")
    @classmethod
    def non_empty_model(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("model no puede estar vacío")
        return value

    @field_validator("temperature")
    @classmethod
    def valid_temperature(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ValueError("temperature debe ser un número finito mayor o igual que cero")
        return value

# =========================================================
# Configuración
# =========================================================
MONGO_URI = build_mongo_uri_from_env()
MONGO_DBNAME = os.getenv("MONGO_DBNAME", "newsdb")
ORDERS_COLLECTION_NAME = os.getenv("ORDERS_COLLECTION", "news")
QUOTAS_COLLECTION_NAME = os.getenv("QUOTAS_COLLECTION_NAME", "clients_quotas")
CONFIG_COLLECTION_NAME = os.getenv("CONFIG_COLLECTION_NAME", "config")
VALIDATOR_TYPE_WEIGHTS_CONFIG_ID = "validator_type_weights"

KAFKA_BROKER = os.getenv("KAFKA_BROKER", DEFAULT_KAFKA_BOOTSTRAP)
TOPIC_RESPONSES = os.getenv("TOPIC_RESPONSES", DEFAULT_TOPIC_RESPONSES)

OPENROUTER_MODELS_URL = os.getenv("OPENROUTER_MODELS_URL", "https://openrouter.ai/api/v1/models")
OPENROUTER_CHAT_COMPLETIONS_URL = os.getenv(
    "OPENROUTER_CHAT_COMPLETIONS_URL",
    "https://openrouter.ai/api/v1/chat/completions"
)
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL")
OPENROUTER_APP_TITLE = os.getenv("OPENROUTER_APP_TITLE", "TrustNews Admin")
GENERATE_ASSERTIONS_URL = os.getenv("GENERATE_ASSERTIONS_URL", "http://generate-asertions.apis.svc.cluster.local:8071")
SOURCE_ROUTER_URL = os.getenv("SOURCE_ROUTER_URL", "http://source-router.apis.svc.cluster.local:8075")
NEWS_HANDLER_URL = os.getenv("NEWS_HANDLER_URL", "http://news-handler.apis.svc.cluster.local:8072")

# =========================================================
# App & Globales
# =========================================================
app = FastAPI(title="Gateway - Quota Manager")
mongo_client = None
db = None
orders_collection = None
quotas_collection = None
config_collection = None
consumer = None


def validate_validator_type_weights(weights: Dict[str, float]) -> Dict[str, float]:
    allowed_names = {validator_type.name for validator_type in ValidatorType}
    unknown_names = sorted(set(weights) - allowed_names)
    if unknown_names:
        raise HTTPException(status_code=422, detail=f"Tipos de validador desconocidos: {', '.join(unknown_names)}")

    normalized = {}
    for name, value in weights.items():
        numeric_value = float(value)
        if not math.isfinite(numeric_value) or numeric_value < 0 or numeric_value > 1:
            raise HTTPException(status_code=422, detail=f"El peso de {name} debe estar entre 0 y 1")
        normalized[name] = numeric_value
    return normalized


async def get_validator_type_weights_document() -> dict:
    defaults = default_validator_type_weights()
    document = await config_collection.find_one({"_id": VALIDATOR_TYPE_WEIGHTS_CONFIG_ID})
    configured = validate_validator_type_weights((document or {}).get("weights") or {})
    return {
        "config_id": VALIDATOR_TYPE_WEIGHTS_CONFIG_ID,
        "weights": {**defaults, **configured},
        "updated_at": (document or {}).get("updated_at"),
    }


# =========================================================
# Lógica de Base de Datos
# =========================================================

async def resolve_client_id(order_id: str = None, post_id: str = None) -> str:
    """
    Busca el client_id en la colección de órdenes (orders).
    Prioriza la búsqueda por order_id. Si no, usa postId.
    Intenta múltiples formatos de postId (string, int).
    """
    if not order_id and not post_id:
        return None

    if order_id and order_id.strip():  # Order ID has value
        doc = await orders_collection.find_one({"order_id": order_id}, {"client_id": 1})
        if doc and "client_id" in doc:
            return doc["client_id"]

    if post_id:
        post_id_str = str(post_id).strip()
        if not post_id_str:
            return None

        queries = [
            {"postId": post_id_str},
        ]

        if post_id_str.isdigit():
            queries.append({"postId": int(post_id_str)})

        for query in queries:
            doc = await orders_collection.find_one(query, {"client_id": 1})
            if doc and "client_id" in doc:
                logger.debug(f"✅ Resolved client_id from postId={post_id_str} using query {query}")
                return doc["client_id"]

    return None

async def record_consumption(client_id: str, service_type: str, cost: int = 1):
    """Incrementa el contador de consumo de un cliente."""
    consumed_field = f"consumed.{service_type}"
    try:
        await quotas_collection.update_one(
            {"client_id": client_id},
            {
                "$inc": {consumed_field: cost},
                "$setOnInsert": {
                    "status": ClientStatus.ALTA.value,
                    "active_date": datetime.now(timezone.utc)
                }
            },
            upsert=True
        )
        logger.info(f"💰 Quota updated | Client: {client_id} | Service: {service_type} | +{cost}")
    except Exception as e:
        logger.error(f"❌ Error updating quota for {client_id}: {e}")


# =========================================================
# OpenRouter helpers
# =========================================================
def decimal_or_none(value: Any) -> Optional[Decimal]:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None

def price_per_million(price_per_token: Decimal) -> float:
    return float(price_per_token * Decimal("1000000"))

def quality_score_for_model(model_id: str, name: str) -> float:
    """
    Estimación heurística de calidad: OpenRouter expone precios/capacidad, pero no
    un benchmark único comparable en /models. Priorizamos familias fuertes y
    modelos habitualmente buenos para clasificación/validación de texto.
    """
    text = f"{model_id} {name}".lower()
    score = 50.0

    quality_terms = {
        "gpt-5": 98,
        "claude-4": 97,
        "gemini-2.5-pro": 96,
        "gpt-4.1": 92,
        "claude-3.5": 90,
        "claude-3-5": 90,
        "gemini-2.5-flash": 88,
        "deepseek-r1": 87,
        "deepseek-v3": 86,
        "qwen3": 84,
        "llama-4": 84,
        "gpt-4o-mini": 82,
        "haiku": 82,
        "mistral": 78,
        "nova": 76,
        "llama-3": 74,
    }

    for term, term_score in quality_terms.items():
        if term in text:
            score = max(score, float(term_score))

    if "free" in text:
        score -= 4
    if "preview" in text or "experimental" in text or "beta" in text:
        score -= 3

    return max(1.0, min(score, 100.0))

def model_reason(model_id: str, prompt_per_m: float, completion_per_m: float, quality_score: float) -> str:
    if prompt_per_m == 0 and completion_per_m == 0:
        return "Muy buen candidato para pruebas y validaciones de bajo coste; revisa límites/rate limits de modelos gratuitos."
    if quality_score >= 90:
        return "Alta calidad esperada manteniendo un coste razonable para validación de aserciones."
    if prompt_per_m <= 0.5 and completion_per_m <= 2:
        return "Coste bajo por token y calidad suficiente para clasificación TRUE/FALSE/UNKNOWN."
    return "Buen equilibrio entre coste, contexto disponible y calidad estimada."

def build_openrouter_recommendation(model: Dict[str, Any], rank: int) -> Optional[OpenRouterModelRecommendation]:
    pricing = model.get("pricing") or {}
    prompt_price = decimal_or_none(pricing.get("prompt"))
    completion_price = decimal_or_none(pricing.get("completion"))

    if prompt_price is None or completion_price is None:
        return None
    if prompt_price < 0 or completion_price < 0:
        return None

    model_id = model.get("id")
    if not model_id:
        return None

    name = model.get("name") or model_id
    quality_score = quality_score_for_model(model_id, name)
    prompt_per_m = price_per_million(prompt_price)
    completion_per_m = price_per_million(completion_price)

    estimated_cost = float((prompt_price * Decimal("1000")) + (completion_price * Decimal("250")))
    weighted_price_per_m = float((prompt_price * Decimal("0.75") + completion_price * Decimal("0.25")) * Decimal("1000000"))
    value_score = quality_score / max(weighted_price_per_m, 0.05)

    return OpenRouterModelRecommendation(
        rank=rank,
        model=model_id,
        name=name,
        quality_score=round(quality_score, 2),
        value_score=round(value_score, 4),
        price=OpenRouterPrice(
            prompt_per_token_usd=str(prompt_price),
            completion_per_token_usd=str(completion_price),
            prompt_per_million_usd=round(prompt_per_m, 6),
            completion_per_million_usd=round(completion_per_m, 6),
        ),
        estimated_validation_cost_usd=round(estimated_cost, 8),
        context_length=model.get("context_length"),
        max_completion_tokens=model.get("top_provider", {}).get("max_completion_tokens") or model.get("max_completion_tokens"),
        env=OpenRouterValidatorEnv(
            MODEL=model_id,
            API_URL=OPENROUTER_CHAT_COMPLETIONS_URL,
        ),
        reason=model_reason(model_id, prompt_per_m, completion_per_m, quality_score),
    )

def is_text_generation_model(model: Dict[str, Any]) -> bool:
    architecture = model.get("architecture") or {}
    input_modalities = architecture.get("input_modalities") or []
    output_modalities = architecture.get("output_modalities") or []

    if input_modalities and "text" not in input_modalities:
        return False
    if output_modalities and "text" not in output_modalities:
        return False
    return True


# Curated candidates are deliberately workload-specific. Catalog metadata can
# confirm availability and price, but not evidence entailment or extraction quality.
LLM_RECOMMENDATION_PROFILES: dict[str, dict[str, Any]] = {
    "generate-asertions": {
        "translation_key": "generateAssertions",
        "workload": "Extracción estructurada de aserciones",
        "tiers": {
            "premium": ["google/gemini-3.8-flash", "mistralai/mistral-medium-3-5"],
            "similar": ["openai/gpt-5-nano", "openai/gpt-4.1-nano"],
            "budget": ["qwen/qwen3.7-flash", "qwen/qwen3-30b-a3b-instruct-2507"],
        },
        "input_tokens": 3000, "output_tokens": 1200,
        "reason": "Prioriza extracción multilingüe, cobertura de hechos y salida estructurada; debe superar el benchmark de AssertionBatch antes del cambio.",
    },
    "source-router": {
        "translation_key": "sourceRouter",
        "workload": "Clasificación estructurada de fuentes",
        "tiers": {
            "premium": ["google/gemini-3.8-flash", "google/gemini-3.5-flash-lite"],
            "similar": ["openai/gpt-5-nano", "openai/gpt-4.1-nano"],
            "budget": ["mistralai/mistral-nemo", "qwen/qwen3.7-flash"],
        },
        "input_tokens": 2000, "output_tokens": 800,
        "reason": "Modelo pequeño orientado a alto volumen, con contexto amplio y salida estructurada para clasificar autoridad y jurisdicción.",
    },
    "rag:ext_only_official": {
        "translation_key": "ragExtOnlyOfficial",
        "workload": "Validación RAG · solo fuentes oficiales externas",
        "tiers": {
            "premium": ["openai/gpt-5.6-sol", "google/gemini-3.1-pro-preview", "google/gemini-3.8-flash"],
            "similar": ["qwen/qwen3-30b-a3b-instruct-2507", "mistralai/mistral-small-24b-instruct-2501"],
            "budget": ["qwen/qwen3.7-flash", "amazon/nova-micro-v1"],
        },
        "input_tokens": 6000, "output_tokens": 600,
        "reason": "Prioriza razonamiento probatorio y entailment sobre evidencias oficiales; es el uso con mayor impacto y justifica un modelo de gama alta.",
    },
    "rag:ext_official_first": {
        "translation_key": "ragExtOfficialFirst",
        "workload": "Validación RAG · fuentes oficiales primero",
        "tiers": {
            "premium": ["anthropic/claude-sonnet-5", "google/gemini-3.1-pro-preview", "google/gemini-3.8-flash"],
            "similar": ["qwen/qwen3.7-flash", "mistralai/mistral-small-24b-instruct-2501"],
            "budget": ["mistralai/mistral-nemo", "amazon/nova-micro-v1"],
        },
        "input_tokens": 6000, "output_tokens": 600,
        "reason": "Aporta una familia distinta al ensemble y capacidad alta para distinguir soporte, contradicción y evidencia insuficiente.",
    },
    "rag:local": {
        "translation_key": "ragLocal",
        "workload": "Validación RAG · corpus local",
        "tiers": {
            "premium": ["mistralai/mistral-medium-3-5", "google/gemini-3.8-flash"],
            "similar": ["qwen/qwen3-30b-a3b-instruct-2507", "mistralai/mistral-small-24b-instruct-2501"],
            "budget": ["qwen/qwen3.7-flash", "mistralai/mistral-nemo"],
        },
        "input_tokens": 6000, "output_tokens": 600,
        "reason": "Mantiene diversidad de proveedor y prioriza comprensión multilingüe de documentos locales con salida estructurada.",
    },
    "rag": {
        "translation_key": "rag",
        "workload": "Validación RAG",
        "tiers": {
            "premium": ["google/gemini-3.1-pro-preview", "openai/gpt-5.6-sol", "google/gemini-3.8-flash"],
            "similar": ["qwen/qwen3-30b-a3b-instruct-2507", "mistralai/mistral-small-24b-instruct-2501"],
            "budget": ["qwen/qwen3.7-flash", "amazon/nova-micro-v1"],
        },
        "input_tokens": 6000, "output_tokens": 600,
        "reason": "Prioriza razonamiento probatorio y grounding; la elección final requiere medir entailment y citas con el corpus del proyecto.",
    },
    "search": {
        "translation_key": "search",
        "workload": "Validación con búsqueda online",
        "tiers": {
            "premium": ["google/gemini-3.8-flash", "openai/gpt-5.6-terra"],
            "similar": ["openai/gpt-5-nano", "qwen/qwen3-30b-a3b-instruct-2507"],
            "budget": ["qwen/qwen3.7-flash", "mistralai/mistral-nemo"],
        },
        "input_tokens": 2500, "output_tokens": 700,
        "reason": "Equilibra síntesis y coste para búsqueda online; las citas siguen siendo no verificadas hasta persistir las anotaciones del proveedor.",
    },
    "memory": {
        "translation_key": "memory",
        "workload": "Validación por conocimiento del modelo",
        "tiers": {
            "premium": ["mistralai/mistral-small-2603", "google/gemini-3.5-flash-lite"],
            "similar": ["openai/gpt-5-nano", "qwen/qwen3-30b-a3b-instruct-2507"],
            "budget": ["mistralai/mistral-nemo", "qwen/qwen3.7-flash"],
        },
        "input_tokens": 1800, "output_tokens": 500,
        "reason": "Prioriza calibración y coste moderado: un modelo más caro no corrige la falta de evidencia verificable de este tipo de validator.",
    },
}


def openrouter_price(model: dict[str, Any]) -> Optional[OpenRouterPrice]:
    pricing = model.get("pricing") or {}
    prompt_price = decimal_or_none(pricing.get("prompt"))
    completion_price = decimal_or_none(pricing.get("completion"))
    if prompt_price is None or completion_price is None or prompt_price < 0 or completion_price < 0:
        return None
    return OpenRouterPrice(
        prompt_per_token_usd=str(prompt_price), completion_per_token_usd=str(completion_price),
        prompt_per_million_usd=round(price_per_million(prompt_price), 6),
        completion_per_million_usd=round(price_per_million(completion_price), 6),
    )


def estimated_token_cost(price: OpenRouterPrice, input_tokens: int, output_tokens: int) -> float:
    return float(
        Decimal(price.prompt_per_token_usd) * Decimal(input_tokens)
        + Decimal(price.completion_per_token_usd) * Decimal(output_tokens)
    )


def recommendation_profile(component: str, validator_type: Optional[dict[str, Any]] = None,
                           strategy: Optional[str] = None) -> Optional[dict[str, Any]]:
    if component in ("generate-asertions", "source-router"):
        return LLM_RECOMMENDATION_PROFILES[component]
    type_name = str((validator_type or {}).get("name") or "").upper()
    if type_name == "RAG_EVIDENCE_VALIDATION":
        key = f"rag:{str(strategy or '').lower()}"
        return LLM_RECOMMENDATION_PROFILES.get(key, LLM_RECOMMENDATION_PROFILES["rag"])
    if type_name == "LLM_SEARCH_VALIDATION":
        return LLM_RECOMMENDATION_PROFILES["search"]
    if type_name == "LLM_MEMORY_VALIDATION":
        return LLM_RECOMMENDATION_PROFILES["memory"]
    return None


def build_deployed_recommendation(*, target_id: str, target_kind: str, current: dict[str, Any],
                                  catalog: dict[str, dict[str, Any]], profile: dict[str, Any]) -> Optional[DeployedLLMRecommendation]:
    input_tokens = int(profile["input_tokens"])
    output_tokens = int(profile["output_tokens"])
    current_provider = str(current.get("provider") or "").lower()
    current_model = str(current.get("model") or "")
    current_raw = catalog.get(current_model) if current_provider == "openrouter" else None
    current_price = openrouter_price(current_raw) if current_raw else None
    current_cost = estimated_token_cost(current_price, input_tokens, output_tokens) if current_price else None

    options = []
    for tier in ("premium", "similar", "budget"):
        candidate_ids = profile.get("tiers", {}).get(tier, [])
        for model_id in candidate_ids:
            raw_model = catalog.get(model_id)
            price = openrouter_price(raw_model) if raw_model else None
            if not price or model_id == current_model:
                continue
            estimated_cost = estimated_token_cost(price, input_tokens, output_tokens)
            if tier == "similar" and current_cost is not None and not current_cost * 0.5 <= estimated_cost <= current_cost * 1.5:
                continue
            if tier == "budget" and (current_cost is None or estimated_cost >= current_cost):
                continue
            delta = estimated_cost - current_cost if current_cost is not None else None
            delta_percent = (delta / current_cost * 100) if delta is not None and current_cost else None
            options.append(OpenRouterRecommendationOption(
                tier=tier,
                model=model_id,
                name=raw_model.get("name") or model_id,
                price=price,
                estimated_cost_usd=round(estimated_cost, 8),
                estimated_cost_delta_usd=round(delta, 8) if delta is not None else None,
                estimated_cost_delta_percent=round(delta_percent, 2) if delta_percent is not None else None,
            ))
            break
    if not options:
        return None

    return DeployedLLMRecommendation(
        target_id=target_id, target_kind=target_kind, workload=profile["workload"],
        workload_key=profile.get("translation_key"),
        current_provider=current_provider, current_model=current_model,
        input_tokens=input_tokens, output_tokens=output_tokens, current_price=current_price,
        estimated_current_cost_usd=round(current_cost, 8) if current_cost is not None else None,
        options=options,
        reason=profile["reason"], reason_key=profile.get("translation_key"),
    )


async def deployed_llm_recommendations(catalog: dict[str, dict[str, Any]]) -> list[DeployedLLMRecommendation]:
    component_calls = [get_llm_component(component) for component in LLM_COMPONENT_TARGETS]
    results = await asyncio.gather(*component_calls, discover_validators(), return_exceptions=True)
    recommendations: list[DeployedLLMRecommendation] = []

    for component, result in zip(LLM_COMPONENT_TARGETS, results[:len(component_calls)]):
        if isinstance(result, Exception):
            logger.warning("Could not inspect deployed LLM component=%s error=%s", component, result.__class__.__name__)
            continue
        profile = recommendation_profile(component)
        recommendation = build_deployed_recommendation(
            target_id=component, target_kind="component", current=result.get("actual") or {},
            catalog=catalog, profile=profile,
        ) if profile else None
        if recommendation:
            recommendations.append(recommendation)

    validator_result = results[-1]
    if isinstance(validator_result, Exception):
        logger.warning("Could not inspect deployed validators error=%s", validator_result.__class__.__name__)
        return recommendations
    for validator in validator_result:
        profile = recommendation_profile(
            "validator", validator.get("validator_type"), validator.get("evidence_search_strategy"),
        )
        if not profile or not validator.get("model"):
            continue
        recommendation = build_deployed_recommendation(
            target_id=validator["validator_id"], target_kind="validator", current=validator,
            catalog=catalog, profile=profile,
        )
        if recommendation:
            recommendations.append(recommendation)
    return recommendations


# =========================================================
# Procesamiento de Kafka
# =========================================================
async def process_quota_event(data: dict):
    try:
        action = data.get("action")
        order_id = data.get("order_id")

        if not action:
            logger.warning("⚠️ Kafka message without 'action', ignored in Quotas.")
            return

        # 1. ¿Es una acción cobrable? Si no, salimos rápido.
        service_type = BILLABLE_SERVICES.get(action)
        model_cls = ACTION_TO_QUOTA_MODEL.get(action)

        if not service_type or not model_cls:
            return

        # ============================================================
        # 2. Resolver order_id a partir de postId si no viene informado
        # ============================================================
        post_id = None
        if not order_id or order_id == "":
            post_id = (
                data.get("payload", {}).get("postId")
                if isinstance(data.get("payload"), dict)
                else None
            )

            if not post_id:
                logger.warning(f"⚠️ Message '{action}' without 'order_id' or 'postId'. Cannot bill.")
                return

        # 3. Validación Pydantic estricta
        try:
            parsed = model_cls(**data)
            order_id = parsed.order_id
            
            if hasattr(parsed.payload, "postId"):
                post_id = str(parsed.payload.postId)
                
            logger.info(f"[{order_id or post_id}] ✅ Billable message '{action}' validated.")
        except ValidationError as e:
            logger.error(f"[{order_id or post_id}] ❌ Pydantic validation error for billing '{action}': {e}")
            return

        # 4. Buscar a quién cobrarle
        client_id = await resolve_client_id(order_id=order_id, post_id=post_id)

        if not client_id:
            # Debug: Try to find what documents exist in the orders collection
            if post_id:
                existing_doc = await orders_collection.find_one(
                    {"postId": {"$exists": True}},
                    {"order_id": 1, "postId": 1, "client_id": 1},
                    skip=0
                )
                debug_info = f" (Sample order found: postId={existing_doc.get('postId') if existing_doc else 'N/A'}, type={type(existing_doc.get('postId')) if existing_doc else 'N/A'})"
            else:
                debug_info = ""
            
            logger.warning(f"⚠️ Event '{action}' discarded. No client_id found in DB for OrderID={order_id} / PostID={post_id}.{debug_info}")
            return

        # 5. Ejecutar cobro
        await record_consumption(client_id, service_type, cost=1)

    except Exception as e:
        logger.exception(f"❌ Unexpected error processing quota event: {e}")


# =========================================================
# Bucle del Consumidor Kafka
# =========================================================
async def consume_responses_for_quotas():
    global consumer
    logger.info("🎧 Starting Quota Manager Kafka Consumer...")

    consumer = AIOKafkaConsumer(
        TOPIC_RESPONSES,
        bootstrap_servers=KAFKA_BROKER,
        group_id="gateway-quota-billing-group", 
        auto_offset_reset="earliest"
    )
    await consumer.start()
    logger.info(f"✅ Quota Manager subscribed to topic: {TOPIC_RESPONSES}")

    try:
        async for msg in consumer:
            try:
                raw = msg.value.decode("utf-8")
                data = json.loads(raw)
                await process_quota_event(data)
            except json.JSONDecodeError:
                logger.error("❌ Received non-JSON message in Kafka")
            except Exception as e:
                logger.exception(f"❌ Error reading Kafka message: {e}")
    except Exception as e:
        logger.exception(f"💥 Fatal error in the loop: {e}")
    finally:
        if consumer:
            await consumer.stop()


# =========================================================
# Endpoints REST
# =========================================================

# LLM runtime configuration -------------------------------------------------
#
# Admin owns desired/actual state in Mongo.  The services keep the effective
# configuration in memory and expose their already-existing internal
# /admin/config endpoint.  No credential can cross either HTTP boundary.
LLM_COMPONENT_TARGETS = {
    "generate-asertions": GENERATE_ASSERTIONS_URL,
    "source-router": SOURCE_ROUTER_URL,
}


def llm_config_id(component: str) -> str:
    return f"llm:{component}"


def validator_config_id(validator_id: str) -> str:
    return f"llm:validator:{validator_id.lower()}"


def normalized_llm_config(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep only non-sensitive, portable LLM settings from a service reply."""
    source = payload.get("config") if isinstance(payload.get("config"), dict) else payload
    result = {
        "provider": str(source.get("provider") or "").strip().lower(),
        "model": str(source.get("model") or "").strip(),
        "temperature": source.get("temperature"),
        "config_version": int(source.get("config_version") or 0),
    }
    if result["temperature"] is not None:
        try:
            result["temperature"] = float(result["temperature"])
        except (TypeError, ValueError):
            result["temperature"] = None
    return result


async def service_config(url: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{url.rstrip('/')}/admin/config")
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Servicio de configuración no disponible: {exc.__class__.__name__}") from exc
    return normalized_llm_config(data)


async def apply_service_config(url: str, desired: dict[str, Any]) -> dict[str, Any]:
    safe_payload = {
        key: desired[key]
        for key in ("provider", "model", "temperature", "config_version")
        if key in desired and desired[key] is not None
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.put(f"{url.rstrip('/')}/admin/config", json=safe_payload)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"No se pudo aplicar la configuración: {exc.__class__.__name__}") from exc
    return normalized_llm_config(data)


def config_matches(desired: dict[str, Any], actual: dict[str, Any]) -> bool:
    return all(
        desired.get(key) == actual.get(key)
        for key in ("provider", "model", "temperature", "config_version")
    )


async def config_document_or_effective(config_id: str, effective: dict[str, Any], component: str) -> dict[str, Any]:
    document = await config_collection.find_one({"_id": config_id})
    if not document:
        return {
            "component": component,
            "desired": effective,
            "actual": effective,
            "config_version": 0,
            "status": "APPLIED",
            "updated_at": None,
            "updated_by": None,
        }
    return {
        "component": component,
        "desired": document.get("desired") or effective,
        "actual": document.get("actual") or effective,
        "config_version": int(document.get("config_version") or 0),
        "status": document.get("status") or "ERROR",
        "updated_at": document.get("updated_at"),
        "updated_by": document.get("updated_by"),
        "last_error": document.get("last_error"),
    }


def semantic_validator_type(value: Any) -> dict[str, Any]:
    try:
        parsed = ValidatorType(int(value))
    except (TypeError, ValueError):
        parsed = ValidatorType.LLM_MEMORY_VALIDATION
    return {"id": int(parsed), "name": parsed.name}


def validator_is_active(config: dict[str, Any]) -> bool:
    return config.get("status") in (None, 1, "1", "Registered", "registered", "ACTIVE", "active")


async def discover_validators() -> list[dict[str, Any]]:
    """Discover validators from the existing blockchain/IPFS-backed cache.

    The browser never provides a pod URL.  The service URL is read from the
    registered validator configuration and is subsequently checked server-side.
    """
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(f"{NEWS_HANDLER_URL.rstrip('/')}/validators/cache", params={"recover_ipfs": "true"})
        response.raise_for_status()
        rows = response.json().get("validators") or []
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"No se pudieron descubrir validators: {exc.__class__.__name__}") from exc

    validators = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        validator_id = str(row.get("validator") or "").strip()
        config = row.get("config") or {}
        if not validator_id or not isinstance(config, dict):
            continue
        service_url = str(row.get("service_url") or row.get("validator_service_url") or config.get("service_url") or "").strip()
        item = {
            "validator_id": validator_id,
            "service_url": service_url,
            "validator_type": semantic_validator_type(row.get("validator_type") or config.get("type")),
            "evidence_search_strategy": config.get("evidence_search_strategy"),
            "categories": row.get("categories") or [],
            "status": "ACTIVE" if validator_is_active(config) else "INACTIVE",
            "provider": config.get("provider"),
            "model": config.get("model"),
        }
        if service_url and item["status"] == "ACTIVE":
            try:
                actual = await service_config(service_url)
                item.update(actual)
                document = await config_collection.find_one({"_id": validator_config_id(validator_id)})
                item["config_version"] = int((document or {}).get("config_version") or actual.get("config_version") or 0)
            except HTTPException:
                item["status"] = "ERROR"
                item["config_version"] = 0
        else:
            item["status"] = "ERROR" if item["status"] == "ACTIVE" else item["status"]
            item["config_version"] = 0
        validators.append(item)
    return validators


async def require_discovered_validator(validator_id: str) -> dict[str, Any]:
    normalized = validator_id.lower()
    for validator in await discover_validators():
        if validator["validator_id"].lower() == normalized:
            if validator["status"] != "ACTIVE" or not validator.get("service_url"):
                raise HTTPException(status_code=503, detail="Validator existe pero no está accesible")
            return validator
    raise HTTPException(status_code=404, detail="Validator no encontrado")


async def persist_and_apply_llm_config(
    *,
    config_id: str,
    component: str,
    target_url: str,
    payload: LLMRuntimeUpdate,
    updated_by: str,
    validator_type: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = await service_config(target_url)
    old_document = await config_collection.find_one({"_id": config_id}) or {}
    desired = {**current, **payload.model_dump(exclude_none=True)}
    desired["config_version"] = int(old_document.get("config_version") or 0) + 1
    now = datetime.now(timezone.utc)
    audit = {
        "component": component,
        "validator_type": validator_type,
        "previous": {key: current.get(key) for key in ("provider", "model", "temperature", "config_version")},
        "next": {key: desired.get(key) for key in ("provider", "model", "temperature", "config_version")},
        "config_version": desired["config_version"],
        "updated_by": updated_by,
        "updated_at": now,
        "result": "PENDING",
    }
    await config_collection.update_one(
        {"_id": config_id},
        {"$set": {"component": component, "desired": desired, "config_version": desired["config_version"], "status": "PENDING", "updated_at": now,
                  "updated_by": updated_by, "last_audit": audit},
         "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    try:
        actual = await apply_service_config(target_url, desired)
        if not config_matches(desired, actual):
            raise RuntimeError("desired_actual_mismatch")
    except Exception as exc:
        error = exc.detail if isinstance(exc, HTTPException) else exc.__class__.__name__
        audit["result"] = "ERROR"
        await config_collection.update_one(
            {"_id": config_id},
            {"$set": {"status": "ERROR", "last_error": str(error), "updated_at": datetime.now(timezone.utc),
                      "last_audit": audit}},
        )
        logger.warning("LLM runtime configuration failed component=%s version=%s error=%s", component, desired["config_version"], error)
        raise HTTPException(status_code=503, detail=f"Configuración persistida pero no aplicada: {error}") from exc

    audit["result"] = "APPLIED"
    now = datetime.now(timezone.utc)
    await config_collection.update_one(
        {"_id": config_id},
        {"$set": {"actual": actual, "status": "APPLIED", "updated_at": now, "updated_by": updated_by,
                  "last_error": None, "last_audit": audit}},
    )
    logger.info("LLM runtime configuration applied component=%s version=%s provider=%s model=%s updated_by=%s",
                component, desired["config_version"], desired["provider"], desired["model"], updated_by)
    return await config_document_or_effective(config_id, actual, component)


@app.get("/internal/llm/overrides/{config_id:path}")
async def get_internal_llm_override(config_id: str):
    """Cluster-internal startup lookup; intentionally contains no credentials."""
    document = await config_collection.find_one({"_id": config_id})
    if not document or not isinstance(document.get("desired"), dict):
        raise HTTPException(status_code=404, detail="No runtime override")
    desired = normalized_llm_config(document["desired"])
    desired["config_version"] = int(document.get("config_version") or desired.get("config_version") or 0)
    return {"desired": desired, "status": document.get("status")}


@app.get("/llm/components")
async def list_llm_components():
    return {"components": [await get_llm_component(component) for component in LLM_COMPONENT_TARGETS]}


@app.get("/llm/components/{component}")
async def get_llm_component(component: str):
    target = LLM_COMPONENT_TARGETS.get(component)
    if not target:
        raise HTTPException(status_code=404, detail="Componente LLM desconocido")
    actual = await service_config(target)
    return await config_document_or_effective(llm_config_id(component), actual, component)


@app.put("/llm/components/{component}")
async def update_llm_component(component: str, payload: LLMRuntimeUpdate, request: Request):
    target = LLM_COMPONENT_TARGETS.get(component)
    if not target:
        raise HTTPException(status_code=404, detail="Componente LLM desconocido")
    if not payload.model_dump(exclude_none=True):
        raise HTTPException(status_code=400, detail="Indica al menos un campo LLM a actualizar")
    updated_by = request.headers.get("x-assermetry-admin-user", "gateway-admin")
    return await persist_and_apply_llm_config(
        config_id=llm_config_id(component), component=component, target_url=target,
        payload=payload, updated_by=updated_by,
    )


@app.get("/llm/validators")
async def list_llm_validators(
    type: Optional[str] = Query(None),
    strategy: Optional[str] = Query(None),
):
    validators = await discover_validators()
    if type:
        type_upper = type.upper()
        validators = [item for item in validators if item["validator_type"]["name"] == type_upper]
    if strategy:
        strategy_upper = strategy.upper()
        validators = [item for item in validators if str(item.get("evidence_search_strategy") or "").upper() == strategy_upper]
    return {"validators": validators}


@app.get("/llm/validators/{validator_id}")
async def get_llm_validator(validator_id: str):
    validator = await require_discovered_validator(validator_id)
    actual = await service_config(validator["service_url"])
    view = await config_document_or_effective(validator_config_id(validator["validator_id"]), actual, f"validator:{validator['validator_id']}")
    return {**view, **{key: value for key, value in validator.items() if key != "service_url"}}


@app.put("/llm/validators/{validator_id}")
async def update_llm_validator(validator_id: str, payload: LLMRuntimeUpdate, request: Request):
    validator = await require_discovered_validator(validator_id)
    if not payload.model_dump(exclude_none=True):
        raise HTTPException(status_code=400, detail="Indica al menos un campo LLM a actualizar")
    updated_by = request.headers.get("x-assermetry-admin-user", "gateway-admin")
    result = await persist_and_apply_llm_config(
        config_id=validator_config_id(validator["validator_id"]), component=f"validator:{validator['validator_id']}",
        target_url=validator["service_url"], payload=payload, updated_by=updated_by,
        validator_type=validator["validator_type"],
    )
    return {**result, "validator_id": validator["validator_id"], "validator_type": validator["validator_type"],
            "evidence_search_strategy": validator["evidence_search_strategy"], "categories": validator["categories"],
            "status": "APPLIED"}


@app.get("/ai/openrouter/recommendations", response_model=OpenRouterRecommendationsResponse)
async def get_openrouter_model_recommendations(
    limit: int = Query(8, ge=1, le=30, description="Número de modelos recomendados a devolver"),
    include_free: bool = Query(True, description="Incluir modelos gratuitos en la recomendación"),
    min_quality_score: float = Query(70, ge=1, le=100, description="Calidad mínima estimada por heurística interna"),
):
    """
    Devuelve modelos de OpenRouter ordenados por relación calidad/precio.
    La configuración está lista para validate-asertions: AI_PROVIDER=openrouter y MODEL=<id>.
    """
    headers = {"Accept": "application/json"}
    if OPENROUTER_SITE_URL:
        headers["HTTP-Referer"] = OPENROUTER_SITE_URL
    if OPENROUTER_APP_TITLE:
        headers["X-Title"] = OPENROUTER_APP_TITLE

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(OPENROUTER_MODELS_URL, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"OpenRouter devolvió un error al listar modelos: {e.response.text}"
        )
    except Exception as e:
        logger.exception(f"❌ Error connecting to OpenRouter models API: {e}")
        raise HTTPException(status_code=502, detail=f"No se pudo conectar a OpenRouter: {e}")

    raw_models = payload.get("data")
    if not isinstance(raw_models, list):
        raise HTTPException(status_code=502, detail="Respuesta inesperada de OpenRouter: falta data[].")

    recommendations = []
    for raw_model in raw_models:
        if not isinstance(raw_model, dict) or not is_text_generation_model(raw_model):
            continue

        recommendation = build_openrouter_recommendation(raw_model, rank=0)
        if not recommendation:
            continue
        if not include_free and (
            recommendation.price.prompt_per_million_usd == 0
            and recommendation.price.completion_per_million_usd == 0
        ):
            continue
        if recommendation.quality_score < min_quality_score:
            continue

        recommendations.append(recommendation)

    recommendations.sort(
        key=lambda item: (
            item.value_score,
            item.quality_score,
            item.context_length or 0,
        ),
        reverse=True,
    )

    selected = recommendations[:limit]
    for index, recommendation in enumerate(selected, start=1):
        recommendation.rank = index

    catalog = {
        model["id"]: model for model in raw_models
        if isinstance(model, dict) and model.get("id") and is_text_generation_model(model)
    }
    deployment_recommendations = await deployed_llm_recommendations(catalog)

    return OpenRouterRecommendationsResponse(
        generated_at=datetime.now(timezone.utc),
        source_url=OPENROUTER_MODELS_URL,
        pricing_note="OpenRouter publica pricing.prompt y pricing.completion como USD por token; aquí también se muestra USD por millón de tokens.",
        estimation_note="El ranking general asume 1000 tokens de entrada y 250 de salida. La comparación por LLM usa la carga indicada en cada fila; no incluye búsqueda web, caché, razonamiento interno ni descuentos.",
        recommendations=selected,
        deployment_recommendations=deployment_recommendations,
    )


@app.get("/config/validator-type-weights", response_model=dict)
async def get_validator_type_weights():
    return await get_validator_type_weights_document()


@app.put("/config/validator-type-weights", response_model=dict)
async def update_validator_type_weights(payload: ValidatorTypeWeightsUpdate):
    if not payload.weights:
        raise HTTPException(status_code=400, detail="Debes indicar al menos un peso")

    weights = validate_validator_type_weights(payload.weights)
    now = datetime.now(timezone.utc)
    set_values = {f"weights.{name}": value for name, value in weights.items()}
    set_values["updated_at"] = now
    await config_collection.update_one(
        {"_id": VALIDATOR_TYPE_WEIGHTS_CONFIG_ID},
        {
            "$set": set_values,
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    logger.info(f"Validator type weights updated: {weights}")
    return await get_validator_type_weights_document()


@app.post("/clients", response_model=dict, status_code=201)
async def create_client(client: ClientCreate):
    existing = await quotas_collection.find_one({"client_id": client.client_id})
    if existing:
        raise HTTPException(status_code=400, detail="El cliente ya existe.")
    
    await quotas_collection.insert_one(client.model_dump())
    name_log = f" ({client.name})" if client.name else ""
    logger.info(f"👤 New client registered: {client.client_id}{name_log}")
    return {"status": "success", "message": f"Cliente {client.client_id} creado correctamente."}


@app.get("/clients", response_model=List[ClientResponse])
async def list_clients(
    status: Optional[ClientStatus] = Query(None, description="Filtrar por estado"), 
    name: Optional[str] = Query(None, description="Búsqueda parcial por nombre")
):
    """
    Lista clientes permitiendo filtrar por estado y/o nombre.
    """
    query = {}
    if status:
        query["status"] = status.value
    if name:
        query["name"] = {"$regex": name, "$options": "i"}
        
    cursor = quotas_collection.find(query, {"_id": 0})
    clients = await cursor.to_list(length=100)
    return clients


@app.get("/clients/{client_id}", response_model=ClientResponse)
async def get_client_quotas(client_id: str):
    client_doc = await quotas_collection.find_one({"client_id": client_id}, {"_id": 0})
    if not client_doc:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    return client_doc


@app.patch("/clients/{client_id}", response_model=dict)
async def update_client(client_id: str, update_data: ClientUpdate):
    update_dict = update_data.model_dump(exclude_unset=True)
    if not update_dict:
        raise HTTPException(status_code=400, detail="No se enviaron datos.")

    mongo_update_query = {"$set": {}}

    # Lógicas inteligentes de fechas basadas en estado
    if update_data.status == ClientStatus.BAJA and update_data.deactivate_date is None:
        mongo_update_query["$set"]["deactivate_date"] = datetime.now(timezone.utc)
    elif update_data.status == ClientStatus.ALTA:
         mongo_update_query["$set"]["deactivate_date"] = None

    # Transformación dot notation para MongoDB
    for main_key, value in update_dict.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                mongo_update_query["$set"][f"{main_key}.{sub_key}"] = sub_value
        else:
            if main_key not in mongo_update_query["$set"]:
                mongo_update_query["$set"][main_key] = value.value if isinstance(value, Enum) else value

    if not mongo_update_query["$set"]:
         raise HTTPException(status_code=400, detail="Estructura inválida.")

    result = await quotas_collection.update_one({"client_id": client_id}, mongo_update_query)
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")

    logger.info(f"⚙️ Client {client_id} updated.")
    return {"status": "success", "message": "Cliente actualizado correctamente."}


@app.delete("/clients/{client_id}", response_model=dict)
async def delete_client(client_id: str):
    """
    Elimina un cliente de la base de datos de cuotas.
    """
    result = await quotas_collection.delete_one({"client_id": client_id})
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
        
    logger.info(f"🗑️ Client {client_id} deleted from the database.")
    return {"status": "success", "message": f"Cliente {client_id} eliminado correctamente."}


# =========================================================
# Ciclo de vida de FastAPI
# =========================================================
@app.on_event("startup")
async def startup_event():
    global mongo_client, db, orders_collection, quotas_collection, config_collection

    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[MONGO_DBNAME]
    orders_collection = db[ORDERS_COLLECTION_NAME]
    quotas_collection = db[QUOTAS_COLLECTION_NAME]
    config_collection = db[CONFIG_COLLECTION_NAME]
    
    now = datetime.now(timezone.utc)
    await config_collection.update_one(
        {"_id": VALIDATOR_TYPE_WEIGHTS_CONFIG_ID},
        {
            "$setOnInsert": {
                "weights": default_validator_type_weights(),
                "created_at": now,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    await quotas_collection.create_index("client_id", unique=True)
    await orders_collection.create_index("order_id")
    await orders_collection.create_index("postId")
    
    logger.info("💽 Connected to MongoDB (Orders & Quotas)")
    asyncio.create_task(consume_responses_for_quotas())

@app.on_event("shutdown")
async def shutdown_event():
    global consumer, mongo_client
    if consumer:
        await consumer.stop()
    if mongo_client:
        mongo_client.close()
    logger.info("🛑 Gateway Quota Manager shut down.")
