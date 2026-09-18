import pytest
from pydantic import ValidationError

from common.models.protocol_models import (
    AssertionsDocumentV2,
    EnrichedAssertion,
    SourceDocumentStorage,
    build_assertion_validation_payload_v2,
    build_assertions_document_v2,
)


def sample_assertion():
    return {
        "assertion_id": 1,
        "assertion_index": 0,
        "text": "El paro en Espana bajo al 11,8% en 2024.",
        "categoryId": 1,
        "topic_code": "EMPLOYMENT",
        "evidence_kind": "STATISTICAL_DATA",
        "taxonomy_version": "routing-taxonomy-v1",
        "context": {
            "locations": [{"name": "Espana", "scope": "COUNTRY", "country_code": "ES", "origin": "explicit", "confidence": 0.98}],
            "entities": [{"name": "INE", "type": "GOVERNMENT_BODY", "role": "AUTHORITY", "origin": "inferred", "confidence": 0.75}],
            "temporal_context": [{"value": "2024", "type": "YEAR", "origin": "explicit", "confidence": 0.95}],
            "language": "es",
            "jurisdiction": {"scope": "COUNTRY", "country_code": "ES"},
        },
        "search_hints": {"search_keywords": ["paro", "Espana", "2024"], "suggested_queries": ["paro Espana 2024"]},
        "context_confidence": {"location": 0.98, "entities": 0.75, "temporal": 0.95},
    }


def test_assertions_document_v2_rejects_wrong_version_and_operational_id():
    with pytest.raises(ValidationError):
        AssertionsDocumentV2(post={"original_text": "x"}, assertions=[sample_assertion()])
    with pytest.raises(ValidationError):
        AssertionsDocumentV2(schema_version="legacy", post={"original_text": "x"}, assertions=[sample_assertion()])
    with pytest.raises(ValidationError):
        AssertionsDocumentV2(
            schema_version="assertions-document-v2", order_id="internal",
            post={"original_text": "x"}, assertions=[sample_assertion()],
        )

    invalid_order = sample_assertion()
    invalid_order["assertion_id"] = 2
    invalid_order["assertion_index"] = 1
    with pytest.raises(ValidationError):
        AssertionsDocumentV2(
            schema_version="assertions-document-v2",
            post={"original_text": "x"}, assertions=[invalid_order],
        )


def test_protocol_uses_normalized_taxonomy_and_chain_projection():
    doc = build_assertions_document_v2(
        text="Texto", assertions=[sample_assertion()], mode="BLOCKCHAIN", provider="test",
        source_url="https://example.test/news", source_domain="example.test",
    )
    dumped = doc.model_dump(mode="json")
    assert "order_id" not in dumped
    assert dumped["assertions"][0]["topic_code"] == "EMPLOYMENT"
    assert dumped["assertions"][0]["evidence_kind"] == "STATISTICAL_DATA"
    assert doc.to_chain_assertions() == [{"idAssertion": "1", "text": sample_assertion()["text"], "categoryId": 1}]


def test_document_builder_reindexes_filtered_assertions():
    assertion = sample_assertion()
    assertion["assertion_id"] = 7
    assertion["assertion_index"] = 6
    document = build_assertions_document_v2(text="Texto", assertions=[assertion], mode="LIGHT")
    assert document.assertions[0].assertion_id == 1
    assert document.assertions[0].assertion_index == 0


def test_validation_payload_propagates_known_origin_and_always_has_origin_object():
    doc = build_assertions_document_v2(text="Texto", assertions=[sample_assertion()], mode="LIGHT")
    light = build_assertion_validation_payload_v2(
        mode="LIGHT", assertion=doc.assertions[0], storage=SourceDocumentStorage.INLINE,
        order_id="order-1", origin_domain="example.test",
    )
    assert light.origin_document.domain == "example.test"
    assert light.correlation.order_id == "order-1"

    unknown_origin = build_assertion_validation_payload_v2(
        mode="BLOCKCHAIN", assertion=doc.assertions[0], storage=SourceDocumentStorage.IPFS, cid="QmCID",
    )
    assert unknown_origin.origin_document.url is None
    assert unknown_origin.origin_document.domain is None

    without_version = unknown_origin.model_dump(mode="json")
    del without_version["schema_version"]
    with pytest.raises(ValidationError):
        type(unknown_origin)(**without_version)


def test_protocol_normalizes_source_and_origin_domains():
    doc = build_assertions_document_v2(
        text="Texto", assertions=[sample_assertion()], mode="LIGHT",
        source_domain="HTTPS://WWW.Example.Test:443/news",
    )
    assert doc.post.source_domain == "example.test"
    payload = build_assertion_validation_payload_v2(
        mode="LIGHT", assertion=doc.assertions[0], storage=SourceDocumentStorage.INLINE,
        origin_domain="www.Example.Test:443",
    )
    assert payload.origin_document.domain == "example.test"


def test_free_taxonomy_and_legacy_context_are_rejected():
    legacy = sample_assertion()
    legacy["subcategory"] = "FREE_TEXT"
    with pytest.raises(ValidationError):
        EnrichedAssertion(**legacy)

    invalid_topic = sample_assertion()
    invalid_topic["topic_code"] = "MODEL_INVENTED_TOPIC"
    with pytest.raises(ValidationError):
        EnrichedAssertion(**invalid_topic)

    invalid_context = sample_assertion()
    invalid_context["context"]["jurisdiction"] = "national"
    with pytest.raises(ValidationError):
        EnrichedAssertion(**invalid_context)


def test_topic_must_be_compatible_with_chain_category():
    invalid = sample_assertion()
    invalid["categoryId"] = 2
    with pytest.raises(ValidationError):
        EnrichedAssertion(**invalid)


def test_categories_remain_strict_blockchain_ids():
    for invalid in ("1", 1.0, True, 0, 11):
        assertion = sample_assertion()
        assertion["categoryId"] = invalid
        with pytest.raises(ValidationError):
            EnrichedAssertion(**assertion)
