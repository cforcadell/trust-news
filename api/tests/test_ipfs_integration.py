import os
import pytest
import requests

# Dirección del servicio FastAPI en docker-compose
IPFS_FASTAPI_URL = os.getenv("IPFS_FASTAPI_URL", "http://localhost:8060")

# Variable global para compartir el CID entre tests
CID_SUBIDO = None


@pytest.mark.integration
def test_ipfs_upload_with_content_bytes():
    """
    Prueba de integración para /ipfs/upload con contenido en memoria (sin fichero físico).
    Sube un JSON a IPFS y guarda el CID devuelto.
    """
    global CID_SUBIDO

    url = f"{IPFS_FASTAPI_URL}/ipfs/upload"
    filename = "test_doc.json"
    content_bytes = b'{"titulo": "Documento de prueba", "valor": 123}'

    # 'requests' no permite bytes directos en data, se usa multipart con files
    files = {"file": (filename, content_bytes)}
    data = {"filename": filename}

    response = requests.post(url, data=data, files=files)
    assert response.status_code == 200, f"Error HTTP: {response.status_code} - {response.text}"

    res_json = response.json()
    assert "cid" in res_json, "La respuesta no contiene 'cid'"
    assert "filename" in res_json, "La respuesta no contiene 'filename'"

    CID_SUBIDO = res_json["cid"]
    print(f"✅ Archivo subido correctamente a IPFS con CID={CID_SUBIDO}")

    # Validación básica del formato CID (Qm... de 46 caracteres aprox)
    assert CID_SUBIDO.startswith("Qm") and len(CID_SUBIDO) >= 40, f"Formato CID sospechoso: {CID_SUBIDO}"


@pytest.mark.integration
def test_ipfs_get_uploaded_cid():
    """
    Prueba de lectura usando el CID obtenido en el test anterior.
    Verifica que el contenido recuperado coincide con el JSON enviado.
    """
    global CID_SUBIDO
    assert CID_SUBIDO is not None, "No hay CID disponible del test anterior"

    url = f"{IPFS_FASTAPI_URL}/ipfs/{CID_SUBIDO}"
    response = requests.get(url)

    assert response.status_code == 200, f"Error HTTP al leer CID: {response.status_code} - {response.text}"

    res_json = response.json()
    assert res_json["cid"] == CID_SUBIDO
    assert "content" in res_json, "La respuesta no contiene 'content'"

    contenido = res_json["content"]
    assert '"titulo": "Documento de prueba"' in contenido, "El contenido recuperado no coincide con el documento original"
    print(f"✅ CID {CID_SUBIDO} leído correctamente con contenido esperado")


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
