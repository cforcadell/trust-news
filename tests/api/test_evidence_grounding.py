import pytest

from common.utils.evidence import evaluate_evidence_grounding


@pytest.fixture
def retrieved_evidence():
    return [
        {
            "source_id": "source-1",
            "url": "https://example.test/report/",
            "contexts": [
                {
                    "context_id": "source-1-context-1",
                    "selected_chunk_id": "source-1-chunk-2",
                    "included_chunk_ids": ["source-1-chunk-1", "source-1-chunk-2"],
                    "text": "La población registrada en 2025 fue de ocho millones de personas.",
                    "text_sha256": "canonical-hash",
                    "citation_eligible": True,
                }
            ],
        }
    ]


def used_reference(**overrides):
    reference = {
        "context_id": "source-1-context-1",
        "supports": True,
        "reason": "El contexto contiene la cifra.",
    }
    reference.update(overrides)
    return reference


def canonical_reference(**overrides):
    reference = {
        "source_id": "source-1",
        "context_id": "source-1-context-1",
        "chunk_id": "source-1-chunk-2",
        "url": "https://example.test/report/",
        "title": None,
        "supports": True,
        "evidence_text": "La población registrada en 2025 fue de ocho millones de personas.",
        "evidence_text_sha256": "canonical-hash",
        "reason": "El contexto contiene la cifra.",
    }
    reference.update(overrides)
    return reference


def test_true_verdict_keeps_only_evidence_present_in_retrieved_context(retrieved_evidence):
    result = evaluate_evidence_grounding(
        "TRUE", [used_reference()], retrieved_evidence, require_grounding=True
    )

    assert result["effective_verdict"] == "TRUE"
    assert result["evidence_used"] == [canonical_reference()]
    assert result["validation"]["status"] == "VERIFIED"
    assert result["validation"]["verified_count"] == 1


@pytest.mark.parametrize(
    ("reference", "code"),
    [
        (used_reference(context_id="source-1-context-invented"), "CONTEXT_NOT_RETRIEVED"),
        ({"supports": True}, "CONTEXT_ID_REQUIRED"),
        (used_reference(supports="true"), "SUPPORTS_REQUIRED"),
    ],
)
def test_invented_or_incomplete_evidence_is_rejected_and_verdict_abstains(
    retrieved_evidence, reference, code
):
    result = evaluate_evidence_grounding(
        "TRUE", [reference], retrieved_evidence, require_grounding=True
    )

    assert result["effective_verdict"] == "UNKNOWN"
    assert result["evidence_used"] == []
    assert result["validation"]["status"] == "UNSUPPORTED"
    assert code in {issue["code"] for issue in result["validation"]["issues"]}
    assert "VERDICT_WITHOUT_SUPPORT" in {
        issue["code"] for issue in result["validation"]["issues"]
    }


def test_missing_evidence_is_not_replaced_with_every_retrieved_source(retrieved_evidence):
    result = evaluate_evidence_grounding(
        "TRUE", [], retrieved_evidence, require_grounding=True
    )

    assert result["effective_verdict"] == "UNKNOWN"
    assert result["evidence_used"] == []
    assert result["validation"]["claimed_count"] == 0
    assert result["validation"]["verified_count"] == 0


def test_false_verdict_requires_a_verified_contradicting_reference(retrieved_evidence):
    supporting = evaluate_evidence_grounding(
        "FALSE", [used_reference(supports=True)], retrieved_evidence, require_grounding=True
    )
    contradicting = evaluate_evidence_grounding(
        "FALSE", [used_reference(supports=False)], retrieved_evidence, require_grounding=True
    )

    assert supporting["effective_verdict"] == "UNKNOWN"
    assert contradicting["effective_verdict"] == "FALSE"
    assert contradicting["validation"]["status"] == "VERIFIED"


