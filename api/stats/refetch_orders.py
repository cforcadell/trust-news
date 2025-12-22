import csv
import json
import os
import requests

BASE_URL = "http://127.0.0.1:8072"
OUTPUT_DIR = "output"

def get_order(order_id):
    resp = requests.get(f"{BASE_URL}/orders/{order_id}")
    resp.raise_for_status()
    return resp.json()

def get_events(order_id):
    resp = requests.get(f"{BASE_URL}/news/{order_id}/events")
    resp.raise_for_status()
    return resp.json()

def load_orders_csv():
    orders = []
    csv_path = os.path.join(OUTPUT_DIR, "orders.csv")

    if not os.path.exists(csv_path):
        raise FileNotFoundError("orders.csv no existe")

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            orders.append(row["order_id"])

    return orders

def save_json(order_id, filename, data):
    order_dir = os.path.join(OUTPUT_DIR, str(order_id))
    os.makedirs(order_dir, exist_ok=True)

    filepath = os.path.join(order_dir, filename)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

def main():
    orders = load_orders_csv()
    print(f"📦 Órdenes encontradas: {len(orders)}")

    for order_id in orders:
        print(f"\n🔄 Refrescando order {order_id}")

        try:
            order = get_order(order_id)
            events = get_events(order_id)

            save_json(order_id, "order.json", order)
            save_json(order_id, "events.json", events)

            print(f"✅ Order {order_id} actualizada")

        except Exception as e:
            print(f"❌ Error con order {order_id}: {e}")

    print("\n✅ Proceso terminado")

if __name__ == "__main__":
    main()
