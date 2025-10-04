import asyncio
import json
import os
import uuid
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9093")
REQUEST_TOPIC = "fake_news_requests"
RESPONSE_TOPIC = "fake_news_responses"

async def test_kafka_flow():
    # Mensaje de prueba
    order_id = str(uuid.uuid4())
    message = {
        "action": "generate_assertions",
        "order_id": order_id,
        "payload": {
            "text": (
                "El Gobierno ha anunciado hoy un plan de ayudas para impulsar el uso "
                "de energías renovables en hogares y pymes. "
                "El programa contará con una inversión inicial de 500 millones de euros. "
                "Se prevé que las subvenciones cubran hasta un 40% del coste de instalaciones solares y eólicas. "
                "El objetivo es reducir la dependencia de combustibles fósiles en un 20% para 2030. "
                "Las solicitudes podrán realizarse a partir del próximo mes de noviembre."
            )
        }
    }

    # Crear producer para enviar mensaje
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP)
    await producer.start()
    try:
        await producer.send_and_wait(REQUEST_TOPIC, json.dumps(message).encode())
        print(f"✅ Mensaje enviado a Kafka: {json.dumps(message)}")
    finally:
        await producer.stop()

    # Crear consumer para recibir respuesta
    consumer = AIOKafkaConsumer(
        RESPONSE_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id="test-group",
        auto_offset_reset="earliest"
    )
    await consumer.start()
    try:
        async for msg in consumer:
            data = json.loads(msg.value.decode())
            print("📥 Mensaje recibido:", data)

            # Validaciones básicas
            assert data.get("action") == "assertions_generated"
            assert data.get("order_id") == order_id
            assert "payload" in data
            assert "assertions" in data["payload"]
            assert isinstance(data["payload"]["assertions"], list)
            assert len(data["payload"]["assertions"]) > 0
            break  # solo necesitamos el primer mensaje
    finally:
        await consumer.stop()

# Ejecutar test unitario
if __name__ == "__main__":
    asyncio.run(test_kafka_flow())
