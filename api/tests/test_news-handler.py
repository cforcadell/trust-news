import os
import time
import pytest
import requests
import jwt
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
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "https://localhost:7443/auth/realms/TrustNews/protocol/openid-connect/token")

# Credenciales
AUTH_CLIENT_ID = os.getenv("AUTH_CLIENT_ID", "TrustNewsApi")
AUTH_CLIENT_SECRET = os.getenv("AUTH_CLIENT_SECRET", "glFlzU7E6j25b6N9WAVAf2Y4xWd2opMz")

# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture(scope="session")
def auth_token():
    """Obtiene el token Bearer desde Keycloak"""
    payload = {
        "grant_type": "client_credentials",
        "client_id": AUTH_CLIENT_ID,
        "client_secret": AUTH_CLIENT_SECRET
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    response = requests.post(KEYCLOAK_URL, data=payload, headers=headers, verify=False)
    assert response.status_code == 200, f"Error Keycloak: {response.text}"
    return response.json()["access_token"]

@pytest.fixture(scope="session")
def computed_client_id(auth_token):
    """Calcula el client_id extrayéndolo del JWT"""
    unverified_claims = jwt.decode(auth_token, options={"verify_signature": False})
    sub = unverified_claims.get("sub", "unknown_sub")
    token_client_id = unverified_claims.get("client_id")
    return f"{token_client_id}_{sub}" if token_client_id else f"user_{sub}"

@pytest.fixture(scope="session")
def api_session(auth_token):
    """Sesión HTTP con el token inyectado en la cabecera"""
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {auth_token}"})
    return session

# Objeto para compartir el order_id entre funciones de test
shared_data = {}

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