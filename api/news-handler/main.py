import os
import uuid
import json
import asyncio
import logging
import hashlib
import requests
from bs4 import BeautifulSoup
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from bson import ObjectId


# =========================================================
# Cargar .env
# =========================================================
load_dotenv()

# =========================================================
# Config / Logging
# =========================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fake-news-orchestrator")

KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
KAFKA_USERNAME = os.getenv("KAFKA_USERNAME", "app")
KAFKA_PASSWORD = os.getenv("KAFKA_PASSWORD", "")
KAFKA_SECURITY_PROTOCOL = os.getenv("KAFKA_SECURITY_PROTOCOL", "SASL_PLAINTEXT")
KAFKA_MECHANISM = os.getenv("KAFKA_MECHANISM", "PLAIN")

TOPIC_REQUESTS_GENERATE = os.getenv("TOPIC_REQUESTS_GENERATE", "fake_news_requests_generate")
TOPIC_REQUESTS_IPFS = os.getenv("TOPIC_REQUESTS_IPFS", "fake_news_requests_ipfs")
TOPIC_REQUESTS_BLOCKCHAIN = os.getenv("TOPIC_REQUESTS_BLOCKCHAIN", "fake_news_requests_blockchain")
TOPIC_REQUESTS_VALIDATE = os.getenv("TOPIC_REQUESTS_VALIDATE", "fake_news_requests_validate")
TOPIC_RESPONSES = os.getenv("TOPIC_RESPONSES", "fake_news_responses")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb:27017")
MONGO_DBNAME = os.getenv("MONGO_DBNAME", "tfm")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "orders")

MAX_WORKERS = int(os.getenv("MAX_WORKERS", "1"))

EMULATE_BLOCKCHAIN_REQUESTS = os.getenv("EMULATE_BLOCKCHAIN_REQUESTS", "true").lower() == "true"

# =========================================================
# App & globals
# =========================================================
app = FastAPI(title="Fake News Orchestrator")
producer: Optional[AIOKafkaProducer] = None
consumer: Optional[AIOKafkaConsumer] = None
mongo_client: Optional[AsyncIOMotorClient] = None
db = None
orders_collection = None
order_locks = {}

# ---------- Models ----------
class PublishRequest(BaseModel):
    text: str
    
class EventModel(BaseModel):
    action: str
    topic: str
    timestamp: str
    payload: dict

# =========================================================
# Helpers DB & Kafka security
# =========================================================
def kafka_security_kwargs():
    # Return only keys if values exist (aiokafka will ignore empty values but be explicit)
    kwargs = {}
    if KAFKA_SECURITY_PROTOCOL:
        kwargs["security_protocol"] = KAFKA_SECURITY_PROTOCOL
    if KAFKA_MECHANISM:
        kwargs["sasl_mechanism"] = KAFKA_MECHANISM
    if KAFKA_USERNAME:
        kwargs["sasl_plain_username"] = KAFKA_USERNAME
    if KAFKA_PASSWORD:
        kwargs["sasl_plain_password"] = KAFKA_PASSWORD
    return kwargs

async def save_order_doc(order_doc: dict):
    global orders_collection
    await orders_collection.insert_one(order_doc)

async def update_order(order_id: str, update: dict):
    global orders_collection
    mongo_update = {}

    # Mantener $push si existe
    if "$push" in update:
        mongo_update["$push"] = update.pop("$push")

    # Si el update ya tiene $set, usarlo directamente
    if "$set" in update:
        mongo_update["$set"] = update.pop("$set")
    elif update:  # Si no, envolver todo en $set
        mongo_update["$set"] = update

    result = await orders_collection.update_one({"order_id": order_id}, mongo_update)
    if result.matched_count == 0:
        logger.error(f"Order {order_id} not found in MongoDB")


async def get_order_doc(order_id: str) -> Optional[dict]:
    doc = await orders_collection.find_one({"order_id": order_id})
    return doc

# ===========================
# Helpers para hashes
# ===========================

def hash_text_to_multihash(text: str) -> dict:
    """Genera un hash SHA-256 tipo multihash para enviar al smart contract."""
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {
        "hash_function": "0x12",  # sha2-256
        "hash_size": "0x20",      # 32 bytes
        "digest": "0x" + h
    }

async def get_order_lock(order_id: str):
    if order_id not in order_locks:
        order_locks[order_id] = asyncio.Lock()
    return order_locks[order_id]

