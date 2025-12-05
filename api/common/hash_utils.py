
import hashlib
import uuid
import base58
import logging
from common.async_models import Multihash



logger = logging.getLogger("hash_utils")

def safe_multihash_to_tuple(mh: Multihash) -> tuple:
    """
    Convierte Multihash (Pydantic) a la tupla (bytes1, bytes1, bytes32)
    requerida por Solidity. Soporta digest en 0x... o Base58 (CID IPFS).
    """
    try:
        digest = mh.digest
        # Si digest es base58 (CID tipo Qm...), lo decodificamos completo
        if isinstance(digest, str) and digest.startswith("Qm"):
            decoded = base58.b58decode(digest)
            hf = decoded[0:1]
            hs = decoded[1:2]
            dg = decoded[2:34]  # digest real
        else:
            # Si digest ya es hex (0x...), usar hash_function y hash_size explícitos
            hf = bytes.fromhex(mh.hash_function.removeprefix("0x"))
            hs = bytes.fromhex(mh.hash_size.removeprefix("0x"))
            dg = bytes.fromhex(digest.removeprefix("0x"))

        # Validación de longitud
        if len(dg) != 32:
            raise ValueError(f"Digest debe tener 32 bytes, tiene {len(dg)}")

        return (hf, hs, dg)

    except Exception as e:
        logger.warning(f"Error en safe_multihash_to_tuple({mh}): {e}")
        return (b'\x00', b'\x00', b'\x00' * 32)

def multihash_to_base58(multihash_tuple: tuple) -> str:
    """
    Convierte un Multihash (bytes1, bytes1, bytes32) en un CID base58 (IPFS-style).

    """
    try:
        hf, hs, dg = multihash_tuple
        # Concatenar bytes: [hash_function][hash_size][digest]
        multihash_bytes = hf + hs + dg
        return base58.b58encode(multihash_bytes).decode("utf-8")
    except Exception as e:
        logger.warning(f"Error en multihash_to_base58: {e}")
        return None




def hash_text_to_hash(text: str) -> str:
    """Genera un hash SHA-256 tipo multihash para enviar al smart contract."""
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return h

    


    
def hash_text_to_multihash(text: str) -> Multihash:
    """Calcula el SHA256 y lo envuelve en el modelo Multihash."""
    logger.info(f"Calculando multihash para texto (preview): {text[:80]}...")
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    # 0x12 es SHA256, 0x20 es 32 bytes (256 bits)
    return Multihash(hash_function="0x12", hash_size="0x20", digest="0x" + h)
    
def safe_hex(value):
    if value is None:
        return None
    if isinstance(value, bytes):
        h = value.hex()
        if not h.startswith("0x"):
            h = "0x" + h
        return h
    if isinstance(value, str) and value.startswith("0x0x"):
        return "0x" + value[4:]
    return value


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



