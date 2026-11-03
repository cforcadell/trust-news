import os
import time
import requests
import urllib3
import logging

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==============================================================================
# Configuración de Logs para los Tests
# ==============================================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] TEST: %(message)s")
logger = logging.getLogger(__name__)

# ==============================================================================
# Configuración
# ==============================================================================
TEXT_NEW = "Catalunya tiene una población de más de 7 millones de habitantes de los que 2 millones de niños en edad escolar y otro millón son europeos."

# URLs de los servicios (Admin de Cuotas y Gateway Público)
ADMIN_URL = os.getenv("ADMIN_URL", "http://127.0.0.1:8400")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:8500")

# ==============================================================================
# Tests
# ==============================================================================

def test_1_setup_client_quota(api_session, computed_client_id):
    """Crea o resetea el cliente en el sistema de cuotas (ADMIN_URL)"""
    logger.info(f"--- INICIO: test_1_setup_client_quota ({computed_client_id}) ---")
    url_create = f"{ADMIN_URL}/clients"
    payload_create = {
        "client_id": computed_client_id,
        "name": "Test Quota Client",
        "limits": {"news_generation": 2, "blockchain_validation": 2},
        "consumed": {"news_generation": 0, "blockchain_validation": 0},
        "status": "Active"
    }
    
    res = api_session.post(url_create, json=payload_create)
    
    if res.status_code == 400: # Ya existe
        url_patch = f"{ADMIN_URL}/clients/{computed_client_id}"
        payload_patch = {
            "limits": {"news_generation": 2, "blockchain_validation": 2},
            "consumed": {"news_generation": 0, "blockchain_validation": 0},
            "status": "Active"
        }
        res_patch = api_session.patch(url_patch, json=payload_patch)
        assert res_patch.status_code == 200, "Falló al resetear la cuota"
    else:
        assert res.status_code == 201, f"Falló al crear el cliente: {res.text}"

def test_2_publish_new_within_quota(api_session):
    """Prueba de publicación dentro del límite de cuota"""
    logger.info("--- INICIO: test_2_publish_new_within_quota ---")
    url = f"{GATEWAY_URL}/orders/publishNew"
    
    # IMPORTANTE: Se añade "cliente" para satisfacer la validación Pydantic de PublishRequest
    payload = {
        "text": TEXT_NEW
    }
    
    res = api_session.post(url, json=payload)
    assert res.status_code == 202, f"Falló al publicar: {res.text}"

def test_3_simulate_quota_exhaustion(api_session, computed_client_id):
    """Simulamos consumo máximo de cuota parcheando en la DB (ADMIN_URL)"""
    logger.info("--- INICIO: test_3_simulate_quota_exhaustion ---")
    url_patch = f"{ADMIN_URL}/clients/{computed_client_id}"
    payload_patch = {
        "consumed": {
            "news_generation": 2,
            "blockchain_validation": 2
        }
    }
    
    res = api_session.patch(url_patch, json=payload_patch)
    assert res.status_code == 200

def test_4_publish_new_exceeds_quota(api_session):
    """Debería fallar con 429 porque la cuota de news_generation está al límite"""
    logger.info("--- INICIO: test_4_publish_new_exceeds_quota ---")
    url = f"{GATEWAY_URL}/orders/publishNew"
    
    # IMPORTANTE: Igual que el test 2, necesita el objeto "cliente"
    payload = {
        "text": "Texto que debería fallar por cuota"
    }
    
    res = api_session.post(url, json=payload)
    assert res.status_code == 429, f"Se esperaba 429, dio: {res.status_code}"
    assert "Quota generate assertions exceded" in res.json().get("detail", "")

def test_5_publish_with_assertions_exceeds_quota(api_session):
    """Debería fallar con 429 porque la cuota de blockchain_validation está al límite"""
    logger.info("--- INICIO: test_5_publish_with_assertions_exceeds_quota ---")
    url = f"{GATEWAY_URL}/orders/publishWithAssertions"
    
    payload = {
        "text": "Texto con aserciones", 
        "assertions": [
            {"idAssertion": "A1", "text": "Asertion 1", "categoryId": 1}
        ]
    }
    
    res = api_session.post(url, json=payload)
    assert res.status_code == 429, f"Se esperaba 429, dio: {res.status_code}"
    assert "Quota validations exceded" in res.json().get("detail", "")

# def test_6_cleanup_client(api_session, computed_client_id):
#     """Limpieza final de la base de datos de cuotas"""
#     logger.info("--- INICIO: test_6_cleanup_client ---")
#     url_delete = f"{ADMIN_URL}/clients/{computed_client_id}"
#     res = api_session.delete(url_delete)
#     assert res.status_code == 200, f"Falló al eliminar cliente: {res.text}"