def test_wrong_context_or_chunk_cannot_be_used(retrieved_evidence):
    result = evaluate_evidence_grounding(
        "TRUE", [used_reference(context_id="source-1-context-invented")], retrieved_evidence,
        require_grounding=True,
    )
    assert result["effective_verdict"] == "UNKNOWN"
    assert result["evidence_used"] == []


def test_context_without_server_citation_flag_cannot_be_used(retrieved_evidence):
    retrieved_evidence[0]["contexts"][0]["citation_eligible"] = False
    result = evaluate_evidence_grounding(
        "TRUE", [used_reference()], retrieved_evidence, require_grounding=True
    )

    assert result["effective_verdict"] == "UNKNOWN"
    assert result["evidence_used"] == []
    assert "CONTEXT_NOT_CITABLE" in {
        issue["code"] for issue in result["validation"]["issues"]
    }


def test_model_cannot_override_canonical_url_or_text(retrieved_evidence):
    claimed = used_reference(
        source_id="source-invented",
        url="https://attacker.test/report",
        evidence_text="Texto inventado",
        title="Título inventado",
    )
    result = evaluate_evidence_grounding("TRUE", [claimed], retrieved_evidence, require_grounding=True)

    assert result["effective_verdict"] == "TRUE"
    assert result["evidence_used"] == [canonical_reference()]


def test_original_document_cannot_be_decisive_evidence(retrieved_evidence):
    retrieved_evidence[0]["relationship_to_origin"] = "ORIGINAL"

    result = evaluate_evidence_grounding(
        "TRUE", [used_reference()], retrieved_evidence, require_grounding=True
    )

    assert result["effective_verdict"] == "UNKNOWN"
    assert result["evidence_used"] == []
    assert "SOURCE_IS_ORIGINAL_DOCUMENT" in {
        issue["code"] for issue in result["validation"]["issues"]
    }


def test_unknown_remains_an_abstention_and_invalid_citations_are_removed(retrieved_evidence):
    result = evaluate_evidence_grounding(
        "UNKNOWN",
        [used_reference(context_id="source-invented-context-1")],
        retrieved_evidence,
        require_grounding=True,
    )

    assert result["effective_verdict"] == "UNKNOWN"
    assert result["evidence_used"] == []
    assert result["validation"]["status"] == "INVALID"


def test_memory_result_is_explicitly_non_documentary(retrieved_evidence):
    result = evaluate_evidence_grounding(
        "TRUE", [used_reference()], retrieved_evidence, require_grounding=False
    )

    assert result["effective_verdict"] == "TRUE"
    assert result["evidence_used"] == []
    assert result["validation"]["status"] == "NOT_APPLICABLE"
    assert result["validation"]["basis"] == "MODEL_KNOWLEDGE"


def test_provider_search_keeps_verdict_without_claiming_documentary_verification():
    declared = [{
        "url": "https://example.test/report",
        "evidence_text": "dato declarado por el proveedor",
        "supports": True,
    }]

    result = evaluate_evidence_grounding(
        "TRUE",
        declared,
        [],
        require_grounding=False,
        non_documentary_basis="PROVIDER_SEARCH_UNVERIFIED",
    )

    assert result["effective_verdict"] == "TRUE"
    assert result["evidence_used"] == []
    assert result["validation"]["status"] == "UNVERIFIED"
    assert result["validation"]["basis"] == "PROVIDER_SEARCH_UNVERIFIED"
    assert result["validation"]["rejected_count"] == 0
    assert result["validation"]["issues"] == [
        {"code": "PROVIDER_SOURCES_NOT_SERVER_VERIFIED"}
    ]


def test_valid_reference_survives_alongside_rejected_invented_reference(retrieved_evidence):
    result = evaluate_evidence_grounding(
        "TRUE",
        [used_reference(), used_reference(context_id="source-invented-context-1")],
        retrieved_evidence,
        require_grounding=True,
    )

    assert result["effective_verdict"] == "TRUE"
    assert result["evidence_used"] == [canonical_reference()]
    assert result["validation"]["status"] == "PARTIALLY_VERIFIED"
    assert result["validation"]["rejected_count"] == 1
