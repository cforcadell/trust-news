import os
import json
import uuid
import logging
import asyncio
import base58
from typing import List, Tuple, Optional, Dict, Any
from hexbytes import HexBytes


import httpx
from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv
from web3 import Web3
from abc import ABC, abstractmethod

from common.blockchain import send_signed_tx, wait_for_receipt_blocking
from common.hash_utils import hash_text_to_multihash, multihash_to_base58,multihash_to_base58_dict, uuid_to_uint256,safe_multihash_to_tuple
from common.veredicto import Veredicto, Validacion
from common.async_models import VerifyInputModel, ValidatorAPIResponse,ValidatorRegistrationInput,Multihash


# =========================================================
# Cargar .env y configurar logger
# =========================================================
load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(),
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("validate-asertions")

# =========================================================
# Config blockchain y AI
# =========================================================
RPC_URL = os.getenv("RPC_URL")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
ACCOUNT_ADDRESS = os.getenv("ACCOUNT_ADDRESS")
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS")
CONTRACT_ABI_PATH = os.getenv("CONTRACT_ABI_PATH", "TrustNews.json")

API_URL = os.getenv("API_URL")
AI_PROVIDER = os.getenv("AI_PROVIDER", "mistral").lower()
VALIDATION_PROMPT = os.getenv(
    "VALIDATION_PROMPT",
    "Validame la siguiente aserción. Devuelve dos tags: 'resultado' (TRUE, FALSE o UNKNOWN) y 'descripcion'."
)

# =========================================================
# Parsear categorías
# =========================================================
try:
    VALIDATOR_CATEGORIES = json.loads(os.getenv("VALIDATOR_CATEGORIES", "[]"))
    VALIDATOR_CATEGORIES = [int(x) for x in VALIDATOR_CATEGORIES]
except Exception:
    VALIDATOR_CATEGORIES = []

# =========================================================
# AI Validators
# =========================================================
class AIValidator(ABC):
    @abstractmethod
    def verificar_asercion(self, texto: str, contexto: Optional[str] = None) -> str:
        pass

class MistralValidator(AIValidator):
    def __init__(self, api_url: str, api_key: str, model: str):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model

    def verificar_asercion(self, texto: str, contexto: Optional[str] = None) -> str:
        import requests
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        contenido = f"{VALIDATION_PROMPT}\n\nTexto a analizar:\n{texto}"
        data = {"model": self.model, "messages": [{"role": "user", "content": contenido}], "temperature": 0.3}
        resp = requests.post(self.api_url, headers=headers, json=data)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

class GeminiValidator(AIValidator):
    def __init__(self, api_url: str, api_key: str, model: str):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model

    def verificar_asercion(self, texto: str, contexto: Optional[str] = None) -> str:
        prompt = f"{VALIDATION_PROMPT}\n\nTexto a analizar:\n{texto}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "topK": 40, "topP": 0.8},
        }
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        resp = httpx.post(f"{self.api_url}/models/{self.model}:generateContent", headers=headers, json=payload)
        if resp.status_code == 200:
            result = resp.json()
            return result["candidates"][0]["content"]["parts"][0]["text"]
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

class OpenRouterValidator(AIValidator):
    def __init__(self, api_url: str, api_key: str, model: str):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model

    def verificar_asercion(self, texto: str, contexto: Optional[str] = None) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        contenido = f"{VALIDATION_PROMPT}\n\nTexto a analizar:\n{texto}"
        data = {"model": self.model, "messages": [{"role": "user", "content": contenido}], "temperature": 0.3}
        resp = httpx.post(self.api_url, headers=headers, json=data)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

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
    text = text.strip()
    if text.startswith("```json"): text = text[7:].strip()
    if text.endswith("```"): text = text[:-3].strip()
    return text

ai_validator = build_ai_validator()
logger.info(f"AI Validator inicializado: {AI_PROVIDER.upper()}")

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
def verificar_asercion(texto: str, contexto: Optional[str] = None) -> str:
    return ai_validator.verificar_asercion(texto, contexto)

