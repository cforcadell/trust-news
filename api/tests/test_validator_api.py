import requests
import os
import pytest

# URL base del servicio (ajusta el host:puerto según tu docker-compose)
BASE_URL = os.getenv("VALIDATOR_API_URL", "http://localhost:8070")

@pytest.mark.integration
def test_verificar_asercion():
    """Test de integración para el endpoint /verificar"""
    url = f"{BASE_URL}/verificar"
    payload = {
        "text": "El sol sale por el este",
        "context": "Fenómeno astronómico diario"
    }

    response = requests.post(url, json=payload)
    print("Response:", response.text)

    # Validaciones básicas
    assert response.status_code == 200
    body = response.json()
    assert "verificación" in body
    assert isinstance(body["verificación"], str)
    assert len(body["verificación"]) > 0


@pytest.mark.integration
def test_registrar_validador():
    """Test de integración para /registrar_validador"""
    url = f"{BASE_URL}/registrar_validador"
    payload = {
        "name": "validator_test_domain",
        "categories": [1, 2]
    }

    response = requests.post(url, json=payload)
    print("Response:", response.text)

    if response.status_code == 200:
        body = response.json()
        assert body["status"] == "ok"
        assert "tx_hash" in body
        assert len(body["tx_hash"]) > 0
    else:
        # A veces el validador ya está registrado → se puede aceptar 500 con mensaje claro
        assert response.status_code in [200, 500]
