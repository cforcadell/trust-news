import csv
import json
import os
import statistics
from collections import defaultdict
from datetime import datetime
from tabulate import tabulate  # pip install tabulate

OUTPUT_DIR = "output"
TIME_FORMAT = "%m/%d/%Y %H:%M:%S"


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

    # ================= MÉTRICAS POR ORDEN =================
    num_assertions_list = []

    true_assertions_per_order = []
    false_assertions_per_order = []
    undefined_assertions_per_order = []
    decidable_assertions_per_order = []

    percent_true_decidable_per_order = []

    # Tiempo total de validación de la orden (en segundos)
    order_completion_times = []

    # ================= MÉTRICAS POR VALIDADOR =================
    approvals_per_validator = defaultdict(list)
    falses_per_validator = defaultdict(list)
    unknowns_per_validator = defaultdict(list)
    response_times_per_validator = defaultdict(list)

    for order_id in orders:
        order = load_json(order_id, "order.json")
        events = load_json(order_id, "events.json")

        assertions = order.get("assertions", [])
        validations = order.get("validations", {})

        num_assertions_list.append(len(assertions))

        true_count = 0
        false_count = 0
        undefined_count = 0

        # --------- tiempos de respuesta por validador ----------
        request_times = defaultdict(dict)
        completed_times = defaultdict(dict)

        # --------- tiempo total de la orden ----------
        order_start_time = None
        order_end_time = None
        expected_validations = 0
        completed_validations = set()

        for ev in events:
            action = ev["action"]
            payload = ev["payload"]
            validator = payload.get("idValidator")
            assertion = payload.get("idAssertion")
            ts = parse_time(ev["timestamp"])

            # primer evento = inicio de la orden
            if order_start_time is None:
                order_start_time = ts

            if action == "request_validation" and validator and assertion:
                request_times[validator][assertion] = ts
                expected_validations += 1

            elif action == "validation_completed" and validator and assertion:
                completed_times[validator][assertion] = ts
                completed_validations.add((validator, assertion))
                order_end_time = ts  # nos quedamos con el último

        # --------- tiempos de respuesta por validador ----------
        for validator in request_times:
            for assertion, start_time in request_times[validator].items():
                end_time = completed_times.get(validator, {}).get(assertion)
                if end_time:
                    delta = (end_time - start_time).total_seconds()
                    response_times_per_validator[validator].append(delta)

        # --------- procesado validaciones ----------
        for assertion_id, vdict in validations.items():
            t_true = 0
            t_false = 0

            for validator, vdata in vdict.items():
                approval = vdata.get("approval")
                if approval == 1:
                    approvals_per_validator[validator].append(1)
                    t_true += 1
                elif approval == 2:
                    falses_per_validator[validator].append(1)
                    t_false += 1
                elif approval == 0:
                    unknowns_per_validator[validator].append(1)
                else:
                    raise ValueError(f"Valor approval desconocido: {approval}")

            # clasificación sin unknown
            if t_true > t_false:
                true_count += 1
            elif t_false > t_true:
                false_count += 1
            else:
                undefined_count += 1

        decidable_count = true_count + false_count

        true_assertions_per_order.append(true_count)
        false_assertions_per_order.append(false_count)
        undefined_assertions_per_order.append(undefined_count)
        decidable_assertions_per_order.append(decidable_count)

        percent_true_decidable_per_order.append(
            (true_count / decidable_count * 100) if decidable_count > 0 else 0
        )

        # --------- tiempo total de validación de la orden ----------
        if (
            order_start_time
            and order_end_time
            and expected_validations == len(completed_validations)
        ):
            total_time = (order_end_time - order_start_time).total_seconds()
            order_completion_times.append(total_time)

    # ================= RESUMEN GLOBAL UNIFICADO =================
    summary_table = [
        ["Número total de órdenes", len(orders)],

        ["Media aserciones por orden",
         f"{statistics.mean(num_assertions_list):.2f}"],
        ["Varianza aserciones por orden",
         f"{statistics.variance(num_assertions_list) if len(num_assertions_list) > 1 else 0:.2f}"],

        ["Media aserciones TRUE por orden",
         f"{statistics.mean(true_assertions_per_order):.2f}"],
        ["Varianza aserciones TRUE por orden",
         f"{statistics.variance(true_assertions_per_order) if len(true_assertions_per_order) > 1 else 0:.2f}"],

        ["Media aserciones FALSE por orden",
         f"{statistics.mean(false_assertions_per_order):.2f}"],
        ["Varianza aserciones FALSE por orden",
         f"{statistics.variance(false_assertions_per_order) if len(false_assertions_per_order) > 1 else 0:.2f}"],

        ["Media aserciones INDEFINIDAS",
         f"{statistics.mean(undefined_assertions_per_order):.2f}"],

        ["Media aserciones DECIDIBLES (TRUE+FALSE)",
         f"{statistics.mean(decidable_assertions_per_order):.2f}"],

        ["% medio de TRUE sobre decidibles",
         f"{statistics.mean(percent_true_decidable_per_order):.2f}%"],

        ["Tiempo medio validación completa de la orden (s)",
         f"{statistics.mean(order_completion_times):.2f}" if order_completion_times else "N/A"],

        ["Varianza tiempo validación completa (s²)",
         f"{statistics.variance(order_completion_times) if len(order_completion_times) > 1 else 0:.2f}"],
    ]

    print("\n=== RESUMEN GLOBAL DE ÓRDENES Y ASERCIONES ===")
    print(tabulate(summary_table, headers=["Métrica", "Valor"], tablefmt="grid"))

    # ================= ESTADÍSTICAS POR VALIDADOR =================
    all_validators = set(
        list(approvals_per_validator.keys()) +
        list(falses_per_validator.keys()) +
        list(unknowns_per_validator.keys())
    )

    validator_table = []
    for v in all_validators:
        total = (
            len(approvals_per_validator[v]) +
            len(falses_per_validator[v]) +
            len(unknowns_per_validator[v])
        )

        t_true = len(approvals_per_validator[v])
        t_false = len(falses_per_validator[v])
        t_unknown = len(unknowns_per_validator[v])

        mean_time = (
            statistics.mean(response_times_per_validator[v])
            if response_times_per_validator[v] else 0
        )
        var_time = (
            statistics.variance(response_times_per_validator[v])
            if len(response_times_per_validator[v]) > 1 else 0
        )

        var_true = (
            statistics.variance(approvals_per_validator[v])
            if len(approvals_per_validator[v]) > 1 else 0
        )
        var_false = (
            statistics.variance(falses_per_validator[v])
            if len(falses_per_validator[v]) > 1 else 0
        )
        var_unknown = (
            statistics.variance(unknowns_per_validator[v])
            if len(unknowns_per_validator[v]) > 1 else 0
        )

        validator_table.append([
            v, total, t_true, t_false, t_unknown,
            f"{var_true:.2f}", f"{var_false:.2f}", f"{var_unknown:.2f}",
            f"{mean_time:.2f}", f"{var_time:.2f}"
        ])

    headers_validator = [
        "Validador", "Total", "True", "False", "Unknown",
        "Var True", "Var False", "Var Unknown",
        "Tiempo medio resp (s)", "Var Tiempo (s²)"
    ]

    print("\n=== ESTADÍSTICAS POR VALIDADOR ===")
    print(tabulate(validator_table, headers=headers_validator, tablefmt="grid"))


if __name__ == "__main__":
    main()