async def upload_validation_to_ipfs(validation_doc_bytes: bytes) -> str:
    ipfs_api_url = os.getenv("IPFS_API_URL", "http://127.0.0.1:8000")
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{ipfs_api_url}/ipfs/upload",
            data={
                "filename": f"validation-{uuid.uuid4()}.json",
                "content_bytes": validation_doc_bytes
            }
        )

    response.raise_for_status()
    return response.json()["cid"]

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

       # ------------------------------------------------
        # Decodificar CIDv0 → Multihash
        # ------------------------------------------------
        decoded = base58.b58decode(validation_cid)

        logger.info(f"CID decoded length: {len(decoded)} bytes")

        if len(decoded) != 34:
            raise ValueError(
                f"CID inválido. Longitud inesperada: {len(decoded)} (esperado 34)"
            )

        hash_function = decoded[0:1]  # bytes1
        hash_size = decoded[1:2]      # bytes1
        digest = decoded[2:]          # bytes32

        logger.info(f"hash_function: {hash_function.hex()}")
        logger.info(f"hash_size: {hash_size.hex()}")
        logger.info(f"digest length: {len(digest)}")

        # ------------------------------------------------
        # Validaciones estrictas (protección arquitectura)
        # ------------------------------------------------
        if hash_function != b"\x12":
            raise ValueError("Solo se soporta SHA-256 (0x12)")

        if hash_size != b"\x20":
            raise ValueError("Solo se soporta digest de 32 bytes (0x20)")

        if len(digest) != 32:
            raise ValueError("Digest no es 32 bytes")

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
def registrar_validador_blockchain(name: str, categories: List[int]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Registra validador y espera minado.
    Devuelve (tx_hash, receipt_dict) o (None, None) en error.
    Bloqueante: usar asyncio.to_thread en el event loop.
    """
    try:
        logger.info(f"Inicio registrar_validador_blockchain -> name: {name}, categories: {categories}")



        # Preparar llamada al contrato
        fn = contract.functions.registerValidator(name, categories)

        # Enviar transacción
        tx_hash = send_signed_tx(w3,fn, ACCOUNT_ADDRESS, PRIVATE_KEY)
        logger.info(f"Transacción enviada: {tx_hash}")

        # Esperar a que se mine
        receipt = wait_for_receipt_blocking(w3,tx_hash)
        logger.info(f"Receipt recibido: {receipt}")

        return tx_hash, receipt

    except Exception as e:
        logger.exception(f"Error al registrar validador en blockchain: {e}")
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
        tx_hash = send_signed_tx(w3,fn, ACCOUNT_ADDRESS, PRIVATE_KEY)
        logger.info(f"Transacción enviada: {tx_hash}")

        # Esperar a que se mine
        receipt = wait_for_receipt_blocking(w3,tx_hash)
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
        tx_hash, receipt = await asyncio.to_thread(registrar_validador_blockchain, input.name, categorias or [])
        if tx_hash is None:
            raise HTTPException(status_code=500, detail="Error registrando validador.")
        return {"status": "ok", "tx_hash": tx_hash, "receipt": receipt}
    except Exception as e:
        logger.exception(f"endpoint_registrar_validador error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/desregistrar_validador")
# ✅ Usando ValidatorRegistrationInput
async def endpoint_desregistrar_validador():
    """Desregistra validador. Espera minado."""
    try:
        tx_hash, receipt = await asyncio.to_thread(desregistrar_validador_blockchain)
        if tx_hash is None:
            raise HTTPException(status_code=500, detail="Error desregistrando validador.")
        return {"status": "ok", "tx_hash": tx_hash, "receipt": receipt}
    except Exception as e:
        logger.exception(f"endpoint_desregistrar_validador error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
            parsed_result = ValidatorAPIResponse(**json.loads(clean_ai_response_text(result_text)))
            if parsed_result.resultado == "TRUE":
                estado_enum = Validacion.TRUE
            elif parsed_result.resultado == "FALSE":
                estado_enum = Validacion.FALSE
            else:
                estado_enum = Validacion.UNKNOWN

            veredicto = Veredicto(parsed_result.descripcion, estado_enum)
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
    agent = BlockchainEventAgent(w3, contract, ACCOUNT_ADDRESS, ipfs_api_url)
    asyncio.create_task(agent.start())
    logger.info("🟢 Blockchain Event Agent iniciado")
    
        # registrar validador en startup (si no está registrado)

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

