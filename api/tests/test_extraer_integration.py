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
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] TEST-EXTRAER: %(message)s")
logger = logging.getLogger(__name__)

# URLs de los servicios
API_GENERATION_URL = os.getenv("API_GENERATION_URL", "http://127.0.0.1:8071")
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

# ==============================================================================
# Tests
# ==============================================================================

@pytest.mark.integration
def test_0_setup_resource_quota(api_session, computed_client_id):
    """
    PASO 0: Asegura que el cliente existe y tiene cuota suficiente (ADMIN_URL).
    Esto hace que el test sea 100% autónomo y no dependa de datos manuales.
    """
    logger.info(f"--- INICIO: test_0_setup_resource_quota para {computed_client_id} ---")
    url_create = f"{ADMIN_URL}/clients"
    
    payload_setup = {
        "client_id": computed_client_id,
        "name": "Integration Test Client",
        "limits": {"news_generation": 2, "blockchain_validation": 2},
        "consumed": {"news_generation": 0, "blockchain_validation": 0},
        "status": "Active"
    }
    
    res = api_session.post(url_create, json=payload_setup)
    
    if res.status_code in [400, 422, 409]:
        logger.info("El cliente ya existe, reseteando cuotas a 0...")
        url_patch = f"{ADMIN_URL}/clients/{computed_client_id}"
        payload_reset = {
            "consumed": {"news_generation": 0, "blockchain_validation": 0},
            "limits": {"news_generation": 2, "blockchain_validation": 2}
        }
        res_patch = api_session.patch(url_patch, json=payload_reset)
        assert res_patch.status_code == 200, "No se pudo resetear la cuota"
    else:
        assert res.status_code == 201, f"Error al crear cliente de cuota: {res.text}"


@pytest.mark.integration
def test_1_extraer_endpoint_success(api_session, computed_client_id):
    """
    Test de éxito: Envía un texto y un client_id válido.
    Valida que se descuente la cuota y devuelva las aserciones.
    """
    logger.info("--- INICIO: test_1_extraer_endpoint_success ---")
    url = f"{API_GENERATION_URL}/extraer"
    
    payload = {
        "text": "Catalunya tiene una población de 8 millones de habitantes y una superficie de 32.000 km2."
    }

    # Pasamos el client_id por params para que se adjunte a la query url (?client_id=...)
    response = api_session.post(url, json=payload, params={"client_id": computed_client_id})

    assert response.status_code == 200, f"Error HTTP {response.status_code}: {response.text}"

    data = response.json()

    # ==== Validaciones de estructura ====
    assert data["action"] == "assertions_generated"
    assert "order_id" in data
    
    payload_data = data["payload"]
    assert payload_data["text"] == payload.get("text")
    
    assertions = payload_data["assertions"]
    assert isinstance(assertions, list)
    assert len(assertions) > 0

    for a in assertions:
        assert "idAssertion" in a
        assert "text" in a
        assert "categoryId" in a

    logger.info(f"✅ Test exitoso. Aserciones extraídas correctamente.")


@pytest.mark.integration
def test_2_simulate_quota_exhaustion(api_session, computed_client_id):
    """
    Simula que el usuario ha agotado sus cuotas mediante un PATCH directo a la base de datos.
    """
    logger.info("--- INICIO: test_2_simulate_quota_exhaustion ---")
    url_patch = f"{ADMIN_URL}/clients/{computed_client_id}"
    payload_reset = {
        "consumed": {"news_generation": 2, "blockchain_validation": 2} # Igualamos el límite (2/2)
    }
    res_patch = api_session.patch(url_patch, json=payload_reset)
    assert res_patch.status_code == 200, "No se pudo simular el agotamiento de cuota"
    logger.info("✅ Cuota agotada artificialmente para la siguiente prueba.")


@pytest.mark.integration
def test_3_extraer_endpoint_quota_exceeded(api_session, computed_client_id):
    """
    Test de error: Valida que si un cliente no tiene cuota, el endpoint devuelve 429.
    """
    logger.info("--- INICIO: test_3_extraer_endpoint_quota_exceeded ---")
    url = f"{API_GENERATION_URL}/extraer"
    
    payload = {
        "text": "Texto de prueba para cuota excedida."
    }

    response = api_session.post(url, json=payload, params={"client_id": computed_client_id})

    assert response.status_code == 429, f"Se esperaba 429, pero dio {response.status_code}"
    
    error_detail = response.json().get("detail", "")
    assert "news_generation" in error_detail.lower() or "quota" in error_detail.lower()
    
    logger.info("✅ El sistema bloqueó correctamente la petición por falta de cuota (429).")


@pytest.mark.integration
def test_4_extraer_missing_client_id(api_session):
    """
    Valida que si no se envía el client_id, el sistema devuelve error 422 (Unprocessable Entity).
    """
    logger.info("--- INICIO: test_4_extraer_missing_client_id ---")
    url = f"{API_GENERATION_URL}/extraer" 
    payload = {"text": "Texto"}

    # No le pasamos el param "client_id" a propósito
    response = api_session.post(url, json=payload)

    assert response.status_code == 422, f"Se esperaba 422, pero dio {response.status_code}"
    logger.info("✅ El sistema rechazó correctamente la petición sin client_id (422).")