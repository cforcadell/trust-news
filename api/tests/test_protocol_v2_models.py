import pytest
from pydantic import ValidationError

from common.models.async_models import Assertion
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
        "text": "El paro en España bajó al 11,8% en 2024.",
        "categoryId": 1,
        "subcategory": "EMPLOYMENT",
        "context": {
            "locations": [{"name": "España", "type": "country", "country_code": "ES", "origin": "explicit", "confidence": 0.98}],
            "entities": [{"name": "INE", "type": "statistics_institute", "role": "potential_source", "origin": "inferred", "confidence": 0.75}],
            "temporal_context": [{"value": "2024", "type": "year", "origin": "explicit", "confidence": 0.95}],
            "language": "es",
            "jurisdiction": "national",
        },
        "search_hints": {
            "preferred_source_types": ["statistics", "official"],
            "search_keywords": ["paro", "España", "2024"],
            "suggested_queries": ["\"paro\" \"España\" \"2024\""],
        },
        "context_confidence": {"location": 0.98, "entities": 0.75, "temporal": 0.95},
    }


def test_assertions_document_v2_rejects_legacy_and_order_id():
    with pytest.raises(ValidationError):
        AssertionsDocumentV2(schema_version="legacy", post={"original_text": "x"}, assertions=[sample_assertion()])
    with pytest.raises(ValidationError):
        AssertionsDocumentV2(schema_version="assertions-document-v2", order_id="internal", post={"original_text": "x"}, assertions=[sample_assertion()])


def test_blockchain_protocol_document_has_no_order_id_and_maps_chain_assertions():
    doc = build_assertions_document_v2(text="Texto", assertions=[sample_assertion()], mode="BLOCKCHAIN", provider="test")
    dumped = doc.model_dump(mode="json")
    assert dumped["schema_version"] == "assertions-document-v2"
    assert "order_id" not in dumped
    assert doc.assertions[0].subcategory == "EMPLOYMENT"
    assert doc.to_chain_assertions()[0]["categoryId"] == 1


def test_validation_payload_v2_light_and_blockchain_share_assertion_shape():
    doc = build_assertions_document_v2(text="Texto", assertions=[sample_assertion()], mode="LIGHT", provider="test")
    light = build_assertion_validation_payload_v2(
        mode="LIGHT", assertion=doc.assertions[0], storage=SourceDocumentStorage.INLINE, order_id="order-1"
    )
    blockchain = build_assertion_validation_payload_v2(
        mode="BLOCKCHAIN", assertion=doc.assertions[0], storage=SourceDocumentStorage.IPFS, post_id=123, cid="QmCID"
    )
    assert light.schema_version == "assertion-validation-payload-v2"
    assert light.correlation.order_id == "order-1"
    assert blockchain.correlation.order_id is None
    assert blockchain.source_document.cid == "QmCID"
    assert light.assertion.model_dump() == blockchain.assertion.model_dump()


def test_assertion_context_accepts_legacy_string_lists_from_llms():
    assertion = Assertion(
        assertion_id=1,
        assertion_index=0,
        text="Catalunya tiene mas de 7 millones de habitantes en 2026.",
        categoryId=10,
        context={
            "locations": ["Catalunya"],
            "entities": ["Union Europea"],
            "temporal_context": ["2026"],
            "language": "es",
            "jurisdiction": "regional",
        },
    )

    assert assertion.context.locations[0].name == "Catalunya"
    assert assertion.context.locations[0].origin == "explicit"
    assert assertion.context.entities[0].name == "Union Europea"
    assert assertion.context.temporal_context[0].value == "2026"
    assert assertion.to_enriched().context.temporal_context[0].value == "2026"


def test_categories_use_strict_blockchain_ids():
    assertion = EnrichedAssertion(assertion_id=1, assertion_index=0, text="x", categoryId=3)
    assert assertion.categoryId == 3
    assert assertion.to_chain_assertion()["categoryId"] == 3

    for invalid in ("3", 3.0, True, 0, 11, "POLÍTICA"):
        with pytest.raises(ValidationError):
            EnrichedAssertion(assertion_id=1, assertion_index=0, text="x", categoryId=invalid)


def test_legacy_category_field_is_rejected():
    with pytest.raises(ValidationError):
        EnrichedAssertion(assertion_id=1, assertion_index=0, text="x", categoryId=3, category="POLÍTICA")
