# gateway_quotas.py
import os
import json
import math
import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from fastapi import FastAPI, HTTPException, Query
import httpx
from motor.motor_asyncio import AsyncIOMotorClient
from aiokafka import AIOKafkaConsumer
from pydantic import BaseModel, ValidationError
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

class OpenRouterRecommendationsResponse(BaseModel):
    generated_at: datetime
    source_url: str
    pricing_note: str
    estimation_note: str
    recommendations: List[OpenRouterModelRecommendation]


class ValidatorTypeWeightsUpdate(BaseModel):
    weights: Dict[str, float]

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

    return OpenRouterRecommendationsResponse(
        generated_at=datetime.now(timezone.utc),
        source_url=OPENROUTER_MODELS_URL,
        pricing_note="OpenRouter publica pricing.prompt y pricing.completion como USD por token; aquí también se muestra USD por millón de tokens.",
        estimation_note="estimated_validation_cost_usd asume una validación típica de 1000 tokens de entrada y 250 de salida.",
        recommendations=selected,
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