# =========================================================
# 🟢 Helpers para logging de eventos y validaciones
# =========================================================
async def log_event(order_id: str, action: str, topic: str, payload: dict):
    """
    Registra un evento (entrada o salida) en la colección 'events'
    con formato uniforme: action, topic, timestamp, payload.
    """
    global db
    if not order_id:
        # Evitar insertar eventos sin order_id
        logger.warning(f"Evento con order_id vacío ignorado: action={action}, topic={topic}")
        return

    events_col = db["events"]
    event_doc = {
        "order_id": order_id,
        "action": action,
        "topic": topic,
        "timestamp": asyncio.get_event_loop().time(),
        "payload": payload,
    }
    await events_col.insert_one(event_doc)
    logger.info(f"[{order_id}] 🟢 Evento '{action}' registrado en MongoDB ({topic}).")


async def log_validation(order_id: str, post_id: str, id_assertion: str, id_validator: str, approval: bool, tx_hash: str, payload: dict):
    """
    Registra una validación completada en la colección 'validations'.
    """
    global db
    if not order_id:
        logger.warning(f"Intento de log_validation sin order_id, ignorado.")
        return

    validations_col = db["validations"]
    val_doc = {
        "order_id": order_id,
        "postId": post_id,
        "idAssertion": id_assertion,
        "idValidator": id_validator,
        "approval": approval,
        "tx_hash": tx_hash,
        "payload": payload,
        "timestamp": asyncio.get_event_loop().time()
    }
    await validations_col.insert_one(val_doc)
    logger.info(f"[{order_id}] 🟢 Validación registrada en MongoDB (Assertion={id_assertion}, Validator={id_validator}).")

# ===========================
# Emulación / manejo blockchain
# ===========================
async def handle_blockchain_request(order_id: str, text: str, cid: str, assertions: list):
    global producer
    if EMULATE_BLOCKCHAIN_REQUESTS:
        hash_text = hash_text_to_multihash(text)
        asertions_hashed = []
        validator_addresses_matrix = []

        for a in assertions:
            mh = hash_text_to_multihash(a.get("text", ""))
            id_assertion = a.get("idAssertion") or str(uuid.uuid4().hex[:8])
            asertions_hashed.append({
                "hash_asertion": mh,
                "idAssertion": id_assertion,
                "text": a.get("text", ""),
                "categoryId": a.get("categoryId", 0)
            })
            # Simulamos validadores si estamos en modo emulado
            fake_validators = ["VAL1", "VAL2"]
            validator_addresses_matrix.append([{"Address": v} for v in fake_validators])

        simulated_msg = {
            "action": "blockchain_registered",
            "order_id": order_id,
            "payload": {
                "postId": 1,
                "hash_text": hash_text,
                "assertions": asertions_hashed,
                "validatorAddressesByAsertion": validator_addresses_matrix,
                "tx_hash": "0xSIMULATEDTXHASH1234567890abcdef"
            }
        }
        await producer.send_and_wait(TOPIC_RESPONSES, json.dumps(simulated_msg).encode("utf-8"))
        logger.info(f"[{order_id}] Mensaje 'blockchain_registered' EMULADO publicado")

        # Registrar evento de salida (publicación a topic responses)
        await log_event(order_id, simulated_msg["action"], TOPIC_RESPONSES, simulated_msg["payload"])
    else:
        # Mensaje real al topic de blockchain
        message = {
            "action": "register_blockchain",
            "order_id": order_id,
            "payload": {
                "text": text,
                "cid": cid,
                "assertions": assertions,
                "publisher": "news-handler"
            }
        }
        await producer.send_and_wait(TOPIC_REQUESTS_BLOCKCHAIN, json.dumps(message).encode("utf-8"))
        logger.info(f"[{order_id}] Mensaje enviado al topic {TOPIC_REQUESTS_BLOCKCHAIN}")

        # Registrar evento de salida
        await log_event(order_id, message["action"], TOPIC_REQUESTS_BLOCKCHAIN, message["payload"])

