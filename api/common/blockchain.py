from typing import Optional, Dict, Any
from web3 import Web3
import logging
logger = logging.getLogger("blockchain")

def send_signed_tx(w3,function_call, account_address,private_key, gas_estimate=3_000_000) -> str:
    """Construye, firma y envía tx; devuelve tx_hash (hex) — no espera minado."""


    sender = Web3.to_checksum_address(account_address)
    
    balance = w3.eth.get_balance(sender)
    logger.info(f"Balance de la cuenta {sender}: {w3.from_wei(balance, 'ether')} ETH")

    nonce = w3.eth.get_transaction_count(account_address, "pending")
    
    tx = function_call.build_transaction({
        "from": account_address,
        "nonce": nonce,
        "gas": gas_estimate,
        "gasPrice": w3.eth.gas_price
    })
    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    tx_hash_hex = tx_hash.hex()
    logger.info(f"Transacción enviada: {tx_hash_hex}")
    return tx_hash_hex

def wait_for_receipt_blocking(w3,tx_hash: str, timeout: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Bloqueante: espera al minado y devuelve diccionario receipt (o None si falla)."""


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