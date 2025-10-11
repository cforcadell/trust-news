from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import requests
import os
import asyncio
import json
import uuid
import hashlib
import logging
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv


# =======================================================
# Cargar variables de entorno
# =======================================================
load_dotenv()

# =======================================================
# Logging
# =======================================================
log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level_str, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# =======================================================
# Configuración Web3 / Smart Contract
# =======================================================
WEB3_PROVIDER_URL = os.getenv("WEB3_PROVIDER_URL")
CONTRACT_ADDRESS = os.getenv("SMART_CONTRACT_ADDRESS")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
CHAIN_ID = int(os.getenv("CHAIN_ID", "11155111"))  # Sepolia por defecto

w3 = Web3(Web3.HTTPProvider(WEB3_PROVIDER_URL))
account = Account.from_key(PRIVATE_KEY)
logger.info(f"Conectado a blockchain: {w3.is_connected()} - Address: {account.address}")

TRUSTMANAGER_ABI = [
    {
        "inputs": [
            {"internalType": "uint256", "name": "PostId", "type": "uint256"},
            {"internalType": "uint256", "name": "asertionIndex", "type": "uint256"},
            {"internalType": "bool", "name": "veredict", "type": "bool"},
            {
                "components": [
                    {"internalType": "bytes1", "name": "hash_function", "type": "bytes1"},
                    {"internalType": "bytes1", "name": "hash_size", "type": "bytes1"},
                    {"internalType": "bytes32", "name": "digest", "type": "bytes32"},
                ],
                "internalType": "struct TrustManager.Multihash",
                "name": "hash_description",
                "type": "tuple",
            },
        ],
        "name": "addValidation",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "string", "name": "name", "type": "string"},
            {"internalType": "string[]", "name": "categories", "type": "string[]"},
        ],
        "name": "registerValidator",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "", "type": "address"}
        ],
        "name": "validators",
        "outputs": [
            {"internalType": "address", "name": "validatorAddress", "type": "address"},
            {"internalType": "string", "name": "domain", "type": "string"},
            {"internalType": "uint256", "name": "reputation", "type": "uint256"}
        ],
        "stateMutability": "view",
        "type": "function"
    }
]

contract = w3.eth.contract(address=Web3.to_checksum_address(CONTRACT_ADDRESS), abi=TRUSTMANAGER_ABI)

# =======================================================
# FastAPI
# =======================================================
app = FastAPI(title="API de Validación de Aserciones")

# =======================================================
# Modelos
# =======================================================
class VerificarEntrada(BaseModel):
    texto: str
    contexto: Optional[str] = None

class RegistroValidadorEntrada(BaseModel):
    nombre: str
    categorias: List[str]


# =======================================================
# Funciones auxiliares
# =======================================================
def verificar_asercion(texto: str, contexto: Optional[str] = None):
    url = os.getenv("API_URL")
    API_KEY = os.getenv("MISTRAL_API_KEY")
    MODEL = os.getenv("MISTRAL_MODEL", "mistral-tiny")

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    contenido = f"Texto a analizar:\n{texto}"
    if contexto:
        contenido += f"\nContexto adicional:\n{contexto}"

    data = {
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": (
                "Validame la siguiente aserción. Devuelve dos tags: "
                "'resultado' (TRUE, FALSE o UNKNOWN) y 'descripcion'.\n\n"
                f"{contenido}"
            )
        }],
        "temperature": 0.3,
    }

    logger.info(f"Verificando aserción: {texto[:60]}...")
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    raise HTTPException(status_code=response.status_code, detail=response.text)


def build_and_send_tx(fn):
    """Crea, firma y envía una transacción al blockchain."""
    tx = fn.build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address, "pending"),
        "chainId": CHAIN_ID,
        "gas": 400000,
        "gasPrice": w3.eth.gas_price
    })
    signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    return tx_hash.hex(), receipt


async def registrar_validacion_blockchain(post_id: int, asertion_index: int, veredict: bool, hash_desc_digest: str):
    try:
        fn = contract.functions.addValidation(
            post_id,
            asertion_index,
            veredict,
            {
                "hash_function": b'\x12',
                "hash_size": b'\x20',
                "digest": Web3.to_bytes(hexstr=hash_desc_digest)
            }
        )
        tx_hash, _ = build_and_send_tx(fn)
        logger.info(f"✅ Validación registrada on-chain: {tx_hash}")
        return tx_hash
    except Exception as e:
        logger.error(f"❌ Error registrando validación: {e}")
        return None


