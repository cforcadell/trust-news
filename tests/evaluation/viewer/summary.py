"""Derived, read-only summaries for the benchmark viewer.

The persisted diagnostic remains the source of truth.  These helpers only
deduplicate assertion consensus and aggregate validator participation for the
high-level UI.
"""

from __future__ import annotations

from collections import defaultdict


DECISIVE = {"TRUE", "FALSE"}
ISSUE_ASSESSMENTS = {"FAIL", "PARTIAL"}


def _technical_error(validation: dict) -> bool:
    llm = validation["stages"].get("llm") or {}
    observations = llm.get("observations") or {}
    if observations.get("errors"):
        return True
    if llm.get("execution_status") == "FAILED":
        return True
    return any(check.get("code") in {"TECHNICAL_ERROR", "INVALID_RESPONSE"}
               for check in llm.get("checks", []))


def _consensus(rows: list[dict]) -> tuple[dict, str]:
    for row in rows:
        stage = row["stages"].get("consensus") or {}
        observations = stage.get("observations") or {}
        if observations:
            return observations, stage.get("assessment", "NOT_EVALUATED")
    return {}, "NOT_EVALUATED"


def _votes(rows: list[dict], consensus: dict) -> list[dict]:
    recorded = consensus.get("votes") or consensus.get("validator_votes") or []
    if recorded:
        return [{"validator_id": str(vote.get("validator_id") or vote.get("validator") or ""),
                 "verdict": vote.get("verdict") or vote.get("vote") or "UNKNOWN",
                 "weight": vote.get("weight"), "error": vote.get("error")}
                for vote in recorded]
    return [{"validator_id": row["validator_id"],
             "verdict": (row["stages"].get("llm") or {}).get("observations", {}).get(
                 "effective_verdict", "UNKNOWN"),
             "weight": None, "error": None}
            for row in rows]


