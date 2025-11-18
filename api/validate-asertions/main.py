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
from abc import ABC, abstractmethod

# ✅ IMPORTAR MODELOS UNIFICADOS
# Se asume que estos son los modelos que definiste en el primer mensaje
from common.veredicto import Veredicto, Validacion
from common.async_models import (
    VerifyInputModel,
    ValidationRegistrationModel,
    ValidatorRegistrationInput,
    ValidationCompletedPayload,
    ValidationFailedPayload,
    ValidationCompletedResponse,
    ValidationFailedResponse,
    RequestValidationRequest,
    ValidatorAPIResponse,
    Multihash
)

# =========================================================
# Cargar .env
# =========================================================
load_dotenv()

# =========================================================
# Config desde .env
# =========================================================
RPC_URL = os.getenv("RPC_URL")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
ACCOUNT_ADDRESS = os.getenv("ACCOUNT_ADDRESS")
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS")
CONTRACT_ABI_PATH = os.getenv("CONTRACT_ABI_PATH", "TrustManager.json")


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
AI_PROVIDER = os.getenv("AI_PROVIDER", "mistral").lower()

EMULATE_BLOCKCHAIN_REQUESTS = os.getenv("EMULATE_BLOCKCHAIN_REQUESTS", "false").lower() # True or False

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
# Pydantic Models (Eliminadas las duplicadas)
# =========================================================
# NOTA: Las clases RequestValidation, ValidationCompleted, ValidationFailed, 
# VerificarEntrada, RegistroValidacionModel y RegistroValidadorInput
# han sido ELIMINADAS y se usan las importadas de common.async_models.

# =========================================================
# AI classes
# =========================================================
class AIValidator(ABC):
    """Interfaz común para verificadores basados en IA."""
    @abstractmethod
    def verificar_asercion(self, texto: str, contexto: Optional[str] = None) -> str:
        pass


class MistralValidator(AIValidator):
    def __init__(self, api_url: str, api_key: str, model: str):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model

    def verificar_asercion(self, texto: str, contexto: Optional[str] = None) -> str:
        if not self.api_url or not self.api_key:
            raise HTTPException(status_code=500, detail="Mistral API configuration missing")

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        contenido = f"{VALIDATION_PROMPT}\n\nTexto a analizar:\n{texto}"
        if contexto:
            contenido += f"\nContexto adicional:\n{contexto}"

        data = {"model": self.model, "messages": [{"role": "user", "content": contenido}], "temperature": 0.3}
        logger.info(f"Invocando Mistral para validar aserción (preview): {texto[:80]}...")
        resp = requests.post(self.api_url, headers=headers, json=data)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        logger.error(f"Mistral API returned {resp.status_code}: {resp.text}")
        raise HTTPException(status_code=resp.status_code, detail=resp.text)


class GeminiValidator(AIValidator):
    """Ejemplo de integración con Gemini (Google AI)."""
    def __init__(self, api_url: str, api_key: str, model: str):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model

    def verificar_asercion(self, texto: str, contexto: Optional[str] = None) -> str:
        if not self.api_url or not self.api_key:
            raise HTTPException(status_code=500, detail="Gemini API configuration missing")

        prompt = f"{VALIDATION_PROMPT}\n\nTexto a analizar:\n{texto}"
        if contexto:
            prompt += f"\nContexto adicional:\n{contexto}"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "topK": 40, "topP": 0.8},
        }
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        logger.info(f"Invocando Gemini para validar aserción (preview): api_url {self.api_url}, texto: {texto[:80]}...")
        resp = requests.post(f"{self.api_url}/models/{self.model}:generateContent", headers=headers, json=payload)
        if resp.status_code == 200:
            result = resp.json()
            return result["candidates"][0]["content"]["parts"][0]["text"]
        logger.error(f"Gemini API error {resp.status_code}: {resp.text}")
        raise HTTPException(status_code=resp.status_code, detail=resp.text)


