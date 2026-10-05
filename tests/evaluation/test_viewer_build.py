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
    assert {item["type"] for item in generation["checks"]} == {"warning"}
    assert generation["assessment"] == "PARTIAL"


def test_missing_generation_trace_does_not_invent_attempts():
    dataset = {"id": "example", "news": "Texto", "assertions": [{"id": "one", "text": "Texto"}]}
    order = {"order_id": "order-2", "status": "VALIDATED", "text": "Texto",
             "assertions": [{"idAssertion": "1", "text": "Texto"}]}
    snapshot = build_order_diagnostic(dataset, order, [], campaign_id="campaign-1",
                                      repetition=1, parent_run_id="parent-2")
    assert snapshot["order"]["generation"]["observations"]["structured_attempts"] is None
    assert snapshot["order"]["generation"]["observations"]["repair_used"] is None


def test_generation_accepts_annotated_approximate_numeric_equivalence():
    dataset = {"id": "example", "news": "Aproximadamente una cuarta parte.", "assertions": [
        {"id": "share", "text": "La cuota fue 24,5 %.", "required_terms": ["cuota"],
         "approximate_values": [{"value": 24.5, "tolerance": 0.5,
                                 "aliases": ["una cuarta parte"]}]}]}
    order = {"order_id": "order", "status": "COMPLETED",
             "assertions": [{"idAssertion": "1", "text": "La cuota fue una cuarta parte."}]}
    snapshot = build_order_diagnostic(dataset, order, [], campaign_id="campaign",
                                      repetition=1, parent_run_id="parent")
    codes = {check["code"] for check in snapshot["order"]["generation"]["checks"]}
    assert "NUMBER_OR_DATE_MISSING" not in codes


def test_unscored_validation_remains_visible_without_wrong_verdict_label():
    from evaluation.viewer.build import _validation_stages

    stages = _validation_stages({
        "provenance": {"scoring_eligible": False},
        "expected": {"expected_verdict": "UNKNOWN"},
        "validator_output": {"effective_verdict": "TRUE"},
        "router": {"status": "NOT_EVALUATED"}, "retrieval": {"status": "NOT_EVALUATED"},
        "consensus": {"status": "COMPLETED", "verdict": "TRUE"},
    })
    assert stages["llm"]["assessment"] == "NOT_EVALUATED"
    assert stages["llm"]["checks"][0]["code"] == "UNSCORED_VALIDATION"
    assert stages["consensus"]["assessment"] == "NOT_EVALUATED"


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
    assert stages["router"]["assessment"] == "PARTIAL"
    assert stages["router"]["observations"]["acceptable_domains"] == ["ine.es"]
    assert stages["router"]["observations"]["matching_domains"] == []
    assert stages["router"]["observations"]["expected_domain_matches"] == [
        {"domain": "ine.es", "matching_selected_domains": []}]
    assert stages["router"]["checks"][0]["code"] == "ROUTER_EXPECTED_DOMAIN_MISSING"
    assert stages["router"]["checks"][0]["type"] == "warning"
    assert "se esperaba ine.es" in stages["router"]["checks"][0]["detail"]
    assert "example.org" in stages["router"]["checks"][0]["detail"]


def test_external_rag_strategy_marks_router_as_intentionally_skipped():
    from evaluation.viewer.build import _validation_stages

    stages = _validation_stages({
        "validator": {"evidence_search_strategy": "EXT_ONLY_OFFICIAL"},
        "expected": {"expected_verdict": "TRUE", "acceptable_domains": ["ine.es"]},
        "router": {"status": "NOT_EVALUATED"},
        "retrieval": {"status": "COMPLETED", "evidences": []},
        "consensus": {"status": "NOT_EVALUATED"},
    })

    router = stages["router"]
    assert router["execution_status"] == "SKIPPED"
    assert router["assessment"] == "SKIPPED"
    assert router["observations"]["skip_reason"] == "EXTERNAL_EVIDENCE_STRATEGY"
    assert "EXT_ONLY_OFFICIAL" in router["missing_reason"]


