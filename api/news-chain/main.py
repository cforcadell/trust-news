# main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from web3 import Web3
import json, os, logging, asyncio, uuid
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from typing import List

# ========================================
# CONFIGURACIÓN
# ========================================
from dotenv import load_dotenv
load_dotenv()

RPC_URL = os.getenv("RPC_URL")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
ACCOUNT_ADDRESS = os.getenv("ACCOUNT_ADDRESS")
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS")

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
REQUEST_TOPIC = os.getenv("KAFKA_REQUEST_TOPIC", "register_blockchain")
RESPONSE_TOPIC = os.getenv("KAFKA_RESPONSE_TOPIC", "register_blockchain_responses")
MAX_RETRIES = 10
RETRY_DELAY = 3

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("TrustManagerAPI")

# ========================================
# WEB3 Y CONTRATO
# ========================================
w3 = Web3(Web3.HTTPProvider(RPC_URL))
with open("contract_abi.json") as f:
    abi = json.load(f)
contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=abi)

# ========================================
# MODELOS DE DATOS
# ========================================
class MultihashModel(BaseModel):
    hash_function: str
    hash_size: str
    digest: str

class ValidatorModel(BaseModel):
    validatorAddress: str
    domain: str
    reputation: int

class ValidationModel(BaseModel):
    id: str
    validator: ValidatorModel
    veredict: bool
    hash_description: MultihashModel

class AsertionModel(BaseModel):
    hash_asertion: MultihashModel
    validations: List[ValidationModel] = []

class PublishModel(BaseModel):
    hash_new: MultihashModel
    hash_ipfs: MultihashModel
    asertions: List[AsertionModel] = []
    publisher: str

# ========================================
# FUNCIONES AUXILIARES
# ========================================
def send_tx(function_call):
    try:
        nonce = w3.eth.get_transaction_count(ACCOUNT_ADDRESS)
        tx = function_call.build_transaction({
            "from": ACCOUNT_ADDRESS,
            "nonce": nonce,
            "gas": 800000,
            "gasPrice": w3.toWei("1", "gwei")
        })
        signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        logger.info(f"Transaction sent: {tx_hash.hex()}")
        return receipt
    except Exception as e:
        logger.error(f"Error sending transaction: {e}")
        raise

def convert_multihash_to_tuple(mh: MultihashModel):
    return (int(mh.hash_function, 16), int(mh.hash_size, 16), bytes.fromhex(mh.digest[2:]))

# ========================================
# FASTAPI
# ========================================
app = FastAPI(title="TrustManager SC API")

@app.post("/publishNew")
def publish_new(data: PublishModel):
    logger.info(f"publishNew called by {data.publisher}")

    hash_new = convert_multihash_to_tuple(data.hash_new)
    hash_ipfs = convert_multihash_to_tuple(data.hash_ipfs)

    # Preparar aserciones y validaciones
    asertions_list = []
    for a in data.asertions:
        validations_list = []
        for v in a.validations:
            v_tuple = (
                int(v.id, 16),
                (v.validator.validatorAddress, v.validator.domain, v.validator.reputation),
                v.veredict,
                convert_multihash_to_tuple(v.hash_description)
            )
            validations_list.append(v_tuple)
        asertions_list.append((convert_multihash_to_tuple(a.hash_asertion), validations_list))

    # Llamar a publishNew en blockchain
    func_call = contract.functions.publishNew(hash_new, hash_ipfs, asertions_list)
    receipt = send_tx(func_call)

    # Obtener PostId
    postId = contract.functions.postCounter().call()

    # Recuperar validaciones
    all_validations = contract.functions.getValidationsByNew(postId).call()

    # Mapear aserciones a validadores
    asertion_validator_map = []
    temp_map = {}
    for v in all_validations:
        asertion_id = v[0]  # id de la aserción
        validator_addr = v[1][0]  # address del validador
        if asertion_id not in temp_map:
            temp_map[asertion_id] = []
        temp_map[asertion_id].append(validator_addr)

    for aid, addrs in temp_map.items():
        asertion_validator_map.append({
            "asertionId": aid.hex() if isinstance(aid, bytes) else aid,
            "validatorAddresses": addrs
        })

    return {
        "status": "success",
        "postId": postId,
        "asertions": asertion_validator_map,
        "tx_hash": receipt.transactionHash.hex()
    }

