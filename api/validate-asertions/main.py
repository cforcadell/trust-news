import os
import json
import uuid
import hashlib
import logging
import asyncio
from typing import List, Optional, Tuple, Any, Dict

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from web3 import Web3
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

# =========================================================
# Cargar .env
# =========================================================
load_dotenv()

# =========================================================
# Config desde .env
# =========================================================
RPC_URL = os.getenv("RPC_URL")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")  # 0x...
ACCOUNT_ADDRESS = os.getenv("ACCOUNT_ADDRESS")  # 0x...
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS")
CONTRACT_ABI_PATH = os.getenv("CONTRACT_ABI_PATH", "TrustManager.json")

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-tiny")
API_URL = os.getenv("API_URL")
VALIDATION_PROMPT = os.getenv(
    "VALIDATION_PROMPT",
    "Validame la siguiente aserción. Devuelve dos tags: 'resultado' (TRUE, FALSE o UNKNOWN) y 'descripcion'."
)

# VALIDATOR_CATEGORIES must be a JSON array in .env, e.g. VALIDATOR_CATEGORIES=[1,2,3]
VALIDATOR_CATEGORIES_RAW = os.getenv("VALIDATOR_CATEGORIES", "[]")

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
REQUEST_TOPIC = os.getenv("KAFKA_REQUEST_TOPIC", "fake_news_requests")
RESPONSE_TOPIC = os.getenv("KAFKA_RESPONSE_TOPIC", "fake_news_responses")
ENABLE_KAFKA_CONSUMER = os.getenv("ENABLE_KAFKA_CONSUMER", "false").lower() == "true"

EMULATE_BLOCKCHAIN_REQUESTS = os.getenv("EMULATE_BLOCKCHAIN_REQUESTS", "false").lower()  # True or False

# =========================================================
# Logging
# =========================================================
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("validate-asertions")

# =========================================================
# Parsear VALIDATOR_CATEGORIES
# =========================================================
try:
    VALIDATOR_CATEGORIES = json.loads(VALIDATOR_CATEGORIES_RAW)
    if not isinstance(VALIDATOR_CATEGORIES, list):
        raise ValueError("VALIDATOR_CATEGORIES must be a JSON list")
    VALIDATOR_CATEGORIES = [int(x) for x in VALIDATOR_CATEGORIES]
except Exception as e:
    logger.error(f"Error parsing VALIDATOR_CATEGORIES from .env: {e}; defaulting to empty list")
    VALIDATOR_CATEGORIES = []

# =========================================================
# Web3 + contract (cargar ABI desde JSON)
# =========================================================
if EMULATE_BLOCKCHAIN_REQUESTS == "false":
    if not RPC_URL or not CONTRACT_ADDRESS or not CONTRACT_ABI_PATH or not PRIVATE_KEY or not ACCOUNT_ADDRESS:
        logger.error("Faltan variables de entorno blockchain (RPC_URL, CONTRACT_ADDRESS, CONTRACT_ABI_PATH, PRIVATE_KEY, ACCOUNT_ADDRESS).")
        raise RuntimeError("Missing blockchain environment variables")

    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    try:
        with open(CONTRACT_ABI_PATH, "r", encoding="utf-8") as fh:
            artifact = json.load(fh)
        abi = artifact.get("abi", artifact)
        contract = w3.eth.contract(address=Web3.to_checksum_address(CONTRACT_ADDRESS), abi=abi)
        logger.info(f"Conectado a blockchain: {w3.is_connected()} - Account: {ACCOUNT_ADDRESS}")
    except Exception as e:
        logger.exception(f"Error cargando ABI/contrato: {e}")
        raise
else:
    logger.warning("⚠️ Blockchain en modo EMULADO. No se realizarán transacciones reales.")
    w3 = None
    contract = None

# =========================================================
# FastAPI app
# =========================================================
app = FastAPI(title="Validate Asertions API")

# =========================================================
# Pydantic Models
# =========================================================
class VerificarEntrada(BaseModel):
    texto: str
    contexto: Optional[str] = None

class RegistroValidacionModel(BaseModel):
    post_id: int
    assertion_id: int
    texto: str
    contexto: Optional[str] = None

class RegistroValidadorInput(BaseModel):
    nombre: str
    categorias: Optional[List[int]] = None