def test_snapshot_promotes_public_validator_metadata():
    dataset = {"id": "example", "news": "Texto", "assertions": [
        {"id": "one", "text": "Texto", "expected_verdict": "TRUE"}]}
    order = {"order_id": "order-metadata", "status": "VALIDATED", "text": "Texto",
             "assertions": [{"idAssertion": "1", "text": "Texto"}]}
    row = {"run_id": "run-1", "assertion_id": "1",
           "validator": {"id": "validator-1", "validator_type": "RAG_EVIDENCE_VALIDATION",
                         "provider": "openrouter", "model": "model-a", "config_version": 3,
                         "evidence_search_strategy": "LOCAL"},
           "expected": {"expected_verdict": "TRUE"}, "router": {"status": "NOT_EVALUATED"},
           "retrieval": {"status": "NOT_EVALUATED"}, "consensus": {"status": "NOT_EVALUATED"}}

    snapshot = build_order_diagnostic(dataset, order, [row], campaign_id="campaign-1",
                                      repetition=1, parent_run_id="parent-1")

    assert snapshot["validations"][0]["validator"] == {
        "validator_type": "RAG_EVIDENCE_VALIDATION", "provider": "openrouter",
        "model": "model-a", "config_version": 3, "temperature": None,
        "evidence_search_strategy": "LOCAL"}


def test_viewer_marks_missing_route_or_citable_source_as_error():
    from evaluation.viewer.build import _validation_stages

    route_missing = _validation_stages({
        "expected": {"expected_verdict": "UNKNOWN", "acceptable_domains": ["ine.es"]},
        "metrics": {"routing": {"status": "FAIL"}},
        "router": {"status": "COMPLETED", "sources": []},
        "retrieval": {"status": "COMPLETED", "evidences": [{"fetch_status": "empty_text", "contexts": []}]},
        "consensus": {"status": "NOT_EVALUATED"},
    })
    assert route_missing["router"]["checks"][0]["type"] == "error"
    retrieval_check = route_missing["evidence_search"]["checks"][0]
    assert retrieval_check["code"] == "NO_CITABLE_EVIDENCE"
    assert retrieval_check["type"] == "error"
    assert "empty_text" in retrieval_check["detail"]
    assert "0 contextos" in retrieval_check["detail"]


def test_failure_details_explain_observed_cause_and_expected_value():
    from evaluation.viewer.build import _validation_stages

    stages = _validation_stages({
        "expected": {"expected_verdict": "TRUE"},
        "router": {"status": "SKIPPED"},
        "retrieval": {"status": "INJECTED", "evidences": []},
        "validator_input": {"retrieval_evidence_bundle_hash": "retrieved", "validator_input_evidence_bundle_hash": "delivered"},
        "validator_output": {"resultado": "FALSE", "effective_verdict": "FALSE"},
        "consensus": {"status": "COMPLETED", "verdict": "FALSE", "reason_code": "MAJORITY_FALSE",
                      "distribution": {"FALSE": 2, "TRUE": 1}},
    })
    assert "retrieved" in stages["handoff"]["checks"][0]["detail"]
    assert "delivered" in stages["handoff"]["checks"][0]["detail"]
    assert "se esperaba 'TRUE'" in stages["llm"]["checks"][0]["detail"]
    assert "produjo 'FALSE'" in stages["llm"]["checks"][0]["detail"]
    assert "MAJORITY_FALSE" in stages["consensus"]["checks"][0]["detail"]


def test_generation_failure_explains_the_invalid_jurisdiction_fields():
    from evaluation.viewer.build import _generation

    dataset = {"assertions": [{"id": "expected-1", "text": "Una afirmación"}]}
    order = {
        "assertions_error": "Invalid structured LLM response",
        "generation_evaluation_trace": {
            "provider": "openrouter",
            "model": "example",
            "temperature": 0.1,
            "status": "FAILED",
            "error_type": "LLMResponseError",
            "validation_issues": [{
                "code": "JURISDICTION_CONTRACT_MISMATCH",
                "assertion_index": 0,
                "assertion_id": "generated-1",
                "location": "assertions.0.context.jurisdiction",
                "message": "SUPRANATIONAL jurisdiction requires only jurisdiction_code",
                "jurisdiction_scope": "SUPRANATIONAL",
                "present_jurisdiction_fields": ["country_code", "jurisdiction_code"],
            }],
        },
    }

    stage = _generation(dataset, order, [])

    detail = next(check["detail"] for check in stage["checks"] if check["code"] == "GENERATION_ERROR")
    assert "generated-1" in detail
    assert "scope=SUPRANATIONAL" in detail
    assert "country_code, jurisdiction_code" in detail
    assert "requires only jurisdiction_code" in detail
