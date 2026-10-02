from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from common.llm import LLMResponse, LLMUsage
from common.models.evidence_models import EvidenceSearchRequestV2
from common.utils.evidence_bundle import evidence_bundle_hash
from common.utils.validation_prompt import build_rag_prompt
from evaluation.core.artifacts import EvaluationError
from evaluation.core.evidence import gold_bundle, replay_bundle
from evaluation.core.execution import execute, validator_config
from evaluation.pipeline.metrics import evaluate, handoff_metrics, routing_metrics
from evaluation.pipeline.root_cause import diagnose


def case():
    return {"schema_version": 2, "id": "synthetic", "news": "Municipio ficticio: 120 residentes.",
        "tags": ["lang:es", "topic:statistics"], "assertions": [{
            "id": "population", "text": "El municipio ficticio supera 100 residentes.", "expected_verdict": "TRUE",
            "acceptable_domains": ["example.org"], "required_terms": ["municipio", "residentes"],
            "reference_evidence": [{"text": "El municipio ficticio tiene 120 residentes.", "source": "https://example.org/reference", "relation": "SUPPORTS"}],
            "pipeline_assertion": {"assertion_id": "population", "assertion_index": 0,
                "text": "El municipio ficticio supera 100 residentes.", "categoryId": 10,
                "topic_code": "DEMOGRAPHY", "evidence_kind": "STATISTICAL_DATA",
                "context": {"language": "es", "jurisdiction": {"scope": "UNKNOWN"}}}}]}


CONFIG = validator_config("openrouter", "test-model")


def answer(provider, request):
    # No external call: models get the same production RAG contract and prompt.
    has_evidence = "gold-context-1" in request.prompt
    return LLMResponse(provider=provider, model=request.model,
        content=json.dumps({"resultado": "TRUE" if has_evidence else "UNKNOWN", "descripcion": "example.org", "confidence": "HIGH",
                            "evidence_used": [{"context_id": "gold-context-1", "supports": True, "reason": "120 > 100"}] if has_evidence else []}),
        usage=LLMUsage(total_tokens=10))


def run(mode="GOLD_EVIDENCE", **kwargs):
    dataset = case()
    kwargs.setdefault("complete_fn", answer)
    return execute(dataset, dataset["assertions"][0], CONFIG, mode, **kwargs)


def test_gold_does_not_call_services_and_replays_identical_prompt():
    services = Mock()
    first = run(services=services)
    assert not first.errors
    assert first.validator_output["effective_verdict"] == "TRUE"
    assert first.cache_state["mode"] == "FROZEN"
    assert not services.mock_calls
    second = run("VALIDATOR_REPLAY", replay=first.to_dict(), services=services)
    assert not second.errors
    assert second.validator_input["prompt_hash"] == first.validator_input["prompt_hash"]
    assert second.validator_input["validator_input_evidence_bundle_hash"] == first.validator_input["validator_input_evidence_bundle_hash"]
    assert second.provenance["replay_of"] == first.run_id
    assert not services.mock_calls


def test_replay_detects_tampering_and_changed_prompt():
    original = run().to_dict()
    corrupt = deepcopy(original)
    corrupt["validator_input"]["evidences"][0]["contexts"][0]["text"] += " Changed"
    with pytest.raises(EvaluationError, match="integrity"):
        replay_bundle(corrupt)
    llm = Mock(side_effect=answer)
    d = case()
    result = execute(d, d["assertions"][0], CONFIG, "VALIDATOR_REPLAY", replay=original, template="Changed", complete_fn=llm)
    assert result.errors and result.errors[0]["stage"] == "SETUP"
    llm.assert_not_called()


def test_hash_order_normalization_and_forged_text_hash():
    bundle = gold_bundle(case()["assertions"][0])
    second = deepcopy(bundle)
    second[0]["contexts"][0]["text"] = "  " + second[0]["contexts"][0]["text"] + "\r\n"
    second[0]["contexts"][0]["text_sha256"] = "forged"
    second[0]["url"] = "HTTPS://EXAMPLE.ORG/reference#fragment"
    assert evidence_bundle_hash(bundle) == evidence_bundle_hash(second)
    second[0]["contexts"].append({"context_id": "second", "text": "Different", "citation_eligible": True})
    original_hash = evidence_bundle_hash(second)
    second[0]["contexts"].reverse()
    assert evidence_bundle_hash(second) != original_hash
    assert handoff_metrics({})["status"] == "NOT_EVALUATED"
    assert handoff_metrics({"retrieval_evidence_bundle_hash": original_hash,
                            "validator_input_evidence_bundle_hash": evidence_bundle_hash(second)})["status"] == "HANDOFF_EVIDENCE_MISMATCH"


def test_gold_domains_bypasses_router_and_uses_production_request_contract():
    services = Mock()
    bundle = gold_bundle(case()["assertions"][0])
    def retrieve(assertion, sources, origin, run_id, cache):
        payload = EvidenceSearchRequestV2(schema_version="evidence-search-request-v2", assertion=assertion,
            origin_document=origin, search_policy={"strategy": "LOCAL", "preferred_sources": sources})
        assert payload.search_policy.preferred_sources[0].domain == "example.org"
        assert cache == "COLD"
        return {"evidences": bundle, "cached": False, "evidence_bundle_hash": evidence_bundle_hash(bundle)}
    services.retrieve.side_effect = retrieve
    result = run("GOLD_DOMAINS", services=services, cache_mode="COLD")
    assert not result.errors
    services.route.assert_not_called()
    assert evaluate(result)["handoff"]["status"] == "PASS"
    assert result.cache_state["route_recomputed"] is False
    assert result.cache_state["evidence_recomputed"] is True


