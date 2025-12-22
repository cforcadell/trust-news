import os
import requests
import pytest

# Dirección base del contenedor (por defecto apunta al puerto 8071)
API_GENERATION_URL = os.getenv("API_GENERATION_URL", "http://localhost:8071")


@pytest.mark.integration
def test_extraer_endpoint():
    """
    Test de integración para el endpoint /extraer de la API de extracción de aserciones.
    Envía un texto de ejemplo y valida que la respuesta siga el formato de evento esperado.
    """

    url = f"{API_GENERATION_URL}/extraer"
    payload = {
        "text": "Catalunya tiene una población de 8 millones de habitantes y una superficie de 32.000 km2."
    }

    response = requests.post(url, json=payload)

    # Verificación de respuesta HTTP
    assert response.status_code == 200, f"Error HTTP {response.status_code}: {response.text}"

    data = response.json()

    # ==== Validaciones principales ====
    assert isinstance(data, dict), "La respuesta debe ser un JSON tipo dict"

    # Campos raíz
    assert "action" in data, "Falta 'action' en la respuesta"
    assert data["action"] == "assertions_generated", "'action' debe ser 'assertions_generated'"

    assert "order_id" in data, "Falta 'order_id' en la respuesta"
    assert isinstance(data["order_id"], str), "'order_id' debe ser una cadena"

    assert "payload" in data, "Falta 'payload' en la respuesta"
    payload_data = data["payload"]
    assert isinstance(payload_data, dict), "'payload' debe ser un objeto JSON"

    # ==== Validaciones del payload ====
    assert "text" in payload_data, "Falta 'text' dentro de 'payload'"
    assert "assertions" in payload_data, "Falta 'assertions' dentro de 'payload'"
    assert "publisher" in payload_data, "Falta 'publisher' dentro de 'payload'"

    assertions = payload_data["assertions"]
    assert isinstance(assertions, list), "'assertions' debe ser una lista"
    assert len(assertions) > 0, "Se esperaba al menos una aserción extraída"

    # Validar estructura de cada aserción
    for a in assertions:
        assert "idAssertion" in a, "Falta 'idAssertion' en una aserción"
        assert "text" in a, "Falta 'text' en una aserción"
        assert "categoryId" in a, "Falta 'categoryId' en una aserción"

    print(f"✅ Respuesta /extraer correcta:\n{data}")