# =========================================================
# Procesador genérico de mensajes Kafka (reutilizable)
# =========================================================
async def process_kafka_message(data: dict):
    """
    data: dict ya decodificado del JSON del mensaje Kafka.
    Maneja: assertions_generated, ipfs_uploaded, blockchain_registered, validation_completed.
    """
    try:
        action = data.get("action")
        order_id = data.get("order_id")
        payload = data.get("payload", {})

        if not action or not order_id:
            logger.warning("⚠️ Mensaje Kafka sin 'action' o 'order_id', ignorado.")
            return

        # Registrar evento de entrada con formato uniforme
        await log_event(order_id, action, TOPIC_RESPONSES, payload)

        logger.info(f"📨 [{order_id}] Procesando acción '{action}'...")

        # ================================================================
        # 1️⃣ assertions_generated
        # ================================================================
        if action == "assertions_generated":
            logger.info(f"[{order_id}] 🧩 Recibido 'assertions_generated'.")
            doc = await get_order_doc(order_id)
            if not doc:
                logger.warning(f"[{order_id}] ⚠️ Documento no encontrado en DB.")
                return

            assertions = payload.get("assertions", [])
            if not assertions:
                logger.warning(f"[{order_id}] ⚠️ Payload vacío de aserciones.")
                return

            document = {
                "order_id": order_id,
                "text": doc["text"],
                "assertions": assertions,
                "metadata": {
                    "generated_by": "news-handler",
                    "timestamp": asyncio.get_event_loop().time()
                }
            }

            await update_order(order_id, {
                "assertions": assertions,
                "document": document,
                "status": "DOCUMENT_CREATED"
                #,"$push": {"history": {"event": "assertions_generated", "payload": payload}}
            })
            logger.info(f"[{order_id}] 📄 Documento y aserciones guardadas en MongoDB.")

            # Enviar upload_ipfs request
            msg_ipfs = {
                "action": "upload_ipfs",
                "order_id": order_id,
                "payload": {"document": document}
            }
            await producer.send_and_wait(TOPIC_REQUESTS_IPFS, json.dumps(msg_ipfs).encode("utf-8"))
            logger.info(f"[{order_id}] 🌐 Documento enviado al servicio IPFS ({TOPIC_REQUESTS_IPFS}).")

            # Registrar evento de salida (upload_ipfs)
            await log_event(order_id, msg_ipfs["action"], TOPIC_REQUESTS_IPFS, msg_ipfs["payload"])

            await update_order(order_id, {
                "status": "IPFS_PENDING"
                #,"$push": {"history": {"event": "upload_ipfs_requested"}}
            })

        # ================================================================
        # 2️⃣ ipfs_uploaded
        # ================================================================
        elif action == "ipfs_uploaded":
            logger.info(f"[{order_id}] 🌐 Recibido 'ipfs_uploaded'.")
            doc = await get_order_doc(order_id)
            if not doc:
                logger.warning(f"[{order_id}] ⚠️ Documento no encontrado para IPFS update.")
                return

            cid = payload.get("cid")
            if not cid:
                logger.warning(f"[{order_id}] ⚠️ Falta 'cid' en payload.")
                return

            text = doc.get("text", "")
            await update_order(order_id, {
                "cid": cid,
                "status": "IPFS_UPLOADED"
                #,"$push": {"history": {"event": "ipfs_uploaded", "payload": payload}}
            })
            logger.info(f"[{order_id}] ✅ IPFS subido con CID={cid}")

            # Modo emulado → Generar blockchain_registered o mandar request real
            await handle_blockchain_request(order_id, text, cid, doc.get("assertions", []))
            await update_order(order_id, {
                "status": "BLOCKCHAIN_PENDING"
                #,"$push": {"history": {"event": "register_blockchain_sent"}}
            })
            logger.info(f"[{order_id}] ⛓️ Petición de registro blockchain enviada (emulada o real según configuración).")

        # ================================================================
        # 3️⃣ blockchain_registered
        # ================================================================
        elif action == "blockchain_registered":
            logger.info(f"[{order_id}] ⛓️ Recibido 'blockchain_registered'.")
            logger.info(f"[{order_id}] 🧾 Payload blockchain_registered: {json.dumps(payload, indent=2)}")

            postId = payload.get("postId")
            tx_hash = payload.get("tx_hash")
            hash_text = payload.get("hash_text")
            
            assertions_payload = payload.get("assertions", [])

            if not assertions_payload:
                logger.warning(f"[{order_id}] ⚠️ blockchain_registered sin assertions, abortando.")
                return

            doc = await get_order_doc(order_id)
            if not doc:
                logger.warning(f"[{order_id}] ❌ Documento no encontrado en MongoDB.")
                return

            validators_info = []
            for i, a in enumerate(assertions_payload):
                assertion_id = a.get("idAssertion")
                assertion_text = a.get("text")
                category_id = int(a.get("categoryId", 0))

                # Acepta strings o dicts y elimina duplicados
                validator_addresses = set(
                    v["Address"] if isinstance(v, dict) else v
                    for v in a.get("validatorAddresses", [])
                )

                validator_addresses = list(validator_addresses)  # volver a lista

                logger.info(f"[{order_id}] 🧩 Aserción #{i+1}: id={assertion_id}, texto='{(assertion_text or '')[:70]}...', categoria={category_id}")
                logger.debug(f"[{order_id}] ⚙️ Validadores únicos: {validator_addresses}")

                validators_info.append({
                    "idAssertion": assertion_id,
                    "validatorAddresses": validator_addresses,
                    "text": assertion_text,
                    "categoryId": category_id
                })

            await update_order(order_id, {
                "validators": validators_info,
                "validators_pending": sum(len(v["validatorAddresses"]) for v in validators_info),
                "status": "VALIDATION_PENDING",
                "postId": postId,
                "tx_hash": tx_hash,
                "hash_text": hash_text
                #,"$push": {"history": {"event": "blockchain_registered", "payload": payload}}
            })
            
            logger.info(f"[{order_id}] ✅ Validadores guardados en MongoDB ({len(validators_info)} aserciones).")

            # Enviar requests de validación
            for val in validators_info:
                id_assert = val["idAssertion"]
                text_assert = val["text"]
                for validator_addr in val["validatorAddresses"]:
                    msg_validation = {
                        "action": "request_validation",
                        "order_id": order_id,
                        "payload": {
                            "postId": str(payload.get("postId")), 
                            "idValidator": validator_addr,
                            "idAssertion": id_assert,
                            "text": text_assert,
                            "context": doc.get("text", "")
                        }
                    }
                    logger.debug(f"[{order_id}] 🧮 Construido mensaje validación -> {validator_addr}: {json.dumps(msg_validation, indent=2)}")
                    await producer.send_and_wait(
                        TOPIC_REQUESTS_VALIDATE,
                        json.dumps(msg_validation).encode("utf-8")
                    )
                    logger.info(f"[{order_id}] 📤 Enviada validación a {validator_addr} para aserción {id_assert} y postId {payload.get('postId')}.")

                    # Registrar evento de salida (request_validation)
                    await log_event(order_id, msg_validation["action"], TOPIC_REQUESTS_VALIDATE, msg_validation["payload"])

            total_validators = sum(len(v['validatorAddresses']) for v in validators_info)
            logger.info(f"[{order_id}] 🎯 Envío de validaciones completado ({total_validators} totales).")

        # ================================================================
        # 4️⃣ validation_completed
        # ================================================================
        elif action == "validation_completed":
            postId = str(payload.get("postId", ""))
            id_val = payload.get("idValidator")
            id_assert = str(payload.get("idAssertion"))
            status_val = payload.get("approval")
            assertion_text = payload.get("text", "")
            tx_hash = payload.get("tx_hash", "")

            logger.info(f"[{order_id}] 🧩 Validación recibida -> postId={postId}, Assertion={id_assert}, Validator={id_val}, Approval={status_val}")

            if not id_val or not id_assert:
                logger.warning(f"[{order_id}] ⚠️ validation_completed sin idValidator o idAssertion, ignorando.")
                return

            lock = await get_order_lock(order_id)
            async with lock:
                doc = await get_order_doc(order_id)
                if not doc:
                    logger.warning(f"[{order_id}] ❌ Documento no encontrado para validation_completed.")
                    return

                validations = doc.get("validations", {})
                if id_assert not in validations:
                    validations[id_assert] = {}

                already_done = id_val in validations[id_assert]
                if already_done:
                    logger.info(f"[{order_id}] ⚠️ Validación duplicada ignorada (Assertion={id_assert}, Validator={id_val}).")
                    return

                validations[id_assert][id_val] = {
                    "approval": status_val,
                    "text": assertion_text,
                    "tx_hash": tx_hash
                }

                await update_order(order_id, {"$set": {"validations": validations}})
                logger.info(f"[{order_id}] ✅ Validación registrada Assertion={id_assert}, Validator={id_val}.")

                # Registrar validación en colección 'validations'
                await log_validation(order_id, postId, id_assert, id_val, status_val, tx_hash, payload)

                validators_cfg = doc.get("validators", [])
                total_pending = 0
                for v in validators_cfg:
                    aid = str(v["idAssertion"])
                    expected = set(v["validatorAddresses"])
                    done = set(validations.get(aid, {}).keys())
                    pending = expected - done
                    total_pending += len(pending)
                    logger.info(
                        f"[{order_id}] 🧮 Assertion {aid}: {len(done)}/{len(expected)} completadas. Pendientes: {list(pending) if pending else 'NINGUNO'}"
                    )

                await update_order(order_id, {"$set": {"validators_pending": total_pending}})
                logger.info(f"[{order_id}] 📊 Validadores pendientes totales: {total_pending}")

                if total_pending == 0:
                    await update_order(order_id, {"$set": {"status": "VALIDATED"}})
                    logger.info(f"[{order_id}] 🎯 Todas las validaciones completadas. Noticia VALIDADA.")
                else:
                    logger.info(f"[{order_id}] 🕓 Aún quedan {total_pending} validaciones pendientes.")

        # ================================================================
        # Acción desconocida
        # ================================================================
        else:
            logger.warning(f"[{order_id}] ⚠️ Acción desconocida recibida: {action}")

    except Exception as e:
        logger.exception(f"❌ Error procesando mensaje Kafka: {e}")