def test_counterfactual_attribution_with_same_assertion_and_configuration():
    services = Mock()
    services.route.return_value = {"sources": [], "route_state": "MISSING"}
    bundle = gold_bundle(case()["assertions"][0])
    services.retrieve.return_value = {"evidences": bundle, "cached": False, "evidence_bundle_hash": evidence_bundle_hash(bundle)}
    llm = Mock(side_effect=answer)
    rows = [run(mode, services=services, complete_fn=llm).to_dict() for mode in ("FULL_PIPELINE", "GOLD_DOMAINS", "GOLD_EVIDENCE")]
    for row in rows:
        row["metrics"] = evaluate(row)
    assert rows[0]["metrics"]["validation"]["verdict"] == "UNKNOWN"
    assert rows[0]["grounding"]["validation"]["basis"] == "ROUTER_NO_SOURCE"
    assert llm.call_count == 2
    assert rows[1]["metrics"]["validation"]["correct"]
    assert diagnose(rows[0], rows)["code"] == "ROUTER_NO_SOURCE"
    assert rows[0]["assertion"] == rows[2]["assertion"]


def test_citation_failure_preserves_raw_correct_verdict():
    def invalid_citation(provider, request):
        response = answer(provider, request)
        response.content = response.content.replace("gold-context-1", "invented")
        return response
    d = case()
    row = execute(d, d["assertions"][0], CONFIG, complete_fn=invalid_citation).to_dict()
    row["metrics"] = evaluate(row)
    assert row["validator_output"]["resultado"] == "TRUE"
    assert row["validator_output"]["effective_verdict"] == "UNKNOWN"
    assert diagnose(row)["code"] == "LLM_CITATION_ERROR"


def test_invalid_response_is_not_unknown_and_provider_error_has_no_secret():
    def invalid(provider, request):
        return LLMResponse(provider=provider, model=request.model, content='{"resultado":"MAYBE"}')
    d = case()
    row = execute(d, d["assertions"][0], CONFIG, complete_fn=invalid).to_dict()
    row["metrics"] = evaluate(row)
    assert diagnose(row)["code"] == "LLM_INVALID_RESPONSE"
    def failed(*args):
        raise RuntimeError("request had api_key=TOP_SECRET")
    row = execute(d, d["assertions"][0], CONFIG, complete_fn=failed).to_dict()
    assert "TOP_SECRET" not in json.dumps(row)
    assert row["errors"][0]["code"] == "TECHNICAL_ERROR"


def test_routing_recall_handles_subdomains_duplicates_and_impostors():
    result = routing_metrics({"status": "COMPLETED", "sources": [
        {"domain": "ine.es.bad.example"}, {"domain": "data.ine.es"}, {"domain": "data.ine.es"}]},
        {"acceptable_domains": ["ine.es", "ec.europa.eu"]})
    assert result["status"] == "PASS"
    assert result["domain_recall_at_k"] == 0.5
    assert result["first_acceptable_domain_rank"] == 2


def test_frozen_failure_never_attributed_to_router_from_other_mode():
    gold = run().to_dict()
    domains = deepcopy(gold)
    domains["execution_mode"] = "GOLD_DOMAINS"
    gold["validator_output"]["effective_verdict"] = "FALSE"
    for row in (gold, domains):
        row["metrics"] = evaluate(row)
    assert diagnose(gold, [domains])["code"] == "LLM_WRONG_VERDICT"


def test_frozen_empty_evidence_does_not_blame_llm_for_abstaining():
    d = case()
    d["assertions"][0]["reference_evidence"] = []
    row = execute(d, d["assertions"][0], CONFIG, complete_fn=answer).to_dict()
    row["metrics"] = evaluate(row)
    assert diagnose(row)["code"] == "UNDETERMINED"


def test_replay_of_live_empty_bundle_does_not_claim_gold_was_delivered():
    services = Mock()
    services.route.return_value = {"sources": [], "route_state": "MISSING"}
    live = run("FULL_PIPELINE", services=services).to_dict()
    replay = run("VALIDATOR_REPLAY", replay=live).to_dict()
    assert not replay["errors"]
    replay["metrics"] = evaluate(replay)
    assert replay["metrics"]["validation"]["gold_supports_expected"] is False
    assert diagnose(replay)["code"] == "UNDETERMINED"


@pytest.mark.parametrize("change", ["dataset", "expected"])
def test_replay_rejects_different_dataset_or_expectation(change):
    original = run().to_dict()
    dataset = case()
    if change == "dataset":
        dataset["id"] = "different"
    else:
        dataset["assertions"][0]["expected_verdict"] = "FALSE"
    llm = Mock(side_effect=answer)
    result = execute(dataset, dataset["assertions"][0], CONFIG, "VALIDATOR_REPLAY",
                     replay=original, complete_fn=llm)
    assert result.errors
    llm.assert_not_called()


def test_counterfactuals_do_not_cross_datasets_or_repetitions():
    services = Mock()
    services.route.return_value = {"sources": [{"domain": "example.org"}], "route_state": "FRESH"}
    services.retrieve.return_value = {"evidences": [], "cached": False}
    full = run("FULL_PIPELINE", services=services).to_dict()
    full["metrics"] = evaluate(full)
    other = run().to_dict()
    other["execution_mode"] = "GOLD_DOMAINS"
    other["metrics"] = evaluate(other)
    assert diagnose(full, [other])["code"] == "ROUTER_WRONG_SOURCE"
    other["dataset_id"] = "different"
    assert diagnose(full, [other])["code"] == "RETRIEVAL_NO_RESULT"
    other["dataset_id"] = full["dataset_id"]
    other["provenance"]["repetition"] = 2
    assert diagnose(full, [other])["code"] == "RETRIEVAL_NO_RESULT"
