# gateway_quotas.py
import os
import json
import asyncio
from datetime import datetime, timezone
from enum import Enum
from fastapi import FastAPI, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorClient
from aiokafka import AIOKafkaConsumer
from loguru import logger
from pydantic import BaseModel, Field, ValidationError
from typing import Optional, List

# =========================================================
# Importación de Modelos de Mensajes
# (Asegúrate de que la ruta 'common.async_models' es correcta en tu entorno)
# =========================================================
from common.async_models import (
    AssertionsGeneratedResponse,
    ValidationCompletedResponse
)

# =========================================================
# Modelos API REST (Gestión de Cuotas y Clientes)
# =========================================================
class ClientStatus(str, Enum):
    ALTA = "Active"
    BAJA = "Deactivated"
    SUSPENDIDO = "Suspended"

class QuotaDetail(BaseModel):
    news_generation: int = 0
    blockchain_validation: int = 0

class ClientBase(BaseModel):
    name: Optional[str] = Field(None, description="Nombre legible del cliente")
    limits: QuotaDetail = Field(default_factory=QuotaDetail, description="Límite máximo permitido")
    consumed: QuotaDetail = Field(default_factory=QuotaDetail, description="Cantidad ya consumida")
    status: ClientStatus = Field(default=ClientStatus.ALTA, description="Estado operativo del cliente")
    active_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    deactivate_date: Optional[datetime] = None

class ClientCreate(ClientBase):
    client_id: str

class ClientResponse(ClientCreate):
    pass

class ClientUpdate(BaseModel):
    name: Optional[str] = None
    limits: Optional[QuotaDetail] = None
    consumed: Optional[QuotaDetail] = None
    status: Optional[ClientStatus] = None
    deactivate_date: Optional[datetime] = None

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
            logger.warning(f"⚠️ Event '{action}' discarded. No client_id found in DB for OrderID={order_id} / PostID={post_id}.")
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
    global mongo_client, db, orders_collection, quotas_collection

    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[MONGO_DBNAME]
    orders_collection = db[ORDERS_COLLECTION_NAME]
    quotas_collection = db[QUOTAS_COLLECTION_NAME]
    
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