async def registrar_validador_blockchain(name: str, categories: List[str]):
    try:
        fn = contract.functions.registerValidator(name, categories)
        tx_hash, _ = build_and_send_tx(fn)
        logger.info(f"✅ Validador '{name}' registrado: {tx_hash}")
        return tx_hash
    except Exception as e:
        logger.error(f"❌ Error al registrar validador: {e}")
        return None


# =======================================================
# Endpoints
# =======================================================
@app.post("/verificar")
def verificar(entrada: VerificarEntrada):
    resultado = verificar_asercion(entrada.texto, entrada.contexto)
    return {"verificación": resultado}


@app.post("/registrar_validador")
async def registrar_validador(entrada: RegistroValidadorEntrada):
    tx_hash = await registrar_validador_blockchain(entrada.nombre, entrada.categorias)
    if tx_hash:
        return {"status": "ok", "tx_hash": tx_hash}
    raise HTTPException(status_code=500, detail="Error al registrar el validador en blockchain")


# =======================================================
# Kafka Consumer
# =======================================================
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
REQUEST_TOPIC = os.getenv("KAFKA_REQUEST_TOPIC", "fake_news_requests")
RESPONSE_TOPIC = os.getenv("KAFKA_RESPONSE_TOPIC", "fake_news_responses")
MAX_RETRIES = 10
RETRY_DELAY = 3

async def consume_and_process():
    consumer = AIOKafkaConsumer(
        REQUEST_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id="news-handler-group",
        auto_offset_reset="earliest"
    )
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await consumer.start()
            await producer.start()
            logger.info("✅ Kafka conectado.")
            break
        except Exception as e:
            logger.warning(f"⚠️ Kafka no disponible (intento {attempt}/{MAX_RETRIES}): {e}")
            await asyncio.sleep(RETRY_DELAY)

    try:
        async for msg in consumer:
            payload = json.loads(msg.value.decode())
            action = payload.get("action")
            idValidator = payload.get("idValidator")
            if action != "request_validation" or idValidator != os.getenv("SMART_CONTRACT_ADDRESS"):
                continue

            order_id = int(payload.get("order_id", "0"))
            assertion = payload["payload"].get("assertion_content", "")
            assertion_id = int(payload["payload"].get("assertion_id", "0"))
            context = payload["payload"].get("context", "")

            logger.info(f"🧩 Validando assertion_id={assertion_id}...")

            veredict_text = verificar_asercion(assertion, context)
            veredict_bool = "TRUE" in veredict_text.upper()
            hash_desc = hashlib.sha256(veredict_text.encode()).hexdigest()

            tx_hash = await registrar_validacion_blockchain(order_id, assertion_id, veredict_bool, hash_desc)

            response_msg = {
                "action": "validation_completed",
                "order_id": order_id,
                "payload": {
                    "assertion_id": assertion_id,
                    "status": "TRUE" if veredict_bool else "FALSE",
                    "description": veredict_text,
                    "tx_hash": tx_hash
                }
            }
            await producer.send_and_wait(RESPONSE_TOPIC, json.dumps(response_msg).encode())
            logger.info(f"✅ Resultado publicado en {RESPONSE_TOPIC}")

    except Exception as e:
        logger.error(f"Error en Kafka consumer: {e}")
    finally:
        await consumer.stop()
        await producer.stop()


# =======================================================
# Startup
# =======================================================
@app.on_event("startup")
async def startup_event():
    if os.getenv("ENABLE_KAFKA_CONSUMER", "false").lower() == "true":
        asyncio.create_task(consume_and_process())

    if os.getenv("ENABLE_REGISTER_VALIDATOR_STARTUP", "false").lower() == "true":
        try:
            validator_info = contract.functions.validators(account.address).call()
            if validator_info[0] == "0x0000000000000000000000000000000000000000":
                logger.info("🔹 Validador no registrado. Registrando automáticamente...")
                await registrar_validador_blockchain("default.domain", ["general"])
            else:
                logger.info("🟢 Validador ya registrado.")
        except Exception as e:
            logger.error(f"❌ Error al registrar validador en startup: {e}")
