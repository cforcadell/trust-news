import os
import logging

import jwt
import pytest
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "https://localhost:7443/auth/realms/TrustNews/protocol/openid-connect/token")
AUTH_CLIENT_ID = os.getenv("AUTH_CLIENT_ID", "TrustNewsApi")
AUTH_CLIENT_SECRET = os.getenv("AUTH_CLIENT_SECRET", "")


@pytest.fixture(scope="session")
def auth_token():
    logger.info("Solicitando token a Keycloak: %s", KEYCLOAK_URL)
    payload = {
        "grant_type": "client_credentials",
        "client_id": AUTH_CLIENT_ID,
        "client_secret": AUTH_CLIENT_SECRET,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    response = requests.post(KEYCLOAK_URL, data=payload, headers=headers, verify=False)
    assert response.status_code == 200, f"Error Keycloak: {response.text}"
    return response.json()["access_token"]


@pytest.fixture(scope="session")
def computed_client_id(auth_token):
    unverified_claims = jwt.decode(auth_token, options={"verify_signature": False})
    sub = unverified_claims.get("sub", "unknown_sub")
    token_client_id = unverified_claims.get("client_id")
    return f"{token_client_id}_{sub}" if token_client_id else f"user_{sub}"


@pytest.fixture(scope="session")
def api_session(auth_token):
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {auth_token}"})
    return session
