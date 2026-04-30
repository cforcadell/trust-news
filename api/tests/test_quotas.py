import os
import time
import pytest
import requests
import jwt
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==============================================================================
# Configuración (Ajustar puertos/hosts según tu entorno local/docker)
# ==============================================================================
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "https://localhost:9443/auth/realms/TrustNews/protocol/openid-connect/token")
AUTH_CLIENT_ID = os.getenv("AUTH_CLIENT_ID", "TrustNewsApi")
AUTH_CLIENT_SECRET = os.getenv("AUTH_CLIENT_SECRET", "glFlzU7E6j25b6N9WAVAf2Y4xWd2opMz")

# URL del Gateway expuesto hacia fuera
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://gateway.apis.svc.cluster.local:8500/backend")

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
    """Calcula el client_id interno exacto que usará el Gateway y Orquestador"""
    unverified_claims = jwt.decode(auth_token, options={"verify_signature": False})
    sub = unverified_claims.get("sub", "unknown_sub")
    token_client_id = unverified_claims.get("client_id")
    
    if token_client_id:
        return f"{token_client_id}_{sub}"
    else:
        return f"user_{sub}"

@pytest.fixture(scope="session")
def api_session(auth_token):
    """Sesión HTTP con el token ya inyectado"""
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {auth_token}"})
    return session

# ==============================================================================
# Tests
# ==============================================================================

def test_1_setup_client_quota(api_session, computed_client_id):
    """Crea o resetea el cliente en el sistema de cuotas con límites bajos"""
    # Intentamos crear el cliente primero
    url_create = f"{GATEWAY_URL}/clients"
    payload_create = {
        "client_id": computed_client_id,
        "name": "Test Quota Client",
        "limits": {
            "news_generation": 2,
            "blockchain_validation": 2
        },
        "consumed": {
            "news_generation": 0,
            "blockchain_validation": 0
        },
        "status": "alta"
    }
    
    res = api_session.post(url_create, json=payload_create)
    
    # Si ya existe (400), hacemos un PATCH para forzar el reseteo a 0 consumidos y límite 2
    if res.status_code == 400:
        url_patch = f"{GATEWAY_URL}/clients/{computed_client_id}"
        payload_patch = {
            "limits": {"news_generation": 2, "blockchain_validation": 2},
            "consumed": {"news_generation": 0, "blockchain_validation": 0},
            "status": "alta"
        }
        res_patch = api_session.patch(url_patch, json=payload_patch)
        assert res_patch.status_code == 200, "Falló al resetear la cuota del cliente existente"
    else:
        assert res.status_code == 201, "Falló al crear el cliente de cuota"

def test_2_publish_new_within_quota(api_session):
    """Debería permitir crear una noticia porque la cuota (0 consumido < 2 límite) está OK"""
    url = f"{GATEWAY_URL}/orders/publishNew"
    payload = {"text": "Texto de prueba dentro de los límites de cuota"}
    
    res = api_session.post(url, json=payload)
    # Esperamos 202 Accepted según la especificación de tu orquestador
    assert res.status_code == 202, f"Falló al publicar: {res.text}"

def test_3_simulate_quota_exhaustion(api_session, computed_client_id):
    """Simulamos que Kafka ya procesó muchos eventos e incrementamos el consumo manualmente al límite"""
    url_patch = f"{GATEWAY_URL}/clients/{computed_client_id}"
    payload_patch = {
        "consumed": {
            "news_generation": 2,       # Excede/Iguala el límite de 2
            "blockchain_validation": 2  # Excede/Iguala el límite de 2
        }
    }
    
    res = api_session.patch(url_patch, json=payload_patch)
    assert res.status_code == 200

def test_4_publish_new_exceeds_quota(api_session):
    """Debería fallar al intentar publicar porque simulamos que se agotó la cuota"""
    url = f"{GATEWAY_URL}/orders/publishNew"
    payload = {"text": "Texto de prueba que debería fallar por cuota excedida"}
    
    res = api_session.post(url, json=payload)
    
    # Validamos que devuelva 429 Too Many Requests (o 403 según lo hayas mapeado)
    assert res.status_code in [429, 403], f"Se esperaba rechazo de cuota, pero dio: {res.status_code}"
    
    # Validar el mensaje de error del Orquestador
    error_data = res.json()
    assert "Quota generate assertions exceded" in error_data.get("detail", "")

def test_5_publish_with_assertions_exceeds_quota(api_session):
    """Valida el rechazo de cuota para el endpoint de validaciones (blockchain_validation)"""
    url = f"{GATEWAY_URL}/orders/publishWithAssertions"
    payload = {
        "text": "Texto con aserciones",
        "cliente": {"client_id": "ignorado_por_gateway_que_usa_jwt"}, 
        "assertions": [
            {"idAssertion": "A1", "text": "Asertion 1", "categoryId": 1}
        ]
    }
    
    res = api_session.post(url, json=payload)
    
    assert res.status_code in [429, 403], f"Se esperaba rechazo de cuota, pero dio: {res.status_code}"
    error_data = res.json()
    assert "Quota validations exceded" in error_data.get("detail", "")