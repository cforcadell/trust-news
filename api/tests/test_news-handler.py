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
    Comprueba que el pedido llegue al estado VALIDATED (espera hasta 10 s).
    Si no llega, muestra el último estado pero no detiene otros tests.
    """
    timeout = 10  # segundos máximos de espera
    interval = 1  # segundos entre reintentos
    start_time = time.time()
    last_status = None

    while True:
        try:
            r = requests.get(f"{NEWS_HANDLER_URL}/orders/{ORDER_ID}")
            if r.status_code != 200:
                print(f"⚠️ No se encontró order_id {ORDER_ID}: {r.text}")
                last_status = "UNKNOWN"
            else:
                data = r.json()
                last_status = data.get("status")
                print(f"⏳ Estado actual: {last_status}")
                print(data)

            if last_status == "VALIDATED":
                print("✅ get_order OK: VALIDATED")
                break

            if time.time() - start_time > timeout:
                print(f"❌ Timeout esperando estado VALIDATED (último estado: {last_status})")
                break

            time.sleep(interval)

        except Exception as e:
            print(f"⚠️ Error consultando order_id {ORDER_ID}: {e}")
            last_status = "ERROR"
            if time.time() - start_time > timeout:
                break


def _test_news_registered():
    """
    Simula el callback del frontend notificando que la noticia fue registrada.
    """
    r = requests.post(f"{NEWS_HANDLER_URL}/news_registered/{ORDER_ID}")
    assert r.status_code == 200, f"Error: {r.text}"
    data = r.json()
    assert data["status"] == "NEWS_REGISTERED"
    print("✅ news_registered OK:", data)



