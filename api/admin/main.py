# gateway_quotas.py
import os
import json
import asyncio
from fastapi import FastAPI, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from aiokafka import AIOKafkaConsumer
from loguru import logger
from pydantic import BaseModel, Field, ValidationError
from typing import Optional

# =========================================================
# Importación de Modelos de Mensajes
# (Asegúrate de que la ruta 'common.async_models' es correcta en tu entorno)
# =========================================================
from common.async_models import (
    AssertionsGeneratedResponse,
    ValidationCompletedResponse
)

# =========================================================
# Modelos API REST (Gestión de Cuotas)
# =========================================================
class QuotaDetail(BaseModel):
    news_generation: int = 0
    blockchain_validation: int = 0

class ClientQuotaBase(BaseModel):
    limits: QuotaDetail = Field(default_factory=QuotaDetail, description="Límite máximo permitido")
    consumed: QuotaDetail = Field(default_factory=QuotaDetail, description="Cantidad ya consumida")

class ClientCreate(ClientQuotaBase):
    client_id: str

class QuotaUpdate(BaseModel):
    limits: Optional[QuotaDetail] = None
    consumed: Optional[QuotaDetail] = None

# =========================================================
# Configuración
# =========================================================
MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb:27017")
MONGO_DBNAME = os.getenv("MONGO_DBNAME", "tfm")
ORDERS_COLLECTION_NAME = os.getenv("ORDERS_COLLECTION", "orders")
QUOTAS_COLLECTION_NAME = os.getenv("QUOTAS_COLLECTION", "clients_quotas")

KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
TOPIC_RESPONSES = os.getenv("TOPIC_RESPONSES", "fake_news_responses")

# Mapeo de acciones cobrables y sus modelos
ACTION_TO_QUOTA_MODEL = {
    "assertions_generated": AssertionsGeneratedResponse,
    "validation_completed": ValidationCompletedResponse
}

BILLABLE_SERVICES = {
    "assertions_generated": "news_generation",
    "validation_completed": "blockchain_validation"
}

# =========================================================
# App & Globales
# =========================================================
app = FastAPI(title="Gateway - Quota Manager")
mongo_client = None
db = None
orders_collection = None
quotas_collection = None
consumer = None


# =========================================================
# Lógica de Base de Datos
# =========================================================
async def resolve_client_id(order_id: str = None, post_id: str = None) -> str:
    """
    Busca el client_id en la colección de órdenes (orders).
    Prioriza la búsqueda por order_id. Si no, usa postId.
    """
    if not order_id and not post_id:
        return None

    if order_id:
        doc = await orders_collection.find_one({"order_id": order_id}, {"client_id": 1})
        if doc and "client_id" in doc:
            return doc["client_id"]

    if post_id:
        doc = await orders_collection.find_one({"postId": str(post_id)}, {"client_id": 1})
        if doc and "client_id" in doc:
            return doc["client_id"]

    return None

async def record_consumption(client_id: str, service_type: str, cost: int = 1):
    """Incrementa el contador de consumo de un cliente."""
    consumed_field = f"consumed.{service_type}"
    try:
        await quotas_collection.update_one(
            {"client_id": client_id},
            {"$inc": {consumed_field: cost}},
            upsert=True
        )
        logger.info(f"💰 Cuota actualizada | Cliente: {client_id} | Servicio: {service_type} | +{cost}")
    except Exception as e:
        logger.error(f"❌ Error actualizando cuota para {client_id}: {e}")


# =========================================================
# Procesamiento de Kafka (Inspirado en el Orquestador)
# =========================================================
async def process_quota_event(data: dict):
    try:
        action = data.get("action")
        order_id = data.get("order_id")

        if not action:
            logger.warning("⚠️ Mensaje Kafka sin 'action', ignorado en Quotas.")
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
                logger.warning(f"⚠️ Mensaje '{action}' sin 'order_id' ni 'postId'. No se puede facturar.")
                return

        # 3. Validación Pydantic estricta
        try:
            parsed = model_cls(**data)
            # Reasignamos variables desde el modelo validado para mayor seguridad
            order_id = parsed.order_id
            
            # Extraemos el postId del payload solo si el modelo lo contempla (ej. ValidationCompleted)
            if hasattr(parsed.payload, "postId"):
                post_id = str(parsed.payload.postId)
                
            logger.info(f"[{order_id or post_id}] ✅ Mensaje cobrable '{action}' validado.")
        except ValidationError as e:
            logger.error(f"[{order_id or post_id}] ❌ Error de validación Pydantic para cobro '{action}': {e}")
            return

        # 4. Buscar a quién cobrarle
        client_id = await resolve_client_id(order_id=order_id, post_id=post_id)

        if not client_id:
            logger.warning(f"⚠️ Evento '{action}' descartado. No se encontró client_id en BD para OrderID={order_id} / PostID={post_id}.")
            return

        # 5. Ejecutar cobro
        await record_consumption(client_id, service_type, cost=1)

    except Exception as e:
        logger.exception(f"❌ Error inesperado procesando evento de cuota: {e}")


