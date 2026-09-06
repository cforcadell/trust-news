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
                }
            ],
        }
    ]


def used_reference(**overrides):
    reference = {
        "source_id": "source-1",
        "context_id": "source-1-context-1",
        "url": "https://example.test/report",
        "evidence_text": "ocho millones de personas",
        "supports": True,
    }
    reference.update(overrides)
    return reference


def test_true_verdict_keeps_only_evidence_present_in_retrieved_context(retrieved_evidence):
    result = evaluate_evidence_grounding(
        "TRUE", [used_reference()], retrieved_evidence, require_grounding=True
    )

    assert result["effective_verdict"] == "TRUE"
    assert result["evidence_used"] == [used_reference()]
    assert result["validation"]["status"] == "VERIFIED"
    assert result["validation"]["verified_count"] == 1


@pytest.mark.parametrize(
    ("reference", "code"),
    [
        (used_reference(source_id="source-invented"), "SOURCE_NOT_RETRIEVED"),
        (used_reference(url="https://attacker.test/report"), "URL_NOT_RETRIEVED"),
        (used_reference(evidence_text="dato que no aparece"), "EVIDENCE_TEXT_NOT_RETRIEVED"),
        (used_reference(evidence_text=""), "EVIDENCE_TEXT_REQUIRED"),
        (used_reference(url="javascript:alert(1)"), "URL_REQUIRED"),
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
    for reference in (
        used_reference(context_id="source-1-context-invented"),
        used_reference(chunk_id="source-1-chunk-invented"),
    ):
        result = evaluate_evidence_grounding(
            "TRUE", [reference], retrieved_evidence, require_grounding=True
        )
        assert result["effective_verdict"] == "UNKNOWN"
        assert result["evidence_used"] == []


def test_placeholder_source_cannot_support_a_documentary_verdict(retrieved_evidence):
    retrieved_evidence[0]["is_placeholder"] = True
    retrieved_evidence[0]["evidence_status"] = "ROUTING_PLACEHOLDER"

    result = evaluate_evidence_grounding(
        "TRUE", [used_reference()], retrieved_evidence, require_grounding=True
    )

    assert result["effective_verdict"] == "UNKNOWN"
    assert result["validation"]["issues"][0]["code"] == "SOURCE_IS_PLACEHOLDER"


def test_legacy_unmarked_routing_placeholder_cannot_support_a_verdict(retrieved_evidence):
    retrieved_evidence[0].pop("contexts")
    retrieved_evidence[0]["snippet"] = (
        "Domain selected by contextual routing; configure API_KEY_PROVIDER for live snippets."
    )

    result = evaluate_evidence_grounding(
        "TRUE",
        [used_reference(evidence_text="Domain selected by contextual routing")],
        retrieved_evidence,
        require_grounding=True,
    )

    assert result["effective_verdict"] == "UNKNOWN"
    assert result["validation"]["issues"][0]["code"] == "SOURCE_IS_PLACEHOLDER"


def test_unknown_remains_an_abstention_and_invalid_citations_are_removed(retrieved_evidence):
    result = evaluate_evidence_grounding(
        "UNKNOWN",
        [used_reference(source_id="source-invented")],
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
        [used_reference(), used_reference(source_id="source-invented")],
        retrieved_evidence,
        require_grounding=True,
    )

    assert result["effective_verdict"] == "TRUE"
    assert result["evidence_used"] == [used_reference()]
    assert result["validation"]["status"] == "PARTIALLY_VERIFIED"
    assert result["validation"]["rejected_count"] == 1