class OpenRouterValidator:
    """Integración con OpenRouter (API compatible con OpenAI)."""
    
    def __init__(self, api_url: str, api_key: str, model: str):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model

    def verificar_asercion(self, texto: str, contexto: Optional[str] = None) -> str:
        if not self.api_key:
            raise HTTPException(status_code=500, detail="OpenRouter API key missing")

        # Encabezados requeridos por OpenRouter
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # Recomendado: identifica tu app (requerido en producción)
            "HTTP-Referer": "https://trust-news",
            "X-Title": "AIValidator-OpenRouter"
        }

        contenido = f"{VALIDATION_PROMPT}\n\nTexto a analizar:\n{texto}"
        if contexto:
            contenido += f"\nContexto adicional:\n{contexto}"

        data = {
            "model": self.model,
            "messages": [{"role": "user", "content": contenido}],
            "temperature": 0.3
        }

        logger.info(f"Invocando OpenRouter ({self.model}) para validar aserción: {texto[:80]}...")

        resp = requests.post(self.api_url, headers=headers, json=data)
        if resp.status_code == 200:
            try:
                return resp.json()["choices"][0]["message"]["content"]
            except Exception as e:
                logger.error(f"Error parsing OpenRouter response: {e} | Body: {resp.text}")
                raise HTTPException(status_code=500, detail="Error parsing OpenRouter response")

        logger.error(f"OpenRouter API error {resp.status_code}: {resp.text}")
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

# =========================================================
# Helpers: 
# =========================================================

def build_ai_validator() -> AIValidator:
    if AI_PROVIDER == "mistral":
        return MistralValidator(API_URL, os.getenv("API_KEY"), os.getenv("MODEL", "mistral-tiny"))
    elif AI_PROVIDER == "gemini":
        return GeminiValidator(API_URL, os.getenv("API_KEY"), os.getenv("MODEL", "gemini-1.5-flash"))
    elif AI_PROVIDER == "openrouter":
        return OpenRouterValidator(API_URL, os.getenv("API_KEY"), os.getenv("MODEL", "gpt-4o-mini"))
    else:
        raise RuntimeError(f"AI_PROVIDER desconocido: {AI_PROVIDER}")
    
    
def clean_ai_response_text(text: str) -> str:
    """Elimina los bloques de código Markdown que envuelven el JSON."""
    text = text.strip()
    # Eliminar el inicio: ```json
    if text.startswith('```json'):
        text = text[len('```json'):].strip()
    # Eliminar el final: ```
    if text.endswith('```'):
        text = text[:-len('```')].strip()
    return text

# =========================================================
# Instanciar AI Validator
# =========================================================
ai_validator = build_ai_validator()
logger.info(f"AI Validator inicializado con proveedor: {AI_PROVIDER.upper()}")

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
# hashing, tx send/wait
# =========================================================
def verificar_asercion(texto: str, contexto: Optional[str] = None) -> str:
    return ai_validator.verificar_asercion(texto, contexto)




def send_signed_tx(function_call, gas_estimate: int = 10000000) -> str:
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
            # logs no serializables completamente; kept minimal
            "logs": [dict(l) for l in getattr(receipt, "logs", []) if hasattr(receipt, "logs")] 
        }
        logger.info(f"Receipt obtenido: tx={receipt_dict['transactionHash']}, block={receipt_dict['blockNumber']}, status={receipt_dict['status']}")
        return receipt_dict
    except Exception as e:
        logger.error(f"Error esperando receipt de {tx_hash}: {e}")
        return None

def uuid_to_uint256(u: str) -> int:
    """
    Convierte un UUID (en formato string) a un entero uint256 compatible con Solidity.
    Si el UUID no es válido, usa el hash como fallback.
    """
    try:
        return uuid.UUID(u).int
    except Exception:
        # Si no es UUID válido (ej: "3" o "abc"), convertir hash como fallback
        # Reducción modular para asegurar que cabe en un uint256 (aunque el UUID original ya cabe)
        return int(hashlib.sha256(u.encode()).hexdigest(), 16) % (2**256)



def hash_text_to_multihash(text: str) -> Multihash:
    """Calcula el SHA256 y lo envuelve en el modelo Multihash."""
    logger.info(f"Calculando multihash para texto (preview): {text[:80]}...")
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    # 0x12 es SHA256, 0x20 es 32 bytes (256 bits)
    return Multihash(hash_function="0x12", hash_size="0x20", digest="0x" + h)

# =========================================================
# Funciones internas reutilizables
# =========================================================