# =========================================================
# Kafka consumer loop
# =========================================================
async def consume_responses_loop():
    global consumer
    logger.info("Starting consume_responses_loop (listening to responses)")

    consumer = AIOKafkaConsumer(
        TOPIC_RESPONSES,
        bootstrap_servers=KAFKA_BROKER,
        group_id="fake-news-orchestrator-group",
        auto_offset_reset="earliest",
        **kafka_security_kwargs()
    )
    await consumer.start()
    logger.info(f"Kafka consumer subscribed to {TOPIC_RESPONSES}")

    try:
        async for msg in consumer:
            try:
                raw = msg.value.decode("utf-8")
                data = json.loads(raw)
                await process_kafka_message(data)
            except Exception as e:
                logger.exception("Error processing Kafka message: %s", e)
    except Exception as e:
        logger.exception("Fatal error in consume_responses_loop: %s", e)
    finally:
        await consumer.stop()

# =========================================================
# FastAPI endpoints
# =========================================================
@app.post("/publishNew", status_code=202)
async def publish_new(req: PublishRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text")

    order_id = str(uuid.uuid4())
    order_doc = {
        "order_id": order_id,
        "status": "PENDING",
        "text": text,
        "cid": None,
        "postId": None,
        "hash_text": None,
        "tx_hash": None,
        "validators_pending": None,
        "assertions": None,
        "document": None,
        "validators": None
    }
    await save_order_doc(order_doc)
    logger.info(f"[{order_id}] Order saved in MongoDB, status=PENDING")

    # Publicar petición a generar aserciones
    message = {
        "action": "generate_assertions",
        "order_id": order_id,
        "payload": {"text": text}
    }
    await producer.send_and_wait(TOPIC_REQUESTS_GENERATE, json.dumps(message).encode("utf-8"))
    logger.info(f"[{order_id}] Published generate_assertions to Kafka topic {TOPIC_REQUESTS_GENERATE}")

    # Registrar evento de salida (generate_assertions)
    await log_event(order_id, message["action"], TOPIC_REQUESTS_GENERATE, message["payload"])

    # update status
    await update_order(order_id, {"status": "ASSERTIONS_REQUESTED"#, "$push": {"history": {"event": "sent_generate_assertions"}}
                                  })
    return {"order_id": order_id, "status": "ASSERTIONS_REQUESTED"}

@app.get("/orders/{order_id}")
async def get_order(order_id: str):
    order = await orders_collection.find_one({"order_id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Convertimos el ObjectId en string
    order["_id"] = str(order["_id"])
    return order

@app.get("/news/{order_id}/events", response_model=List[EventModel])
async def get_news_events(order_id: str):
    """Devuelve todos los eventos asociados a una noticia."""
    cursor = db.events.find({"order_id": order_id}, {"_id": 0})
    events = await cursor.to_list(length=100)

    if not events:
        raise HTTPException(status_code=404, detail="No hay eventos para esta noticia")

    # 🔹 Convertir timestamp numérico a string
    for e in events:
        if not isinstance(e.get("timestamp"), str):
            e["timestamp"] = str(e["timestamp"])

    return events



from bson import ObjectId

@app.get("/news")
async def list_news():
    """Devuelve todas las noticias con order_id, estado, hash_text y fecha de creación (derivada del _id)."""
    cursor = db.news.find({}, {"_id": 1, "order_id": 1, "status": 1, "hash_text": 1})
    news_list = await cursor.to_list(length=1000)

    if not news_list:
        raise HTTPException(status_code=404, detail="No hay noticias registradas")

    # Convertir _id a fecha de creación
    for news in news_list:
        oid = ObjectId(news["_id"])
        news["created_at"] = oid.generation_time.isoformat()
        del news["_id"]

    return news_list



from bson import ObjectId

@app.post("/find-order-by-text")
async def find_order_by_text(request: PublishRequest):
    """
    Recibe un texto, calcula su hash SHA256 (multihash) y busca
    en MongoDB todas las órdenes cuyo hash_text.digest coincida.
    Devuelve order_id, estado y fecha de creación derivada del _id.
    """
    global orders_collection
    try:
        if not request.text:
            raise HTTPException(status_code=400, detail="El campo 'text' no puede estar vacío.")

        # 1️⃣ Calcular hash SHA256 tipo multihash
        mh = hash_text_to_multihash(request.text)
        digest_hex = mh["digest"]

        logger.info(f"🧮 Buscando órdenes con hash_text={digest_hex}")

        # 2️⃣ Buscar todas las coincidencias en MongoDB
        cursor = orders_collection.find(
            {"hash_text": digest_hex},
            {"_id": 1, "order_id": 1, "status": 1, "hash_text": 1}
        )
        docs = await cursor.to_list(length=1000)

        if not docs:
            logger.warning("❌ No se encontró ninguna orden con ese hash_text.digest")
            raise HTTPException(status_code=404, detail="No se encontró ninguna orden con ese hash.")

        # 3️⃣ Convertir _id a fecha de creación
        for doc in docs:
            oid = ObjectId(doc["_id"])
            doc["created_at"] = oid.generation_time.isoformat()
            del doc["_id"]

        logger.info(f"✅ {len(docs)} coincidencia(s) encontrada(s).")

        # 4️⃣ Respuesta homogénea con /news
        return docs

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error en find_order_by_text: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/extract_text_from_url")
def extract_text_from_url(url: str = Query(..., description="URL de la noticia")):
    """
    Recupera el contenido de una URL y devuelve solo el texto limpio de la noticia.
    """
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=f"No se pudo acceder a la URL: {url}")

        soup = BeautifulSoup(resp.content, "html.parser")

        # Extraer solo texto visible, ignorando scripts y estilos
        for script_or_style in soup(["script", "style"]):
            script_or_style.extract()

        text = soup.get_text(separator="\n")
        # Limpiar líneas vacías
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        clean_text = "\n".join(lines)

        return {"url": url, "text": clean_text}

    except requests.RequestException as e:
        logger.error(f"Error accediendo a URL {url}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =========================================================
# Startup / Shutdown
# =========================================================
@app.on_event("startup")
async def startup_event():
    global producer, consumer, mongo_client, db, orders_collection

    # MongoDB
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[MONGO_DBNAME]
    orders_collection = db[MONGO_COLLECTION]
    logger.info(f"MongoDB connected at {MONGO_COLLECTION}")

    # Crear índices útiles
    try:
        await db["events"].create_index([("order_id", 1)])
        await db["events"].create_index([("action", 1)])
        await db["validations"].create_index([("order_id", 1)])
        logger.info("MongoDB indexes for events and validations ensured")
    except Exception as e:
        logger.warning(f"Could not create indexes: {e}")

    # Kafka producer
    producer = AIOKafkaProducer(
        bootstrap_servers=KAFKA_BROKER,
        **kafka_security_kwargs()
    )
    await producer.start()
    logger.info("Kafka producer started")

    # Kafka consumer (consume_responses_loop will create and start its own consumer)
    asyncio.create_task(consume_responses_loop())
    logger.info("Background consumer task started")

@app.on_event("shutdown")
async def shutdown_event():
    global producer, consumer, mongo_client
    if producer:
        await producer.stop()
    if consumer:
        await consumer.stop()
    if mongo_client:
        mongo_client.close()
    logger.info("Shutdown complete")
