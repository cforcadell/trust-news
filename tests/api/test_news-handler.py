import os
import time
import pytest
import requests
import urllib3
import logging

# Desactivar avisos de certificados (entornos de desarrollo)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==============================================================================
# Configuración y Logs
# ==============================================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] NEWS-HANDLER: %(message)s")
logger = logging.getLogger(__name__)

# URLs de los servicios
NEWS_HANDLER_URL = os.getenv("NEWS_HANDLER_URL", "http://localhost:8072")
ADMIN_URL = os.getenv("ADMIN_URL", "http://127.0.0.1:8400") # URL del Admin de Cuotas

# Credenciales

# ==============================================================================
# Tests
# ==============================================================================

def test_0_setup_resource_quota(api_session, computed_client_id):
    """
    PASO 1: Asegura que el cliente existe y tiene cuota suficiente (ADMIN_URL).
    """
    logger.info(f"--- INICIO: test_0_setup_resource_quota para {computed_client_id} ---")
    url_create = f"{ADMIN_URL}/clients"
    
    # Definimos límites generosos para el test
    payload_setup = {
        "client_id": computed_client_id,
        "name": "News Handler Integration Test",
        "limits": {"news_generation": 10, "blockchain_validation": 10},
        "consumed": {"news_generation": 0, "blockchain_validation": 0},
        "status": "Active"
    }
    
    res = api_session.post(url_create, json=payload_setup)
    
    # Si el cliente ya existe (400), reseteamos su consumo a 0
    if res.status_code == 400:
        logger.info("El cliente ya existe, reseteando cuotas...")
        url_patch = f"{ADMIN_URL}/clients/{computed_client_id}"
        payload_reset = {
            "consumed": {"news_generation": 0, "blockchain_validation": 0},
            "limits": {"news_generation": 10, "blockchain_validation": 10}
        }
        res_patch = api_session.patch(url_patch, json=payload_reset)
        assert res_patch.status_code == 200, "No se pudo resetear la cuota"
    else:
        assert res.status_code == 201, f"Error al crear cliente de cuota: {res.text}"

def test_1_publish_new(api_session, computed_client_id):
    """
    PASO 2: Publica una noticia usando el client_id como query param.
    """
    logger.info("--- INICIO: test_1_publish_new ---")
    payload = {
        "text": "Catalunya tiene una población de más de 7 millones de habitantes de los que 2 millones de niños en edad escolar."
    }

    # Se envía el client_id en el query string
    r = api_session.post(
        f"{NEWS_HANDLER_URL}/publishNew", 
        json=payload, 
        params={"client_id": computed_client_id}
    )
    
    assert r.status_code == 202, f"Error en publicación: {r.text}"
    data = r.json()
    
    assert "order_id" in data
    shared_data["order_id"] = data["order_id"]
    logger.info(f"✅ Noticia publicada. Order ID: {shared_data['order_id']}")

# MODIFICACIÓN AQUÍ: Se añade el fixture computed_client_id
def test_2_get_order_status(api_session, computed_client_id):
    """
    PASO 3: Verifica que la orden alcance el estado VALIDATED.
    """
    order_id = shared_data.get("order_id")
    assert order_id is not None, "No se encontró order_id del paso anterior"

    timeout = 20 # Aumentado para dar tiempo al procesamiento blockchain/ML
    interval = 2
    start_time = time.time()
    last_status = None

    logger.info(f"--- INICIO: test_2_get_order_status para ID {order_id} ---")

    while True:
        # MODIFICACIÓN AQUÍ: Se añaden los params obligatorios
        r = api_session.get(
            f"{NEWS_HANDLER_URL}/orders/{order_id}",
            params={
                "client_id": computed_client_id,
                "admin": "false" # Testeamos como usuario normal para asegurar que la seguridad es correcta
            }
        )
        
        if r.status_code == 200:
            data = r.json()
            last_status = data.get("status")
            logger.info(f"⏳ Estado actual: {last_status}")
            
            if last_status == "VALIDATED":
                logger.info("✅ Test completado con éxito: Orden VALIDATED")
                break
        else:
            logger.warning(f"⚠️ Error consultando estado ({r.status_code}): {r.text}")

        if time.time() - start_time > timeout:
            pytest.fail(f"Timeout: La orden no llegó a VALIDATED. Estado final: {last_status}")

        time.sleep(interval)