def registrar_validacion_internal(postId: Any, assertion_id: Any, veredicto: Veredicto) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    1) Verifica la aserción (IA)
    2) Envía la transacción addValidation
    3) Espera al minado y devuelve (tx_hash, receipt_dict)
    Nota: función BLOQUEANTE; ejecutar con asyncio.to_thread desde handlers async.
    """
    try:

        multihash = hash_text_to_multihash(veredicto.texto)

        logger.info(f"Veredicto (bool): {veredicto.estado} — preparando tx addValidation (post {postId}, assertion {assertion_id})")

        # Conversión segura: aseguramos que los IDs sean enteros antes de pasarlos a Web3
        postId_int = int(postId) if str(postId).isdigit() else uuid_to_uint256(str(postId))
        assertion_id_int = int(assertion_id)

        if EMULATE_BLOCKCHAIN_REQUESTS == "true":
            tx_hash = f"0x{uuid.uuid4().hex[:64]}"
            receipt = {"transactionHash": tx_hash, "blockNumber": 0, "status": 1}
            logger.info(f"[EMULADO] Validación simulada: {tx_hash}")
            return tx_hash, receipt

        func_call = contract.functions.addValidation(
            postId_int,             # ✅ Ahora postId se pasa como int (Web3/Solidity)
            assertion_id_int - 1,   # ✅ assertion_id como índice 0-based
            int(veredicto.estado),
            {
                "hash_function": multihash.hash_function,
                "hash_size": multihash.hash_size,
                "digest": multihash.digest
            }
        )
        tx_hash = send_signed_tx(func_call)
        receipt = wait_for_receipt_blocking(tx_hash)
        return tx_hash, receipt
    except HTTPException:
        # propaga errores de IA al caller (para logging/response)
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
# ✅ Usando VerifyInputModel
def endpoint_verificar(body: VerifyInputModel):
    resultado = verificar_asercion(body.text, body.context)
    return {"verificación": resultado}



@app.get("/tx/status/{tx_hash}")
async def endpoint_tx_status(tx_hash: str):
    """Consulta el estado de la tx (no bloqueante)."""
    result = consultar_tx_status_internal(tx_hash)
    return result

@app.post("/registrar_validador")
# ✅ Usando ValidatorRegistrationInput
async def endpoint_registrar_validador(input: ValidatorRegistrationInput):
    """Registra validador (usa VALIDATOR_CATEGORIES si no se pasan). Espera minado."""
    categorias = input.categories if input.categories is not None else VALIDATOR_CATEGORIES
    try:
        tx_hash, receipt = await asyncio.to_thread(registrar_validador_blockchain, input.name, categorias or [])
        if tx_hash is None:
            raise HTTPException(status_code=500, detail="Error registrando validador.")
        return {"status": "ok", "tx_hash": tx_hash, "receipt": receipt}
    except Exception as e:
        logger.exception(f"endpoint_registrar_validador error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =========================================================
# Kafka consumer (asincrónico) — procesa mensajes y valida directamente
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
    logger.info(f"Kafka consumer y producer iniciados (background) - {ACCOUNT_ADDRESS}")

    try:
        async for msg in consumer:
            try:

                # Usamos RequestValidationRequest para validar la estructura del contenido del payload
                try:
                    payload_msg = json.loads(msg.value.decode("utf-8"))
                    message = RequestValidationRequest(**payload_msg)
                    action = message.action
                    order_id = message.order_id
                    val_payload = message.payload
                    idValidator = val_payload.idValidator
                except Exception as e:
                    logger.error(f"Error de Pydantic en payload Kafka: {e}")
                    # No podemos enviar un failed response completo si el order_id/action es inválido
                    continue

                # Filtrar mensajes no dirigidos a este validador
                if action != "request_validation" or idValidator != ACCOUNT_ADDRESS:
                    logger.debug(f"Ignorado mensaje Kafka (action={action}, idValidator={idValidator})")
                    continue

                postId = val_payload.postId
                assertion_id = val_payload.idAssertion
                assertion_text = val_payload.text
                context = val_payload.context

                logger.info(f"Kafka: procesando request_validation para postId={postId}, assertion_id={assertion_id}")

                # =====================================================
                # 1️⃣ Verificar directamente 
                # =====================================================
                result_text = None
                try:
                    # Ejecutar la verificación de IA en un thread
                    result_text = await asyncio.to_thread(verificar_asercion, assertion_text, context)
                    logger.info(f"Verificación completada (preview): {result_text}")
                    result_text_parsed = ValidatorAPIResponse(**json.loads(clean_ai_response_text(result_text)))
                    logger.info(f"Resultado verificación: {result_text_parsed}")
                except Exception as e:
                    logger.exception(f"Error ejecutando verificar_asercion(): {e}")
                    # ✅ Usando ValidationFailedResponse/Payload
                    failed_response = ValidationFailedResponse(
                        action="validation_failed",
                        order_id=order_id,
                        payload=ValidationFailedPayload(
                            order_id=order_id,
                            postId=postId,
                            idAssertion=assertion_id,
                            idValidator=ACCOUNT_ADDRESS,
                            error_message=f"verificar_error: {str(e)}",
                            error_type="AI_Validation_Error"
                        )
                    )
                    await producer.send_and_wait(RESPONSE_TOPIC, failed_response.model_dump_json().encode())
                    continue

                # =====================================================
                # 2️⃣ Registrar en blockchain
                # =====================================================
                tx_hash = None
                receipt = None
                if result_text_parsed.resultado == "TRUE":
                    estado_enum = Validacion.TRUE
                elif result_text_parsed.resultado == "FALSE":
                    estado_enum = Validacion.FALSE
                else:
                    estado_enum = Validacion.UNKNOWN
                    
                veredict = Veredicto(result_text_parsed.descripcion,estado_enum) # Intentamos la conversión del veredicto

                try:
                    # Los IDs vienen como str desde Kafka, la función interna los convierte a int/uint256 para Web3
                    tx_hash, receipt = await asyncio.to_thread(registrar_validacion_internal, postId, assertion_id,veredict) 

                    if not tx_hash or receipt is None or receipt.get("status") != 1:
                         raise RuntimeError(f"Transacción de validación fallida o no minada. Receipt: {receipt}")
                         
                except Exception as e:
                    logger.exception(f"Error registrando validación en blockchain: {e}")
                    # ✅ Usando ValidationFailedResponse/Payload
                    failed_response = ValidationFailedResponse(
                        action="validation_failed",
                        order_id=order_id,
                        payload=ValidationFailedPayload(
                            order_id=order_id,
                            postId=postId,
                            idAssertion=assertion_id,
                            idValidator=ACCOUNT_ADDRESS,
                            error_message=f"blockchain_error: {str(e)}",
                            error_type="Blockchain_Transaction_Error"
                        )
                    )
                    await producer.send_and_wait(RESPONSE_TOPIC, failed_response.model_dump_json().encode())
                    continue

                # =====================================================
                # 3️⃣ Publicar resultado final
                # =====================================================
                # ✅ Usando ValidationCompletedResponse/Payload
                completed_response = ValidationCompletedResponse(
                    action="validation_completed",
                    order_id=order_id,
                    payload=ValidationCompletedPayload(
                        postId=postId,
                        idAssertion=assertion_id,
                        idValidator=ACCOUNT_ADDRESS,
                        approval=veredict.estado, # El enum Validacion
                        text=result_text_parsed.descripcion,
                        tx_hash=tx_hash,
                        validator_alias=AI_PROVIDER.upper(),
                        # Receipt no está en el Payload original, lo omitimos para consistencia con common.async_models
                    )
                )

                await producer.send_and_wait(RESPONSE_TOPIC, completed_response.model_dump_json().encode())
                logger.info(f"✅ Publicado validation_completed (postId={postId}, assertion_id={assertion_id})")

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
    if ENABLE_KAFKA_CONSUMER :
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
            # Usar 'default-' como nombre si es el registro automático
            tx_hash, receipt = await asyncio.to_thread(registrar_validador_blockchain, f"default-{ACCOUNT_ADDRESS}", VALIDATOR_CATEGORIES or [])
            if tx_hash:
                logger.info(f"Validador registrado en startup: {tx_hash}")
            else:
                logger.error("Registro de validador en startup falló.")
        except Exception as e:
            logger.exception(f"Error en startup registrar validador: {e}")
    else:
        logger.info("[EMULADO] Saltando registro real de validador en startup.")