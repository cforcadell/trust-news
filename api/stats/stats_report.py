import csv
import json
import os
import statistics
from collections import defaultdict

OUTPUT_DIR = "output"

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

def main():
    orders = load_orders()

    times_to_validated = []
    num_assertions_list = []
    percent_valid_assertions_per_order = []

    positive_approvals_per_validator = defaultdict(list)
    zero_approval_per_validator = defaultdict(list)

    for order_id in orders:
        order = load_json(order_id, "order.json")

        assertions = order.get("assertions", [])
        validations = order.get("validations", {})
        num_assertions_list.append(len(assertions))

        valid_assertions = 0

        for assertion_id, vdict in validations.items():
            balance = 0
            for validator, vdata in vdict.items():
                approval = vdata["approval"]

                if approval == 1:
                    positive_approvals_per_validator[validator].append(1)
                    balance += 1
                elif approval == 0:
                    zero_approval_per_validator[validator].append(1)
                else:
                    positive_approvals_per_validator[validator].append(0)
                    balance -= 1

            if balance > 0:
                valid_assertions += 1

        percent_valid_assertions_per_order.append(
            (valid_assertions / len(assertions) * 100) if assertions else 0
        )

    print("\n=== ESTADÍSTICAS ===")
    print(f"Número de órdenes: {len(orders)}")
    print(f"Número medio de aserciones: {statistics.mean(num_assertions_list):.2f}")
    print(f"% medio de aserciones válidas: {statistics.mean(percent_valid_assertions_per_order):.2f}%")

    print("\nEstadísticas por validador:")
    for v in positive_approvals_per_validator:
        avg_pos = statistics.mean(positive_approvals_per_validator[v])
        zero_var = statistics.variance(zero_approval_per_validator[v]) if len(zero_approval_per_validator[v]) > 1 else 0
        print(f"  {v} - media aprobaciones=1: {avg_pos:.2f}, varianza aprobaciones=0: {zero_var:.2f}")

if __name__ == "__main__":
    main()
