import requests
import pytest
import time
import json
import os
import uuid

# URL base del servicio orquestador dentro del docker-compose o en local
NEWS_HANDLER_URL = os.getenv("NEWS_HANDLER_URL", "http://localhost:8072")

# === Helper para crear una noticia ===
def test_publish_new():
    """
    Verifica que el endpoint /publishNew funcione correctamente y devuelva order_id.
    """
    payload = {
        "text": "Catalunya tiene una población de más de 7 millones de habitantes."
        }

    r = requests.post(f"{NEWS_HANDLER_URL}/publishNew", json=payload)
    assert r.status_code == 202, f"Error: {r.text}"

    data = r.json()
    assert "order_id" in data, "No se devolvió order_id"
    assert data["status"] == "ASSERTIONS_REQUESTED"
    print("✅ publishNew OK:", data)

    # Guardamos order_id para los siguientes tests
    global ORDER_ID
    ORDER_ID = data["order_id"]
    time.sleep(1)  # pequeña pausa para que se inserte en Mongo


def test_get_order():
    """
    Comprueba que el pedido recién creado se pueda consultar.
    """
    r = requests.get(f"{NEWS_HANDLER_URL}/orders/{ORDER_ID}")
    assert r.status_code == 200, f"No se encontró order_id {ORDER_ID}: {r.text}"
    data = r.json()
    assert data["status"] in ["PENDING", "ASSERTIONS_REQUESTED"]
    print("✅ get_order OK:", data["status"])


def test_news_registered():
    """
    Simula el callback del frontend notificando que la noticia fue registrada.
    """
    r = requests.post(f"{NEWS_HANDLER_URL}/news_registered/{ORDER_ID}")
    assert r.status_code == 200, f"Error: {r.text}"
    data = r.json()
    assert data["status"] == "NEWS_REGISTERED"
    print("✅ news_registered OK:", data)



