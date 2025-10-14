import os
import pytest
import requests

# Dirección del servicio FastAPI en docker-compose
IPFS_FASTAPI_URL = os.getenv("IPFS_FASTAPI_URL", "http://localhost:8060")

@pytest.mark.integration
def test_ipfs_upload_with_content_bytes():
    """
    Prueba de integración para /ipfs/upload con contenido en memoria (sin fichero físico).
    """
    url = f"{IPFS_FASTAPI_URL}/ipfs/upload"

    data = {
        "filename": "test_doc.json",
        "content_bytes": b'{"titulo": "Documento de prueba", "valor": 123}'
    }

    # Nota: 'requests' no soporta enviar bytes en multipart automáticamente
    # por tanto enviamos content_bytes como parte de un form
    files = {"file": None}
    response = requests.post(url, data={"filename": data["filename"]}, files={"file": ("test_doc.json", data["content_bytes"])})
    
    assert response.status_code == 200, f"Error HTTP: {response.status_code} - {response.text}"

    res_json = response.json()
    assert "cid" in res_json, "La respuesta no contiene 'cid'"
    assert "filename" in res_json, "La respuesta no contiene 'filename'"

    cid = res_json["cid"]
    print(f"✅ Archivo subido correctamente a IPFS con CID={cid}")

@pytest.mark.integration
def test_ipfs_upload_without_content():
    """
    Debe devolver error 400 si no se proporciona contenido (ni file ni content_bytes).
    """
    url = f"{IPFS_FASTAPI_URL}/ipfs/upload"
    response = requests.post(url, data={"filename": "empty.json"})
    assert response.status_code == 400, f"Esperado 400, recibido {response.status_code}: {response.text}"
    print("✅ Error correctamente manejado en subida sin contenido")

@pytest.mark.integration
def test_ipfs_get_invalid_cid():
    """
    Debe devolver error (HTTPException 500 o 4xx) para un CID inexistente.
    """
    fake_cid = "QmFakeCIDNoExiste123456789"
    url = f"{IPFS_FASTAPI_URL}/ipfs/{fake_cid}"

    response = requests.get(url)
    assert response.status_code >= 400, f"Se esperaba error para CID inválido: {response.status_code}"
    print(f"✅ Respuesta esperada para CID inexistente ({fake_cid}): {response.status_code}")
