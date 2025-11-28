import requests
import time
import statistics
from collections import defaultdict
import argparse
import csv

BASE_URL = "http://127.0.0.1:8072"

def publish_news(text):
    resp = requests.post(f"{BASE_URL}/publishNew", json={"text": text})
    resp.raise_for_status()
    return resp.json()["order_id"]

def get_order(order_id):
    resp = requests.get(f"{BASE_URL}/orders/{order_id}")
    resp.raise_for_status()
    return resp.json()

def main(text, num_runs, timeout, csv_file):
    times_to_validated = []
    orders_not_validated = 0
    num_assertions_list = []

    # Estadísticas por validador
    positive_approvals_per_validator = defaultdict(list)
    zero_approval_per_validator = defaultdict(list)
    validator_completion_times = defaultdict(list)
    approval1_gt2_per_validator = defaultdict(list)

    percent_valid_assertions_per_order = []

    csv_rows = []

    for run in range(num_runs):
        print(f"\n=== Run {run+1}/{num_runs} ===")
        order_id = publish_news(text)
        start_time = time.time()
        order = get_order(order_id)

        # Diccionario para registrar el primer momento en que cada validador completa cada aserción
        validator_times = defaultdict(dict)

        # Esperar hasta que se VALIDATED o timeout
        elapsed = 0
        while order["status"] != "VALIDATED" and elapsed < timeout:
            current_time = time.time()
            # Registrar tiempos por validador y aserción
            for assertion_id, val_dict in order.get("validations", {}).items():
                for validator, vdata in val_dict.items():
                    if assertion_id not in validator_times[validator]:
                        validator_times[validator][assertion_id] = current_time - start_time

            pending = order.get("validators_pending")
            print(f"Order {order_id} estado: {order['status']}, validaciones pendientes: {pending}")
            time.sleep(1)
            elapsed = time.time() - start_time
            order = get_order(order_id)

        if order["status"] == "VALIDATED":
            print(f"Order {order_id} VALIDATED en {elapsed:.2f}s")
            times_to_validated.append(elapsed)
        else:
            print(f"Order {order_id} NO se VALIDATED en {timeout}s")
            orders_not_validated += 1

        assertions = order.get("assertions", [])
        num_assertions_list.append(len(assertions))
        validations = order.get("validations", {})

        # Calcular % de aserciones válidas por orden
        valid_assertions_count = 0

        for assertion_id, val_dict in validations.items():
            all_validators_approval1_gt2 = True
            for validator, vdata in val_dict.items():
                approval = vdata["approval"]

                if approval == 1:
                    positive_approvals_per_validator[validator].append(1)
                elif approval == 0:
                    zero_approval_per_validator[validator].append(1)
                else:
                    positive_approvals_per_validator[validator].append(0)

                # Validación approval1 > approval2 (ignorar 0)
                if approval == 2:
                    all_validators_approval1_gt2 = False

                # CSV
                csv_rows.append({
                    "order_id": order_id,
                    "assertion_id": assertion_id,
                    "validator": validator,
                    "approval_0": 1 if approval==0 else 0,
                    "approval_1": 1 if approval==1 else 0,
                    "approval_2": 1 if approval==2 else 0
                })

            if all_validators_approval1_gt2:
                valid_assertions_count += 1

        percent_valid_assertions_per_order.append(
            (valid_assertions_count / len(assertions) * 100) if assertions else 0
        )

        # Tiempo de respuesta por validador para esta orden
        for validator, times_dict in validator_times.items():
            max_time = max(times_dict.values())
            validator_completion_times[validator].append(max_time)

    # Estadísticas finales
    print("\n=== Estadísticas finales ===")
    if times_to_validated:
        print(f"Tiempo medio hasta VALIDATED: {sum(times_to_validated)/len(times_to_validated):.2f}s")
    else:
        print("No se alcanzó VALIDATED en ninguna orden.")

    print(f"Número de órdenes que no llegaron a VALIDATED: {orders_not_validated}")
    print(f"Número medio de aserciones: {statistics.mean(num_assertions_list):.2f}")
    print(f"Varianza del número de aserciones: {statistics.variance(num_assertions_list) if len(num_assertions_list)>1 else 0:.2f}")
    print(f"Media % de aserciones válidas por orden: {statistics.mean(percent_valid_assertions_per_order):.2f}%")

    # Estadísticas por validador
    print("\nEstadísticas por validador:")
    for validator in validator_completion_times.keys():
        times = validator_completion_times[validator]
        avg_response_time = statistics.mean(times)
        approvals1 = positive_approvals_per_validator.get(validator, [])
        avg_positive = statistics.mean(approvals1) if approvals1 else 0
        zero_var = statistics.variance(zero_approval_per_validator[validator]) if len(zero_approval_per_validator[validator])>1 else 0

        print(f"  {validator} - tiempo medio respuesta: {avg_response_time:.2f}s, media approvals=1: {avg_positive:.2f}, varianza approvals=0: {zero_var:.2f}")

    # Exportar CSV
    with open(csv_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["order_id","assertion_id","validator","approval_0","approval_1","approval_2"])
        writer.writeheader()
        writer.writerows(csv_rows)

    print(f"\nCSV exportado a {csv_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ciclo de verificación con estadísticas completas y tiempos por validador")
    parser.add_argument("--text", required=True, help="Texto de la noticia")
    parser.add_argument("--num_runs", type=int, default=1, help="Número de ejecuciones")
    parser.add_argument("--timeout", type=int, default=60, help="Tiempo máximo de espera por orden (s)")
    parser.add_argument("--csv_file", type=str, default="validations_summary.csv", help="Archivo CSV de salida")
    args = parser.parse_args()

    main(args.text, args.num_runs, args.timeout, args.csv_file)
