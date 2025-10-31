import os
import requests
import pytest

# Dirección base del contenedor (puede venir del docker-compose)
API_GENERATION_URL = os.getenv("API_GENERATION_URL", "http://localhost:8071")

@pytest.mark.integration
def test_extraer_endpoint():
    """
    Test de integración para el endpoint /extraer de la API de extracción de aserciones.
    - Envía un texto de ejemplo
    - Comprueba que el servicio devuelve un documento JSON con las claves esperadas
    """

    url = f"{API_GENERATION_URL}/extraer"
    payload = {
        "texto": "Catalunya tiene una población de 8 millones de habitantes y una superficie de 32.000 km2."
    }

    response = requests.post(url, json=payload)

    # Debe responder correctamente
    assert response.status_code == 200, f"Error HTTP: {response.status_code}, body: {response.text}"

    data = response.json()

    # Estructura esperada
    assert isinstance(data, dict), "La respuesta debe ser un JSON tipo dict"
    assert "new" in data, "Falta la clave 'new'"
    assert "asertions" in data, "Falta la clave 'asertions'"
    assert isinstance(data["asertions"], list), "'asertions' debe ser una lista"

    # Log de depuración (útil en CI/CD o docker-compose logs)
    print(f" Respuesta /extraer correcta: {data}")


@pytest.mark.integration
def test_extraer_endpoint_empty_text():
    """
    Test de integración para texto vacío — debe responder correctamente (aunque sin aserciones).
    """

    url = f"{API_GENERATION_URL}/extraer"
    payload = {"texto": ""}

    response = requests.post(url, json=payload)
    assert response.status_code == 200, f"Error HTTP: {response.status_code}, body: {response.text}"

    data = response.json()
    assert "asertions" in data, "Falta 'asertions' en la respuesta"
    assert isinstance(data["asertions"], list), "'asertions' debe ser lista"
    print(f"Respuesta vacía /extraer: {data}")