@app.get("/getNewByHash/{digest}")
def get_new_by_hash(digest: str):
    digest_bytes = bytes.fromhex(digest[2:])
    postId = contract.functions.postsHash(digest_bytes).call()
    post = contract.functions.postsById(postId).call()
    return {"postId": postId, "post": post}

@app.get("/getNewByCid/{digest}")
def get_new_by_cid(digest: str):
    digest_bytes = bytes.fromhex(digest[2:])
    postId = contract.functions.postsCid(digest_bytes).call()
    post = contract.functions.postsById(postId).call()
    return {"postId": postId, "post": post}


@app.get("/getAsertionsWithValidations/{PostId}")
def get_asertions_with_validations(PostId: int):
    try:
        # Obtener todas las aserciones del Post
        raw_asertions = contract.functions.getAsertionsByNew(PostId).call()  # suponiendo que existe en el SC
        result = []

        # Para cada aserción, obtener sus validaciones
        for a in raw_asertions:
            asertion_hash = a[0]  # hash de la aserción
            validations_raw = contract.functions.getValidationsByAsertion(a[1]).call()  # id de la aserción
            validations_list = []

            for v in validations_raw:
                validation = {
                    "id": v[0],
                    "validator": {
                        "validatorAddress": v[1][0],
                        "domain": v[1][1],
                        "reputation": v[1][2]
                    },
                    "veredict": v[2],
                    "hash_description": {
                        "hash_function": hex(v[3][0]),
                        "hash_size": hex(v[3][1]),
                        "digest": "0x" + v[3][2].hex()
                    }
                }
                validations_list.append(validation)

            result.append({
                "hash_asertion": "0x" + asertion_hash.hex() if isinstance(asertion_hash, bytes) else asertion_hash,
                "validations": validations_list
            })

        return {"PostId": PostId, "asertions": result}

    except Exception as e:
        logger.error(f"Error en getAsertionsWithValidations para PostId={PostId}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========================================
# CONSUMER KAFKA
# ========================================
async def consume_register_blockchain():
    consumer = AIOKafkaConsumer(
        REQUEST_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id="trustmanager-api-group",
        auto_offset_reset="earliest"
    )
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await consumer.start()
            await producer.start()
            logger.info("✅ Kafka conectado para register_blockchain")
            break
        except Exception as e:
            logger.warning(f"⚠️ Kafka no disponible (intento {attempt}/{MAX_RETRIES}): {e}")
            await asyncio.sleep(RETRY_DELAY)

    try:
        async for msg in consumer:
            try:
                payload_msg = json.loads(msg.value.decode())
                order_id = payload_msg.get("order_id", str(uuid.uuid4()))
                payload = payload_msg.get("payload", {})
                publisher = payload.get("publisher", ACCOUNT_ADDRESS)
                hash_new = MultihashModel(**payload["hash_new"])
                hash_ipfs = MultihashModel(**payload["hash_ipfs"])
                asertions = [AsertionModel(**a) for a in payload.get("asertions", [])]

                publish_data = PublishModel(
                    hash_new=hash_new,
                    hash_ipfs=hash_ipfs,
                    asertions=asertions,
                    publisher=publisher
                )

                # Llamada síncrona adaptada a async
                result = await asyncio.to_thread(publish_new, publish_data)
                logger.info(f"Post publicado desde Kafka: {result}")

                response = {
                    "action": "blockchain_registered",
                    "order_id": order_id,
                    "payload": result
                }
                await producer.send_and_wait(RESPONSE_TOPIC, json.dumps(response).encode())
                logger.info(f"Respuesta enviada a {RESPONSE_TOPIC} para order_id {order_id}")

            except Exception as e:
                logger.error(f"Error procesando mensaje Kafka: {e}")

    finally:
        await consumer.stop()
        await producer.stop()
        logger.info("Kafka consumer y producer detenidos para register_blockchain")

# ========================================
# STARTUP
# ========================================
@app.on_event("startup")
async def startup_event():
    if os.getenv("ENABLE_KAFKA_CONSUMER", "false").lower() == "true":
        asyncio.create_task(consume_register_blockchain())
        logger.info("Kafka consumer iniciado")
