import requests
import time
import argparse
import csv
import json
import os

BASE_URL = "http://127.0.0.1:8072"
OUTPUT_DIR = "output"

def publish_news(text):
    resp = requests.post(f"{BASE_URL}/publishNew", json={"text": text})
    resp.raise_for_status()
    return resp.json()["order_id"]

def get_order(order_id):
    resp = requests.get(f"{BASE_URL}/orders/{order_id}")
    resp.raise_for_status()
    return resp.json()

def get_events(order_id):
    resp = requests.get(f"{BASE_URL}/news/{order_id}/events")
    resp.raise_for_status()
    return resp.json()

def wait_until_validated(order_id, timeout):
    start = time.time()
    order = get_order(order_id)

    while order["status"] != "VALIDATED":
        print(f"Order Status: {order['status']}. Validators Pending: {order['validators_pending']}")
        if time.time() - start > timeout:
            return None
        time.sleep(1)
        order = get_order(order_id)

    return order

def save_order_data(order_id, order_data, events_data):
    order_dir = os.path.join(OUTPUT_DIR, str(order_id))
    os.makedirs(order_dir, exist_ok=True)

    with open(os.path.join(order_dir, "order.json"), "w") as f:
        json.dump(order_data, f, indent=2)

    with open(os.path.join(order_dir, "events.json"), "w") as f:
        json.dump(events_data, f, indent=2)

def main(text, num_runs, timeout):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    orders_csv = os.path.join(OUTPUT_DIR, "orders.csv")

    with open(orders_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["order_id"])

        for run in range(num_runs):
            print(f"\n=== Run {run+1}/{num_runs} ===")
            order_id = publish_news(text)
            print(f"Order publicada: {order_id}")

            order = wait_until_validated(order_id, timeout)
            if not order:
                print(f"Order {order_id} NO VALIDATED (timeout)")
                continue

            events = get_events(order_id)
            save_order_data(order_id, order, events)

            writer.writerow([order_id])
            print(f"Order {order_id} VALIDATED y guardada")

    print("\nProceso finalizado.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Publica noticias y guarda órdenes VALIDATED")
    parser.add_argument("--text", required=True)
    parser.add_argument("--num_runs", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    main(args.text, args.num_runs, args.timeout)