# =========================================================
# Bucle del Consumidor Kafka
# =========================================================
async def consume_responses_for_quotas():
    global consumer
    logger.info("🎧 Iniciando Quota Manager Kafka Consumer...")

    consumer = AIOKafkaConsumer(
        TOPIC_RESPONSES,
        bootstrap_servers=KAFKA_BROKER,
        # Importante: group_id único para no robarle mensajes al orquestador
        group_id="gateway-quota-billing-group", 
        auto_offset_reset="earliest"
    )
    await consumer.start()
    logger.info(f"✅ Quota Manager suscrito al topic: {TOPIC_RESPONSES}")

    try:
        async for msg in consumer:
            try:
                raw = msg.value.decode("utf-8")
                data = json.loads(raw)
                await process_quota_event(data)
            except json.JSONDecodeError:
                logger.error("❌ Recibido mensaje no-JSON en Kafka")
            except Exception as e:
                logger.exception(f"❌ Error leyendo mensaje Kafka: {e}")
    except Exception as e:
        logger.exception(f"💥 Error fatal en el bucle: {e}")
    finally:
        if consumer:
            await consumer.stop()


# =========================================================
# Endpoints REST
# =========================================================
@app.post("/clients", response_model=dict, status_code=201)
async def create_client(client: ClientCreate):
    existing = await quotas_collection.find_one({"client_id": client.client_id})
    if existing:
        raise HTTPException(status_code=400, detail="El cliente ya existe.")
    
    await quotas_collection.insert_one(client.model_dump())
    logger.info(f"👤 Nuevo cliente registrado: {client.client_id}")
    return {"status": "success", "message": f"Cliente {client.client_id} creado."}

@app.get("/clients/{client_id}/quotas", response_model=ClientQuotaBase)
async def get_client_quotas(client_id: str):
    client_doc = await quotas_collection.find_one({"client_id": client_id}, {"_id": 0})
    if not client_doc:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    return client_doc

@app.patch("/clients/{client_id}/quotas", response_model=dict)
async def update_client_quotas(client_id: str, update_data: QuotaUpdate):
    update_dict = update_data.model_dump(exclude_unset=True)
    if not update_dict:
        raise HTTPException(status_code=400, detail="No se enviaron datos.")

    mongo_update_query = {"$set": {}}
    for main_key, sub_dict in update_dict.items():
        if sub_dict:
            for sub_key, value in sub_dict.items():
                mongo_update_query["$set"][f"{main_key}.{sub_key}"] = value

    if not mongo_update_query["$set"]:
         raise HTTPException(status_code=400, detail="Estructura inválida.")

    result = await quotas_collection.update_one({"client_id": client_id}, mongo_update_query)
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")

    logger.info(f"⚙️ Cuotas actualizadas manualmente para: {client_id}")
    return {"status": "success", "message": "Cuotas actualizadas correctamente."}


# =========================================================
# Ciclo de vida de FastAPI
# =========================================================
@app.on_event("startup")
async def startup_event():
    global mongo_client, db, orders_collection, quotas_collection

    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[MONGO_DBNAME]
    orders_collection = db[ORDERS_COLLECTION_NAME]
    quotas_collection = db[QUOTAS_COLLECTION_NAME]
    
    await quotas_collection.create_index("client_id", unique=True)
    await orders_collection.create_index("order_id")
    await orders_collection.create_index("postId")
    
    logger.info("💽 Conectado a MongoDB (Orders & Quotas)")
    asyncio.create_task(consume_responses_for_quotas())

@app.on_event("shutdown")
async def shutdown_event():
    global consumer, mongo_client
    if consumer:
        await consumer.stop()
    if mongo_client:
        mongo_client.close()
    logger.info("🛑 Gateway Quota Manager apagado.")