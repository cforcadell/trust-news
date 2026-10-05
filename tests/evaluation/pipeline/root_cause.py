"""Conservative deterministic attribution. Missing observations remain unknown."""


def successful(row):
    m = row.get("metrics", {})
    return (not row.get("errors") and m.get("validation", {}).get("correct") is True
            and m.get("grounding", {}).get("status") in {"GROUNDING_PASS", "NOT_EVALUATED"}
            and m.get("handoff", {}).get("status") != "HANDOFF_EVIDENCE_MISMATCH")


def diagnose(row, counterfactuals=()):
    m = row["metrics"]
    result = lambda code, basis: {"code": code, "basis": basis}
    if m["handoff"]["status"] == "HANDOFF_EVIDENCE_MISMATCH":
        return result("HANDOFF_EVIDENCE_MISMATCH", "Recorded boundary hashes differ")
    if m["extraction"]["status"] == "EXTRACTION_ERROR":
        return result("EXTRACTION_ERROR", "Deterministic required_terms/category match failed")
    if m["validation"]["status"] == "INVALID_RESPONSE":
        return result("LLM_INVALID_RESPONSE", "Production response contract rejected the response")
    if m["grounding"]["status"] in {"LLM_CITATION_ERROR", "GROUNDING_ERROR"}:
        return result(m["grounding"]["status"], "Production grounding audit")
    if row.get("errors"):
        return result("TECHNICAL_ERROR", "Execution error; see stage and exception_type")
    if m.get("evidence_coherence", {}).get("status") == "VERDICT_EVIDENCE_CONTRADICTION":
        return result("VERDICT_EVIDENCE_CONTRADICTION",
                      "Delivered citable evidence supports an explicitly annotated approximate value, but verdict is FALSE")
    if successful(row) and m["consensus"]["status"] != "CONSENSUS_ERROR":
        return result(None, "No observed decision failure")
    if successful(row) and m["consensus"]["status"] == "CONSENSUS_ERROR":
        return result("CONSENSUS_ERROR", "Correct validator response; incorrect aggregate verdict")
    # Never compare different assertion texts, validators, temperatures or templates.
    comparable = [c for c in counterfactuals if c.get("case_id") == row.get("case_id")
                  and c.get("dataset_id") == row.get("dataset_id")
                  and c.get("provenance", {}).get("repetition") == row.get("provenance", {}).get("repetition")
                  and c.get("assertion") == row.get("assertion") and c.get("validator") == row.get("validator")
                  and c.get("validator_input", {}).get("prompt_template_hash") == row.get("validator_input", {}).get("prompt_template_hash")]
    if row["execution_mode"] != "FULL_PIPELINE":
        comparable = []
    domains = next((c for c in comparable if c["execution_mode"] == "GOLD_DOMAINS"), None)
    gold = next((c for c in comparable if c["execution_mode"] == "GOLD_EVIDENCE"), None)
    route = m["routing"]
    retrieval = m["retrieval"]
    if domains and successful(domains):
        return result("ROUTER_NO_SOURCE" if route.get("source_count") == 0 else "ROUTER_WRONG_SOURCE",
                      "Same assertion/config succeeds with GOLD_DOMAINS; single-run counterfactual")
    if route.get("source_count") == 0 and row["execution_mode"] == "FULL_PIPELINE":
        return result("ROUTER_NO_SOURCE", "Router returned no sources")
    if gold and successful(gold) and domains and not successful(domains) and not domains.get("errors"):
        return result("RETRIEVAL_NO_RESULT" if retrieval["result_count"] == 0 else "RETRIEVAL_LOW_RECALL",
                      "GOLD_DOMAINS fails; GOLD_EVIDENCE succeeds (single-run counterfactual)")
    if row["execution_mode"] not in {"GOLD_EVIDENCE", "VALIDATOR_REPLAY"}:
        if route.get("acceptable_domain_found") is False:
            return result("ROUTER_WRONG_SOURCE", "No dataset acceptable domain selected")
        if row.get("retrieval", {}).get("status") == "COMPLETED":
            if retrieval["result_count"] == 0:
                return result("RETRIEVAL_NO_RESULT", "Search returned no evidence")
            if retrieval["failed_source_count"] and not retrieval["contexts_count"]:
                return result("RETRIEVAL_FETCH_ERROR", "Failed downloads and no citable context")
        if gold:
            gold_cause = diagnose(gold)
            if gold_cause["code"] in {"LLM_WRONG_VERDICT", "LLM_UNNECESSARY_ABSTENTION"}:
                return result(gold_cause["code"], "Same configuration also fails on annotated GOLD_EVIDENCE")
        return result("UNDETERMINED", "Need sufficient gold evidence or comparable counterfactuals")
    if m["validation"]["status"] == "UNNECESSARY_ABSTENTION":
        return result("LLM_UNNECESSARY_ABSTENTION", "Annotated decisive gold evidence, but UNKNOWN")
    if m["validation"]["status"] == "WRONG_VERDICT":
        # Empty/neutral evidence cannot justify assigning a decisive failure to the LLM.
        if row["expected"]["expected_verdict"] == "UNKNOWN" or m["validation"].get("gold_supports_expected"):
            return result("LLM_WRONG_VERDICT", "Wrong verdict with annotated frozen evidence")
    return result("UNDETERMINED", "Insufficient observations for attribution")
