import csv
import json
import os
import statistics
from collections import defaultdict
from datetime import datetime
from tabulate import tabulate  # pip install tabulate

OUTPUT_DIR = "output"
TIME_FORMAT = "%d/%m/%Y %H:%M:%S"

def load_orders():
    orders = []
    with open(os.path.join(OUTPUT_DIR, "orders.csv")) as f:
        reader = csv.DictReader(f)
        for row in reader:
            orders.append(row["order_id"])
    return orders

def load_json(order_id, filename):
    path = os.path.join(OUTPUT_DIR, order_id, filename)
    with open(path) as f:
        return json.load(f)

def parse_time(ts):
    return datetime.strptime(ts, TIME_FORMAT)

def main():
    orders = load_orders()

    num_assertions_list = []
    percent_valid_assertions_per_order = []

    approvals_per_validator = defaultdict(list)
    zeros_per_validator = defaultdict(list)
    unknowns_per_validator = defaultdict(list)
    response_times_per_validator = defaultdict(list)

    for order_id in orders:
        order = load_json(order_id, "order.json")
        events = load_json(order_id, "events.json")

        assertions = order.get("assertions", [])
        validations = order.get("validations", {})

        num_assertions_list.append(len(assertions))

        valid_assertions = 0

        # Prepara diccionario para tiempos
        request_times = defaultdict(dict)  # validator -> assertion -> timestamp
        completed_times = defaultdict(dict)

        for ev in events:
            action = ev["action"]
            payload = ev["payload"]
            validator = payload.get("idValidator")
            assertion = payload.get("idAssertion")
            ts = parse_time(ev["timestamp"])
            if action == "request_validation" and validator and assertion:
                request_times[validator][assertion] = ts
            elif action == "validation_completed" and validator and assertion:
                completed_times[validator][assertion] = ts

        # Calcula tiempos de respuesta por validador
        for validator in request_times:
            for assertion, start_time in request_times[validator].items():
                end_time = completed_times.get(validator, {}).get(assertion)
                if end_time:
                    delta = (end_time - start_time).total_seconds()
                    response_times_per_validator[validator].append(delta)

        # Procesa validaciones
        for assertion_id, vdict in validations.items():
            balance = 0
            for validator, vdata in vdict.items():
                approval = vdata["approval"]
                if approval == 1:
                    approvals_per_validator[validator].append(1)
                    balance += 1
                elif approval == 0:
                    zeros_per_validator[validator].append(1)
                else:
                    unknowns_per_validator[validator].append(1)
                    balance -= 1
            if balance > 0:
                valid_assertions += 1

        percent_valid_assertions_per_order.append(
            (valid_assertions / len(assertions) * 100) if assertions else 0
        )

    # === TABLA ESTADÍSTICAS GLOBALES ===
    global_table = [
        ["Número de órdenes", len(orders)],
        ["Número medio de aserciones por orden", f"{statistics.mean(num_assertions_list):.2f}"],
        ["Varianza del número de aserciones", f"{statistics.variance(num_assertions_list) if len(num_assertions_list)>1 else 0:.2f}"],
        ["% medio de aserciones válidas por orden", f"{statistics.mean(percent_valid_assertions_per_order):.2f}%"],
        ["Varianza % de aserciones válidas", f"{statistics.variance(percent_valid_assertions_per_order) if len(percent_valid_assertions_per_order)>1 else 0:.2f}"]
    ]
    print("\n=== ESTADÍSTICAS GLOBALES ===")
    print(tabulate(global_table, headers=["Métrica", "Valor"], tablefmt="grid"))

    # === TABLA ESTADÍSTICAS POR VALIDADOR ===
    all_validators = set(list(approvals_per_validator.keys()) +
                         list(zeros_per_validator.keys()) +
                         list(unknowns_per_validator.keys()))
    validator_table = []
    for v in all_validators:
        total = len(approvals_per_validator[v]) + len(zeros_per_validator[v]) + len(unknowns_per_validator[v])
        t_true = len(approvals_per_validator[v])
        t_false = len(zeros_per_validator[v])
        t_unknown = len(unknowns_per_validator[v])

        mean_time = statistics.mean(response_times_per_validator[v]) if response_times_per_validator[v] else 0
        var_time = statistics.variance(response_times_per_validator[v]) if len(response_times_per_validator[v])>1 else 0

        var_true = statistics.variance(approvals_per_validator[v]) if len(approvals_per_validator[v])>1 else 0
        var_false = statistics.variance(zeros_per_validator[v]) if len(zeros_per_validator[v])>1 else 0
        var_unknown = statistics.variance(unknowns_per_validator[v]) if len(unknowns_per_validator[v])>1 else 0

        validator_table.append([
            v, total, t_true, t_false, t_unknown,
            f"{var_true:.2f}", f"{var_false:.2f}", f"{var_unknown:.2f}",
            f"{mean_time:.2f}", f"{var_time:.2f}"
        ])

    print("\n=== ESTADÍSTICAS POR VALIDADOR ===")
    headers_validator = ["Validador", "Total", "True", "False", "Unknown",
                         "Var True", "Var False", "Var Unknown",
                         "Tiempo medio resp (s)", "Var Tiempo (s²)"]
    print(tabulate(validator_table, headers=headers_validator, tablefmt="grid"))

    # === TABLA RESUMEN GLOBAL DE VALIDADORES ===
    true_vals = [len(approvals_per_validator[v]) for v in all_validators]
    false_vals = [len(zeros_per_validator[v]) for v in all_validators]
    unknown_vals = [len(unknowns_per_validator[v]) for v in all_validators]

    summary_table = [
        ["Suma true", sum(true_vals)],
        ["Suma false", sum(false_vals)],
        ["Suma unknown", sum(unknown_vals)],
        ["Varianza total true", f"{statistics.variance(true_vals) if len(true_vals)>1 else 0:.2f}"],
        ["Varianza total false", f"{statistics.variance(false_vals) if len(false_vals)>1 else 0:.2f}"],
        ["Varianza total unknown", f"{statistics.variance(unknown_vals) if len(unknown_vals)>1 else 0:.2f}"]
    ]
    print("\n=== RESUMEN GLOBAL DE VALIDADORES ===")
    print(tabulate(summary_table, headers=["Métrica", "Valor"], tablefmt="grid"))

if __name__ == "__main__":
    main()
