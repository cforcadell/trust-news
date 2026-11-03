"""Reuse the production consensus policy for explicitly selected RAG validators."""


def attach_consensus(rows):
    from common.utils.scoring import calculate_assertion_result, validation_weight_snapshot
    groups = {}
    for row in rows:
        if row["execution_mode"] == "FULL_PIPELINE" and row.get("provenance", {}).get("origin") != "persisted_order":
            key = (row.get("dataset_id"), row["case_id"], row.get("provenance", {}).get("repetition"))
            groups.setdefault(key, []).append(row)
    for items in groups.values():
        if len(items) < 2:
            continue
        validators = {}
        for row in items:
            validators[row["validator"]["id"]] = {
                "execution_status": "ERROR" if row["errors"] else "COMPLETED",
                "approval": row["validator_output"].get("effective_verdict", "UNKNOWN"),
                "evidence_used": row["grounding"].get("evidence_used", []),
                "evidence_validation": row["grounding"].get("validation"),
                **validation_weight_snapshot({"validator_type": 3, "reputation": 1.0}),
            }
        consensus = calculate_assertion_result(str(items[0]["assertion_id"]), validators)
        for row in items:
            row["consensus"] = {"status": "COMPLETED", "scope": "evaluation_models_equal_reputation", **consensus}