# =========================================================
# Helpers: Mistral call, hashing, tx send/wait
# =========================================================
def verificar_asercion(texto: str, contexto: Optional[str] = None) -> str:
    """Llama a la API de Mistral usando el prompt configurado en .env"""
    if not API_URL or not MISTRAL_API_KEY:
        raise HTTPException(status_code=500, detail="Mistral API configuration missing")

    headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"}
    contenido = f"{VALIDATION_PROMPT}\n\nTexto a analizar:\n{texto}"
    if contexto:
        contenido += f"\nContexto adicional:\n{contexto}"

    data = {"model": MISTRAL_MODEL, "messages": [{"role": "user", "content": contenido}], "temperature": 0.3}
    logger.info(f"Invocando Mistral para validar aserción (preview): {texto[:80]}...")
    resp = requests.post(API_URL, headers=headers, json=data)
    if resp.status_code == 200:
        return resp.json()["choices"][0]["message"]["content"]
    logger.error(f"Mistral API returned {resp.status_code}: {resp.text}")
    raise HTTPException(status_code=resp.status_code, detail=resp.text)

def hash_text_to_bytes(text: str) -> bytes:
    """SHA256 hex -> bytes (32 bytes)"""
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return bytes.fromhex(h)

def send_signed_tx(function_call, gas_estimate: int = 1000000) -> str:
    """Construye, firma y envía tx; devuelve tx_hash (hex) — no espera minado."""
    if EMULATE_BLOCKCHAIN_REQUESTS == "true":
        fake_hash = f"0x{uuid.uuid4().hex[:64]}"
        logger.info(f"[EMULADO] send_signed_tx -> {fake_hash}")
        return fake_hash

    nonce = w3.eth.get_transaction_count(ACCOUNT_ADDRESS, "pending")
    tx = function_call.build_transaction({
        "from": ACCOUNT_ADDRESS,
        "nonce": nonce,
        "gas": gas_estimate,
        "gasPrice": w3.eth.gas_price
    })
    signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    tx_hash_hex = tx_hash.hex()
    logger.info(f"Transacción enviada: {tx_hash_hex}")
    return tx_hash_hex

