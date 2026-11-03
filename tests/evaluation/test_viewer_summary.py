"""High-level viewer summaries adapt to the validators observed per order."""

from evaluation.viewer.summary import summarize_campaign, summarize_order


def _diagnostic(validator_ids, verdicts, *, assertions=1):
    assertion_rows = [{"assertion_id": str(index), "text": f"Aserción {index}",
                       "expected_case_id": f"case-{index}"}
                      for index in range(1, assertions + 1)]
    validations = []
    votes = [{"validator_id": validator_id, "verdict": verdict, "weight": 1.0,
              "error": None} for validator_id, verdict in zip(validator_ids, verdicts)]
    decisive = sum(vote["verdict"] in {"TRUE", "FALSE"} for vote in votes)
    abstentions = sum(vote["verdict"] == "UNKNOWN" for vote in votes)
    consensus = {"verdict": "TRUE", "expected_verdict": "TRUE",
                 "decision_status": "CONSENSUS", "reason_code": "TEST",
                 "validations_count": len(validator_ids), "responses_count": len(votes),
                 "counts": {"responses": len(votes), "completed": len(votes),
                            "decisive": decisive, "abstentions": abstentions, "errors": 0},
                 "distribution": {"decisive_coverage": decisive / len(votes) if votes else 0},
                 "consensus_policy": {"min_decisive_coverage": 0.5}, "votes": votes}
    for assertion in assertion_rows:
        for validator_id, verdict in zip(validator_ids, verdicts):
            validations.append({"run_id": f"{assertion['assertion_id']}-{validator_id}",
                                "assertion_id": assertion["assertion_id"],
                                "validator_id": validator_id, "validator": {},
                                "stages": {"llm": {"execution_status": "COMPLETED",
                                                    "assessment": "PASS" if verdict == "TRUE" else "NOT_EVALUATED",
                                                    "observations": {"effective_verdict": verdict,
                                                                     "expected_verdict": "TRUE",
                                                                     "errors": []}, "checks": []},
                                           "consensus": {"execution_status": "COMPLETED",
                                                         "assessment": "PASS",
                                                         "observations": consensus, "checks": []}}})
    return {"order": {"status": "VALIDATED", "assertions": assertion_rows},
            "validations": validations}


def test_summary_uses_dynamic_validator_matrix_and_deduplicates_consensus():
    summary = summarize_order(_diagnostic(["v1", "v2", "v3", "v4"],
                                          ["TRUE", "TRUE", "UNKNOWN", "FALSE"], assertions=2))

    assert summary["outcome"] == "ACHIEVED"
    assert summary["health"] == "DEGRADED"
    assert summary["validators_observed"] == 4
    assert summary["assertions_achieved"] == 2
    assert summary["assigned_votes"] == 8
    assert summary["decisive_votes"] == 6
    assert summary["abstentions"] == 2
    assert summary["contradictions"] == 2
    assert summary["consensus_rescues"] == 2
    assert len(summary["assertions"][0]["votes"]) == 4


def test_single_validator_is_not_described_as_consensus_rescue():
    summary = summarize_order(_diagnostic(["only"], ["TRUE"]))

    assert summary["outcome"] == "ACHIEVED"
    assert summary["health"] == "HEALTHY"
    assert summary["consensus_rescues"] == 0
    assert summary["validators"][0]["assigned_assertions"] == 1


def test_campaign_summary_counts_assertions_instead_of_validator_runs():
    healthy = summarize_order(_diagnostic(["v1"], ["TRUE"], assertions=2))
    degraded = summarize_order(_diagnostic(["v1", "v2"], ["TRUE", "UNKNOWN"], assertions=3))

    summary = summarize_campaign([healthy, degraded])

    assert summary["orders_total"] == 2
    assert summary["orders_achieved"] == 2
    assert summary["assertions_total"] == 5
    assert summary["assertions_achieved"] == 5
    assert summary["orders_degraded"] == 1
    assert summary["consensus_rescues"] == 3