def summarize_order(diagnostic: dict) -> dict:
    """Summarize one order independently of its validator count."""
    grouped = defaultdict(list)
    validator_metadata = {}
    for validation in diagnostic["validations"]:
        grouped[validation["assertion_id"]].append(validation)
        validator_metadata.setdefault(validation["validator_id"], validation.get("validator") or {})

    assertion_summaries = []
    all_validator_ids = set(validator_metadata)
    for assertion in diagnostic["order"]["assertions"]:
        assertion_id = assertion["assertion_id"]
        rows = grouped.get(assertion_id, [])
        consensus, assessment = _consensus(rows)
        votes = _votes(rows, consensus)
        all_validator_ids.update(vote["validator_id"] for vote in votes if vote["validator_id"])
        expected = consensus.get("expected_verdict")
        if expected is None:
            expected_values = [((row["stages"].get("llm") or {}).get("observations") or {}).get(
                "expected_verdict") for row in rows]
            expected = next((value for value in expected_values if value is not None), None)
        verdict = consensus.get("verdict") or consensus.get("winner")
        counts = consensus.get("counts") or {}
        assigned = consensus.get("validations_count")
        if assigned is None:
            assigned = max(len(votes), len(rows))
        responses = counts.get("responses", consensus.get("responses_count"))
        if responses is None:
            responses = len(votes)
        decisive = sum(vote["verdict"] in DECISIVE and not vote.get("error") for vote in votes)
        abstentions = counts.get("abstentions")
        if abstentions is None:
            abstentions = sum(vote["verdict"] == "UNKNOWN" and not vote.get("error") for vote in votes)
        errors = counts.get("errors", consensus.get("errors_count"))
        if errors is None:
            errors = sum(bool(vote.get("error")) for vote in votes)
        errors = max(errors, sum(_technical_error(row) for row in rows))
        contradictions = sum(expected in DECISIVE and vote["verdict"] in DECISIVE
                             and vote["verdict"] != expected for vote in votes)
        achieved = assessment == "PASS"
        stage_issues = sum(stage.get("assessment") in ISSUE_ASSESSMENTS
                           for row in rows for key, stage in row["stages"].items()
                           if key != "consensus")
        degraded = bool(abstentions or errors or contradictions or stage_issues)
        assertion_summaries.append({
            "assertion_id": assertion_id, "text": assertion.get("text", ""),
            "case_id": assertion.get("expected_case_id"), "expected_verdict": expected,
            "consensus_verdict": verdict, "consensus_assessment": assessment,
            "decision_status": consensus.get("decision_status"),
            "reason_code": consensus.get("reason_code"), "assigned": assigned,
            "responses": responses, "decisive": decisive, "abstentions": abstentions,
            "errors": errors, "contradictions": contradictions,
            "decisive_coverage": (consensus.get("distribution") or {}).get("decisive_coverage"),
            "minimum_coverage": (consensus.get("consensus_policy") or {}).get(
                "min_decisive_coverage"),
            "achieved": achieved, "degraded": degraded,
            "rescued_by_consensus": achieved and assigned > 1 and bool(
                abstentions or errors or contradictions),
            "votes": votes,
        })

    total = len(assertion_summaries)
    achieved = sum(item["achieved"] for item in assertion_summaries)
    evaluated = sum(item["consensus_assessment"] not in {"NOT_EVALUATED", "SKIPPED"}
                    for item in assertion_summaries)
    if not total or not evaluated:
        outcome = "NOT_EVALUATED"
    elif achieved == total:
        outcome = "ACHIEVED"
    elif achieved:
        outcome = "PARTIALLY_ACHIEVED"
    elif any(item["consensus_assessment"] == "FAIL" for item in assertion_summaries):
        outcome = "NOT_ACHIEVED"
    else:
        outcome = "UNRESOLVED"

    technical_errors = sum(item["errors"] for item in assertion_summaries)
    degraded = any(item["degraded"] for item in assertion_summaries)
    health = "FAILED" if outcome in {"NOT_EVALUATED", "UNRESOLVED"} and technical_errors else (
        "DEGRADED" if degraded else "HEALTHY")

    validator_summaries = []
    for validator_id in sorted(all_validator_ids):
        rows = [row for row in diagnostic["validations"] if row["validator_id"] == validator_id]
        vote_rows = [item for assertion in assertion_summaries for item in assertion["votes"]
                     if item["validator_id"] == validator_id]
        decisive = sum(item["verdict"] in DECISIVE and not item.get("error") for item in vote_rows)
        abstentions = sum(item["verdict"] == "UNKNOWN" and not item.get("error") for item in vote_rows)
        errors = max(sum(bool(item.get("error")) for item in vote_rows),
                     sum(_technical_error(row) for row in rows))
        stage_issues = sum(stage.get("assessment") in ISSUE_ASSESSMENTS
                           for row in rows for key, stage in row["stages"].items()
                           if key != "consensus")
        expected_matches = 0
        contradictions = 0
        for assertion in assertion_summaries:
            expected = assertion["expected_verdict"]
            for vote in assertion["votes"]:
                if vote["validator_id"] != validator_id or vote["verdict"] not in DECISIVE:
                    continue
                expected_matches += expected in DECISIVE and vote["verdict"] == expected
                contradictions += expected in DECISIVE and vote["verdict"] != expected
        validator_summaries.append({
            "validator_id": validator_id, "metadata": validator_metadata.get(validator_id, {}),
            "assigned_assertions": len(vote_rows) or len(rows), "responses": len(vote_rows),
            "decisive": decisive, "expected_matches": expected_matches,
            "abstentions": abstentions, "contradictions": contradictions, "errors": errors,
            "stage_issues": stage_issues,
            "health": "FAILED" if errors else (
                "DEGRADED" if abstentions or contradictions or stage_issues else "HEALTHY"),
        })

    return {
        "outcome": outcome, "health": health, "assertions_total": total,
        "assertions_evaluated": evaluated, "assertions_achieved": achieved,
        "validators_observed": len(all_validator_ids),
        "assigned_votes": sum(item["assigned"] for item in assertion_summaries),
        "responses": sum(item["responses"] for item in assertion_summaries),
        "decisive_votes": sum(item["decisive"] for item in assertion_summaries),
        "abstentions": sum(item["abstentions"] for item in assertion_summaries),
        "contradictions": sum(item["contradictions"] for item in assertion_summaries),
        "technical_errors": technical_errors,
        "consensus_rescues": sum(item["rescued_by_consensus"] for item in assertion_summaries),
        "assertions": assertion_summaries, "validators": validator_summaries,
        "roster_source": "observed",
    }


def summarize_campaign(order_summaries: list[dict]) -> dict:
    """Aggregate order summaries without counting validator runs as cases."""
    return {
        "orders_total": len(order_summaries),
        "orders_achieved": sum(item["outcome"] == "ACHIEVED" for item in order_summaries),
        "orders_degraded": sum(item["health"] == "DEGRADED" for item in order_summaries),
        "orders_failed": sum(item["health"] == "FAILED" for item in order_summaries),
        "assertions_total": sum(item["assertions_total"] for item in order_summaries),
        "assertions_achieved": sum(item["assertions_achieved"] for item in order_summaries),
        "assigned_votes": sum(item["assigned_votes"] for item in order_summaries),
        "decisive_votes": sum(item["decisive_votes"] for item in order_summaries),
        "abstentions": sum(item["abstentions"] for item in order_summaries),
        "contradictions": sum(item["contradictions"] for item in order_summaries),
        "technical_errors": sum(item["technical_errors"] for item in order_summaries),
        "consensus_rescues": sum(item["consensus_rescues"] for item in order_summaries),
    }
