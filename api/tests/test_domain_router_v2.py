import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "evidence-search"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))

from app.domain_router.profiles_loader import normalize_assertion
from app.domain_router.resolver import resolve_domains
from common.models.evidence_models import EvidenceDomainProfile, EvidenceNormalizationConfig


def profile():
    return EvidenceDomainProfile.model_validate(json.loads((ROOT / "config/evidence-domain-profile-default.json").read_text()))


def configs():
    docs = json.loads((ROOT / "config/evidence-normalization-configs.json").read_text())
    return {doc["config_type"]: EvidenceNormalizationConfig.model_validate(doc) for doc in docs}


def catalunya_assertion():
    return {
        "assertion_id": 1, "text": "Catalunya supera ocho millones de habitantes.",
        "categoryId": 10, "subcategory": "demografía",
        "context": {"locations": [{"name":"Catalunya","type":"region","country_code":"es","region_code":"es-ct"}], "entities": []},
        "search_hints": {"preferred_source_types": ["Official", "estadística"]},
    }


def test_normalization_uses_canonical_subcategory_location_and_source_types():
    assertion = normalize_assertion(catalunya_assertion(), configs())
    assert assertion["subcategory"] == "DEMOGRAPHICS"
    assert assertion["context"]["locations"][0]["scope"] == "region"
    assert assertion["context"]["locations"][0]["region_code"] == "ES-CT"
    assert assertion["search_hints"]["preferred_source_types"] == ["official", "statistics"]


def test_catalunya_scoring_order():
    assertion = normalize_assertion(catalunya_assertion(), configs())
    result = resolve_domains(assertion, profile())
    scores = {item["domain"]: item["final_score"] for item in result["preferred_domains"]}
    assert scores["idescat.cat"] > scores["ine.es"] > scores["eurostat.ec.europa.eu"] > scores["reuters.com"]
    assert result["preferred_domains"][0]["matched"]["location"] == "region"


def test_subcategory_incompatible_with_blockchain_category_becomes_unknown():
    assertion = catalunya_assertion()
    assertion["categoryId"] = 3
    assert normalize_assertion(assertion, configs())["subcategory"] == "unknown"


def test_local_scoring_is_identical_for_light_and_blockchain_payloads():
    from common.models.protocol_models import AssertionValidationPayloadV2

    scores_by_mode = {}
    for mode, storage in (("LIGHT", "inline"), ("BLOCKCHAIN", "ipfs")):
        raw_assertion = catalunya_assertion()
        raw_assertion["assertion_index"] = 0
        raw_assertion["context"].update({"temporal_context": [], "language": "es", "jurisdiction": "regional"})
        raw_assertion["context_confidence"] = {"location": 1.0, "entities": 0.0, "temporal": 0.0}
        payload = AssertionValidationPayloadV2.model_validate({
            "schema_version": "assertion-validation-payload-v2",
            "mode": mode,
            "assertion": raw_assertion,
            "source_document": {"storage": storage, "schema_version": "assertions-document-v2"},
        })
        normalized = normalize_assertion(payload.assertion.model_dump(mode="json"), configs())
        scores_by_mode[mode] = [item["domain"] for item in resolve_domains(normalized, profile())["preferred_domains"]]
    assert scores_by_mode["LIGHT"] == scores_by_mode["BLOCKCHAIN"]
