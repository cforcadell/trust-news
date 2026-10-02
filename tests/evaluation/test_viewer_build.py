"""A saved order keeps all generated assertions, not just matched validator rows."""

from evaluation.viewer.build import build_order_diagnostic


def test_generation_diagnosis_includes_missing_extra_and_context_loss():
    dataset = {
        "id": "example", "news": "En 2025 hubo 50 casos y no aumentaron.",
        "assertions": [
            {"id": "count", "text": "En 2025 hubo 50 casos.", "required_terms": ["50", "casos"],
             "category_ids": [10], "source_excerpt": "En 2025 hubo 50 casos",
             "expected_context": {"temporal_context": ["2025"]}},
            {"id": "trend", "text": "Los casos no aumentaron.", "required_terms": ["no", "aumentaron"]},
        ],
    }
    order = {
        "order_id": "order-1", "status": "VALIDATED", "text": dataset["news"],
        "document": {"generator": {"service": "generate-asertions", "provider": "example", "model": "model"}},
        "generation_evaluation_trace": {"provider": "example", "model": "model", "temperature": 0.1,
                                        "config_version": 1, "structured_attempts": 2,
                                        "repair_used": True, "duration_seconds": 2.5,
                                        "status": "COMPLETED", "assertion_count": 2},
        "assertions": [
            {"idAssertion": "1", "text": "Hubo 50 casos.", "categoryId": 10,
             "context": {"temporal_context": []}, "search_hints": {}},
            {"idAssertion": "2", "text": "Una afirmación sin referencia.", "categoryId": 10},
        ],
    }
    snapshot = build_order_diagnostic(dataset, order, [], campaign_id="campaign-1",
                                      repetition=1, parent_run_id="parent-1")
    generation = snapshot["order"]["generation"]
    codes = {item["code"] for item in generation["checks"]}
    assert len(snapshot["order"]["assertions"]) == 2
    assert "EXPECTED_ASSERTION_MISSING" in codes
    assert "UNMATCHED_GENERATED_ASSERTION" in codes
    assert "NUMBER_OR_DATE_MISSING" in codes
    assert "CONTEXT_TEMPORAL_CONTEXT_MISSING" in codes
    assert generation["observations"]["repair_used"] is True
    assert generation["observations"]["structured_attempts"] == 2


def test_missing_generation_trace_does_not_invent_attempts():
    dataset = {"id": "example", "news": "Texto", "assertions": [{"id": "one", "text": "Texto"}]}
    order = {"order_id": "order-2", "status": "VALIDATED", "text": "Texto",
             "assertions": [{"idAssertion": "1", "text": "Texto"}]}
    snapshot = build_order_diagnostic(dataset, order, [], campaign_id="campaign-1",
                                      repetition=1, parent_run_id="parent-2")
    assert snapshot["order"]["generation"]["observations"]["structured_attempts"] is None
    assert snapshot["order"]["generation"]["observations"]["repair_used"] is None


def test_citation_diagnosis_uses_only_contexts_delivered_to_same_validation():
    from evaluation.viewer.build import _validation_stages

    contexts = [{"context_id": "ctx-1", "text": "Texto verificable", "citation_eligible": True},
                {"context_id": "ctx-2", "text": "No citar", "citation_eligible": False}]
    row = {"validator": {"id": "v1", "model": "m"}, "expected": {"expected_verdict": "TRUE"},
           "retrieval": {"status": "COMPLETED", "evidences": [{"source_id": "source-1", "contexts": contexts}]},
           "validator_input": {"evidences": [{"source_id": "source-1", "contexts": contexts}],
                               "retrieval_evidence_bundle_hash": "equal", "validator_input_evidence_bundle_hash": "equal"},
           "validator_output": {"resultado": "TRUE", "effective_verdict": "UNKNOWN", "evidence_used": []},
           "grounding": {"validation": {"claimed_count": 3, "verified_count": 0, "rejected_count": 3,
                                        "claimed_evidence": [
                                            {"source_id": "source-9", "context_id": "ctx-1"},
                                            {"source_id": "source-1", "context_id": "ctx-9"},
                                            {"source_id": "source-1", "context_id": "ctx-2"}],
                                        "issues": [{"code": "CONTEXT_NOT_RETRIEVED"}]}},
           "consensus": {"status": "NOT_EVALUATED"}}
    stages = _validation_stages(row)
    assert stages["handoff"]["assessment"] == "PASS"
    citations = stages["citations"]
    assert citations["assessment"] == "FAIL"
    assert [item["reason"] for item in citations["observations"]["citations"]] == [
        "SOURCE_ID_NOT_DELIVERED", "CONTEXT_ID_NOT_DELIVERED", "CONTEXT_NOT_CITABLE"]
    assert stages["llm"]["observations"]["grounding"]["issues"][0]["code"] == "CONTEXT_NOT_RETRIEVED"
    assert stages["llm"]["observations"]["original_verdict"] == "TRUE"
    assert stages["llm"]["observations"]["effective_verdict"] == "UNKNOWN"


def test_original_citation_ids_and_consensus_votes_are_preserved_without_evidence_duplication():
    from evaluation.viewer.build import _validation_stages

    context = {"context_id": "ctx-1", "text": "Dato", "citation_eligible": True}
    row = {"validator": {"id": "v1", "model": "model", "provider": "example"},
           "expected": {"expected_verdict": "TRUE"},
           "retrieval": {"status": "COMPLETED", "evidences": [{"source_id": "source-1", "contexts": [context]}]},
           "validator_input": {"evidences": [{"source_id": "source-1", "contexts": [context]}]},
           "validator_output": {"resultado": "TRUE", "effective_verdict": "TRUE",
                                "evidence_used": [{"source_id": "source-1", "context_id": "ctx-1"}],
                                "evaluation_citation_trace": {"claims": [{"source_id": "invented", "context_id": "ctx-1"}]}},
           "consensus": {"status": "COMPLETED", "verdict": "TRUE", "reason_code": "ALL_DECISIVE_AGREE_TRUE",
                         "counts": {"abstentions": 0, "errors": 0},
                         "details": [{"validator": "v1", "result": "TRUE", "effective_weight": 1.5,
                                      "evidence_used": [{"evidence_text": "Large repeated text"}]}]}}
    stages = _validation_stages(row)
    assert stages["citations"]["observations"]["citations"][0]["reason"] == "SOURCE_ID_NOT_DELIVERED"
    consensus = stages["consensus"]["observations"]
    assert consensus["votes"] == [{"validator_id": "v1", "verdict": "TRUE", "weight": 1.5,
                                   "validator_type": None, "error": None, "audit_status": None}]
    assert "Large repeated text" not in str(consensus)


def test_router_reference_domains_are_kept_separate_from_selected_domains():
    from evaluation.viewer.build import _validation_stages

    stages = _validation_stages({
        "expected": {"expected_verdict": "UNKNOWN", "acceptable_domains": ["ine.es"]},
        "metrics": {"routing": {"status": "FAIL"}},
        "router": {"status": "COMPLETED", "sources": [{"domain": "example.org"}]},
        "retrieval": {"status": "SKIPPED"},
        "consensus": {"status": "NOT_EVALUATED"},
    })
    assert stages["router"]["assessment"] == "FAIL"
    assert stages["router"]["observations"]["acceptable_domains"] == ["ine.es"]
    assert stages["router"]["observations"]["matching_domains"] == []