def wait_for_receipt_blocking(tx_hash: str, timeout: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Bloqueante: espera al minado y devuelve diccionario receipt (o None si falla)."""
    if EMULATE_BLOCKCHAIN_REQUESTS == "true":
        fake_receipt = {"transactionHash": tx_hash, "blockNumber": 0, "status": 1}
        logger.info(f"[EMULADO] wait_for_receipt -> {fake_receipt}")
        return fake_receipt

    try:
        # w3.eth.wait_for_transaction_receipt aceptará timeout si se especifica
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
        # convertir atributos del receipt a dict simple
        receipt_dict = {
            "transactionHash": receipt.transactionHash.hex() if hasattr(receipt, "transactionHash") else tx_hash,
            "blockNumber": getattr(receipt, "blockNumber", None),
            "status": getattr(receipt, "status", None),
            "logs": [dict(l) for l in getattr(receipt, "logs", [])]  # logs no serializables completamente; kept minimal
        }
        logger.info(f"Receipt obtenido: tx={receipt_dict['transactionHash']}, block={receipt_dict['blockNumber']}, status={receipt_dict['status']}")
        return receipt_dict
    except Exception as e:
        logger.error(f"Error esperando receipt de {tx_hash}: {e}")
        return None

# =========================================================
# Funciones internas reutilizables
# =========================================================
def registrar_validacion_internal(post_id: int, assertion_id: int, texto: str, contexto: Optional[str] = None) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    1) Verifica la aserción (Mistral)
    2) Envía la transacción addValidation
    3) Espera al minado y devuelve (tx_hash, receipt_dict)
    Nota: función BLOQUEANTE; ejecutar con asyncio.to_thread desde handlers async.
    """
    try:
        veredict_text = verificar_asercion(texto, contexto)
        veredict_bool = "TRUE" in veredict_text.upper()
        digest_bytes = hash_text_to_bytes(veredict_text)

        logger.info(f"Veredicto (bool): {veredict_bool} — preparando tx addValidation (post {post_id}, assertion {assertion_id})")

        if EMULATE_BLOCKCHAIN_REQUESTS == "true":
            tx_hash = f"0x{uuid.uuid4().hex[:64]}"
            receipt = {"transactionHash": tx_hash, "blockNumber": 0, "status": 1}
            logger.info(f"[EMULADO] Validación simulada: {tx_hash}")
            return tx_hash, receipt

        func_call = contract.functions.addValidation(
            int(post_id),
            int(assertion_id),
            bool(veredict_bool),
            {
                "hash_function": b"\x12",
                "hash_size": b"\x20",
                "digest": digest_bytes
            }
        )
        tx_hash = send_signed_tx(func_call)
        receipt = wait_for_receipt_blocking(tx_hash)
        return tx_hash, receipt
    except HTTPException:
        # propaga errores de Mistral al caller (para logging/response)
        raise
    except Exception as e:
        logger.exception(f"Error en registrar_validacion_internal: {e}")
        return None, None

def consultar_tx_status_internal(tx_hash: str) -> Dict[str, Any]:
    """Consulta receipt y devuelve un dict con status y detalles (no bloqueante)."""
    if EMULATE_BLOCKCHAIN_REQUESTS == "true":
        return {"status": "mined", "result": True, "tx_hash": tx_hash, "receipt": {"transactionHash": tx_hash, "status": 1, "blockNumber": 0}}

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
def registrar_validador_blockchain(name: str, categories: List[int]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Registra validador y espera minado.
    Devuelve (tx_hash, receipt_dict) o (None, None) en error.
    Bloqueante: usar asyncio.to_thread en el event loop.
    """
    try:
        logger.info(f"Inicio registrar_validador_blockchain -> name: {name}, categories: {categories}")

        if EMULATE_BLOCKCHAIN_REQUESTS == "true":
            tx_hash = f"0x{uuid.uuid4().hex[:64]}"
            fake_receipt = {"transactionHash": tx_hash, "blockNumber": 0, "status": 1}
            logger.info(f"[EMULATE] Transacción simulada: {tx_hash}, receipt: {fake_receipt}")
            return tx_hash, fake_receipt

        # Preparar llamada al contrato
        fn = contract.functions.registerValidator(name, categories)

        # Enviar transacción
        tx_hash = send_signed_tx(fn)
        logger.info(f"Transacción enviada: {tx_hash}")

        # Esperar a que se mine
        receipt = wait_for_receipt_blocking(tx_hash)
        logger.info(f"Receipt recibido: {receipt}")

        return tx_hash, receipt

    except Exception as e:
        logger.exception(f"Error al registrar validador en blockchain: {e}")
        return None, None


# =========================================================
# Endpoints HTTP (sincronicos desde la perspectiva del caller)
# =========================================================
@app.post("/verificar")
def endpoint_verificar(body: VerificarEntrada):
    resultado = verificar_asercion(body.texto, body.contexto)
    return {"verificación": resultado}

@app.post("/registrar_validacion")
async def endpoint_registrar_validacion(body: RegistroValidacionModel):
    """
    Ejecuta registrar_validacion_internal en un thread para no bloquear event loop.
    Devuelve tx_hash y receipt (o error).
    """
    try:
        tx_hash, receipt = await asyncio.to_thread(registrar_validacion_internal, body.post_id, body.assertion_id, body.texto, body.contexto)
        if tx_hash is None:
            raise HTTPException(status_code=500, detail="Error al registrar validación (ver logs).")
        return {"tx_hash": tx_hash, "receipt": receipt}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"endpoint_registrar_validacion error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tx-status/{tx_hash}")
async def endpoint_tx_status(tx_hash: str):
    """Consulta el estado de la tx (no bloqueante)."""
    result = consultar_tx_status_internal(tx_hash)
    return result

@app.post("/registrar_validador")
async def endpoint_registrar_validador(input: RegistroValidadorInput):
    """Registra validador (usa VALIDATOR_CATEGORIES si no se pasan). Espera minado."""
    categorias = input.categorias if input.categorias is not None else VALIDATOR_CATEGORIES
    try:
        tx_hash, receipt = await asyncio.to_thread(registrar_validador_blockchain, input.nombre, categorias or [])
        if tx_hash is None:
            raise HTTPException(status_code=500, detail="Error registrando validador.")
        return {"status": "ok", "tx_hash": tx_hash, "receipt": receipt}
    except Exception as e:
        logger.exception(f"endpoint_registrar_validador error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =========================================================
# Kafka consumer (asincrónico) — usa internals y espera minado
# =========================================================
async def consume_and_process():
    consumer = AIOKafkaConsumer(
        REQUEST_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=f"validate-asertions-{ACCOUNT_ADDRESS}",
        auto_offset_reset="earliest"
    )
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP)
    await consumer.start()
    await producer.start()
    logger.info("Kafka consumer y producer iniciados (background)")

    try:
        async for msg in consumer:
            try:
                payload = json.loads(msg.value.decode())
                action = payload.get("action")
                idValidator = payload.get("payload", {}).get("idValidator")

                if action != "request_validation" or idValidator != ACCOUNT_ADDRESS:
                    logger.info(f"Kafka: mensaje ignorado (action={action}, idValidator={idValidator})")
                    continue

                order_id = str(payload.get("order_id", "0"))
                assertion = payload["payload"].get("text", "")
                assertion_id = payload["payload"].get("idAssertion", "0")
                context = payload["payload"].get("context", "")

                logger.info(f"Kafka: validando assertion_id={assertion_id} (order {order_id})")

                # Ejecutar la lógica interna que verifica, envía y espera el minado
                tx_hash, receipt = await asyncio.to_thread(
                    registrar_validacion_internal,
                    int(order_id),
                    int(assertion_id),
                    assertion,
                    context
                )

                if not tx_hash:
                    logger.error(f"Kafka: error al generar tx para assertion {assertion_id}")
                    # enviar un mensaje de fallo opcional
                    await producer.send_and_wait(RESPONSE_TOPIC, json.dumps({
                        "action": "validation_failed",
                        "order_id": order_id,
                        "payload": {"idAssertion": assertion_id, "error": "tx_failed"}
                    }).encode())
                    continue

                # receipt puede ser None si hubo fallo esperando minado
                if receipt and receipt.get("status") == 1:
                    response_msg = {
                        "action": "validation_completed",
                        "order_id": order_id,
                        "payload": {
                            "idAssertion": assertion_id,
                            "idValidator": ACCOUNT_ADDRESS,
                            "approval": "TRUE" if "TRUE" in str(receipt).upper() else "UNKNOWN",
                            "text": assertion,
                            "tx_hash": tx_hash,
                            "receipt": receipt
                        }
                    }
                else:
                    response_msg = {
                        "action": "validation_failed",
                        "order_id": order_id,
                        "payload": {
                            "idAssertion": assertion_id,
                            "idValidator": ACCOUNT_ADDRESS,
                            "error": "tx_mined_failed_or_no_receipt",
                            "tx_hash": tx_hash,
                            "receipt": receipt
                        }
                    }

                await producer.send_and_wait(RESPONSE_TOPIC, json.dumps(response_msg).encode())
                logger.info(f"Kafka: publicado resultado para order_id={order_id}")

            except Exception as e:
                logger.exception(f"Error procesando mensaje Kafka: {e}")
    finally:
        await consumer.stop()
        await producer.stop()
        logger.info("Kafka detenido")

# =========================================================
# Startup: lanzar kafka consumer y registrar validador si hace falta
# =========================================================
@app.on_event("startup")
async def startup_event():
    # iniciar Kafka consumer si está habilitado
    if ENABLE_KAFKA_CONSUMER == "true":
        asyncio.create_task(consume_and_process())
        logger.info("Kafka consumer iniciado en background")

    # registrar validador en startup (si no está registrado)
    if EMULATE_BLOCKCHAIN_REQUESTS == "false":
        try:
            # Comprobar registro existente (si la llamada falla, procedemos a registrar)
            try:
                val_info = contract.functions.validators(ACCOUNT_ADDRESS).call()
                already = val_info[0] if isinstance(val_info, (list, tuple)) and len(val_info) > 0 else None
                if already and str(already) != "0x0000000000000000000000000000000000000000":
                    logger.info("Validador ya registrado en blockchain.")
                    return
            except Exception as e:
                logger.warning(f"No se pudo comprobar validador (se intentará registrar): {e}")

            # Registrar usando VALIDATOR_CATEGORIES
            logger.info(
                f"Validador no encontrado -> registrando en startup. "
                f"Cuenta: {ACCOUNT_ADDRESS}, Categorías: {VALIDATOR_CATEGORIES or []} (esperando minado)..."
            )
            tx_hash, receipt = await asyncio.to_thread(registrar_validador_blockchain, f"default-{ACCOUNT_ADDRESS}", VALIDATOR_CATEGORIES or [])
            if tx_hash:
                logger.info(f"Validador registrado en startup: {tx_hash}")
            else:
                logger.error("Registro de validador en startup falló.")
        except Exception as e:
            logger.exception(f"Error en startup registrar validador: {e}")
    else:
        logger.info("[EMULADO] Saltando registro real de validador en startup.")
