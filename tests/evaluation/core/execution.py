"""One execution path for the benchmark and pipeline evaluation.

Only this module invokes LLMs. HTTP services use existing production contracts.
"""

from copy import deepcopy
import time

from common.utils.evidence_bundle import evidence_bundle_hash
from common.utils.validation_prompt import DEFAULT_RAG_PROMPT, build_rag_prompt
from .artifacts import EvaluationError, canonical_json, sha256_text
from .evidence import gold_bundle, replay_bundle
from .models import CaseResult, ExecutionMode, CacheMode


def validator_config(provider, model, temperature=0.0, identifier=None):
    import math
    if provider not in {"openrouter", "gemini", "mistral", "grok"} or not model.strip():
        raise EvaluationError("Use an existing provider and a non-empty model")
    if not math.isfinite(temperature) or temperature < 0:
        raise EvaluationError("temperature must be finite and non-negative")
    return {"id": identifier or f"{provider}:{model}", "provider": provider,
            "model": model, "temperature": temperature, "validator_type": "RAG_EVIDENCE_VALIDATION"}


def execute(dataset, expected, config, mode="GOLD_EVIDENCE", *, services=None,
            cache_mode=None, replay=None, template=DEFAULT_RAG_PROMPT, complete_fn=None,
            progress=None):
    """Run a single assertion/validator and retain failures as structured results."""
    mode = ExecutionMode(mode).value
    frozen = mode in {"GOLD_EVIDENCE", "VALIDATOR_REPLAY"}
    cache_mode = CacheMode(cache_mode or ("FROZEN" if frozen else "WARM")).value
    if frozen != (cache_mode == "FROZEN"):
        raise EvaluationError("GOLD_EVIDENCE/REPLAY require FROZEN; live modes require WARM or COLD")
    assertion = deepcopy(expected.get("pipeline_assertion") or {"text": expected.get("text", "")})
    result = CaseResult(expected["id"], mode, assertion, deepcopy(expected),
                        dataset_id=dataset["id"], dataset_hash=sha256_text(canonical_json(dataset)),
                        assertion_id=str(assertion.get("assertion_id", expected["id"])), validator=deepcopy(config))
    result.cache_state["mode"] = cache_mode

    def notify(phase, **fields):
        if progress:
            progress(phase, run_id=result.run_id, case_id=result.case_id, mode=mode, **fields)

    notify("run.start", cache=cache_mode, validator=config.get("id"))
    if frozen:
        result.cache_state.update(router_cache_hit=False, evidence_cache_hit=False,
                                  route_recomputed=False, evidence_recomputed=False)
    started = time.monotonic()
    stage = "SETUP"
    try:
        if expected.get("pipeline_assertion"):
            from common.models.protocol_models import EnrichedAssertion
            assertion = EnrichedAssertion.model_validate(assertion).model_dump(mode="json")
            result.assertion = assertion
        if mode == "VALIDATOR_REPLAY":
            if replay is None:
                raise EvaluationError("VALIDATOR_REPLAY requires an artifact")
            if (replay["case_id"] != expected["id"]
                    or replay.get("dataset_id") not in (None, dataset["id"])
                    or replay["expected"] != expected):
                raise EvaluationError("Replay dataset/case/expected identity mismatch")
            bundle = replay_bundle(replay)
            assertion = deepcopy(replay["assertion"])
            result.assertion = assertion
            result.assertion_id = replay.get("assertion_id")
            result.provenance["replay_of"] = replay["run_id"]
            context = replay["validator_input"]["context"]
            result.router = {"status": "SKIPPED"}
            notify("router.skipped", reason="validator_replay")
            result.retrieval = {"status": "INJECTED", "evidence_bundle_hash": evidence_bundle_hash(bundle)}
            notify("retrieval.injected", evidence_count=len(bundle), source="replay")
        elif mode == "GOLD_EVIDENCE":
            bundle = gold_bundle(expected)
            context = canonical_json({"assertion": assertion})
            result.router = {"status": "SKIPPED"}
            notify("router.skipped", reason="gold_evidence")
            result.retrieval = {"status": "INJECTED", "evidence_bundle_hash": evidence_bundle_hash(bundle)}
            notify("retrieval.injected", evidence_count=len(bundle), source="gold_evidence")
        else:
            from common.models.protocol_models import EnrichedAssertion
            assertion = EnrichedAssertion.model_validate(assertion).model_dump(mode="json")
            result.assertion = assertion
            context = canonical_json({"assertion": assertion})
            if services is None:
                raise EvaluationError("Live modes require Source Router / Evidence Search services")
            if mode == "GOLD_DOMAINS":
                domains = expected.get("acceptable_domains")
                if not domains:
                    raise EvaluationError("GOLD_DOMAINS requires acceptable_domains")
                result.router = {"status": "INJECTED", "sources": [
                    {"domain": d, "source_type": "UNKNOWN", "authority_level": "UNKNOWN",
                     "jurisdictions": [], "topic_codes": [assertion["topic_code"]],
                     "evidence_kinds": [assertion["evidence_kind"]], "languages": [],
                     "route_score": 0, "rank": index, "reason": "Dataset acceptable domain (authority not inferred)",
                     "profile_version": "evaluation-gold-v1"}
                    for index, d in enumerate(domains, 1)]}
                result.cache_state.update(router_cache_hit=False, route_recomputed=False)
                notify("router.injected", source_count=len(result.router["sources"]), source="gold_domains")
            else:
                stage = "ROUTING"
                notify("router.start")
                t = time.monotonic()
                result.router = {"status": "COMPLETED", **services.route(assertion, result.run_id, cache_mode)}
                result.timings["routing_seconds"] = time.monotonic() - t
                notify("router.complete", source_count=len(result.router.get("sources", [])),
                       route_state=result.router.get("route_state"),
                       seconds=round(result.timings["routing_seconds"], 6))
                result.cache_state.update(router_cache_hit=(result.router.get("route_state") == "FRESH" or bool(result.router.get("stale_route_used"))),
                                          route_recomputed=result.router.get("route_state") in {"MISSING", "STALE"} and not result.router.get("stale_route_used", False))
            stage = "RETRIEVAL"
            notify("retrieval.start", source_count=len(result.router.get("sources", [])))
            t = time.monotonic()
            sources = result.router.get("sources", [])
            response = (services.retrieve(assertion, sources, dataset.get("origin_document", {}), result.run_id, cache_mode)
                        if sources else {"evidences": [], "cached": False, "search_skipped": "no_eligible_local_sources"})
            bundle = response.get("evidences", [])
            result.retrieval = {"status": "COMPLETED", **response}
            result.timings["retrieval_seconds"] = time.monotonic() - t
            result.cache_state.update(evidence_cache_hit=response.get("cached"),
                                      evidence_recomputed=bool(sources) and response.get("cached") is False)
            notify("retrieval.complete", evidence_count=len(bundle), cached=response.get("cached"),
                   skipped=response.get("search_skipped"), seconds=round(result.timings["retrieval_seconds"], 6))
            if cache_mode == "COLD" and (result.cache_state["router_cache_hit"] or response.get("cached")):
                raise EvaluationError("COLD service returned cached results")
        if not str(assertion.get("text") or "").strip():
            raise EvaluationError("Validator execution requires assertion text")
        input_hash = evidence_bundle_hash(bundle)
        prompt = build_rag_prompt(assertion["text"], context, bundle, template)
        result.validator_input = {
            "evidences": deepcopy(bundle), "context": context,
            "validator_input_evidence_bundle_hash": input_hash,
            "retrieval_evidence_bundle_hash": result.retrieval.get("evidence_bundle_hash"),
            "prompt_hash": sha256_text(prompt), "prompt_template_hash": sha256_text(template),
        }
        if replay and replay["validator_input"].get("prompt_hash") != result.validator_input["prompt_hash"]:
            raise EvaluationError("Replay prompt differs; provide the original template and context")
        notify("validator_input.prepared", evidence_count=len(bundle),
               evidence_bundle_hash=input_hash)
        stage = "VALIDATION"
        notify("validation.start")
        from common.llm import LLMRequest, complete, parse_response
        from common.models.async_models import RAGValidatorAPIResponse
        from common.utils.evidence import evaluate_evidence_grounding
        request = LLMRequest(prompt=prompt, model=config["model"], temperature=config["temperature"],
                             response_model=RAGValidatorAPIResponse)
        result.validator_input["response_schema_hash"] = sha256_text(canonical_json(request.response_schema))
        if replay and replay["validator_input"].get("response_schema_hash") not in (None, result.validator_input["response_schema_hash"]):
            raise EvaluationError("Replay response contract differs")
        t = time.monotonic()
        try:
            response = (complete_fn or complete)(config["provider"], request)
            # Persist only a safe, structured response; never raw provider metadata.
            parsed = parse_response(request, response)
        finally:
            result.timings["validation_seconds"] = time.monotonic() - t
        result.validator_output = parsed.model_dump(mode="json")
        result.validator_output["resolved_provider"] = response.provider
        result.validator_output["resolved_model"] = response.model
        result.validator_output["usage"] = response.usage.model_dump() if response.usage else None
        notify("validation.complete", provider=response.provider, model=response.model,
               seconds=round(result.timings["validation_seconds"], 6))
        stage = "GROUNDING"
        notify("grounding.start")
        result.grounding = evaluate_evidence_grounding(parsed.resultado, result.validator_output["evidence_used"],
                                                      bundle, require_grounding=True)
        result.validator_output["effective_verdict"] = result.grounding["effective_verdict"]
        notify("grounding.complete", effective_verdict=result.validator_output["effective_verdict"],
               status=result.grounding.get("validation", {}).get("basis"))
    except Exception as exc:
        # Provider exception bodies can contain request credentials. Store type/stage only.
        code = "INVALID_RESPONSE" if type(exc).__name__ in {"LLMResponseError", "ValidationError"} and stage == "VALIDATION" else "TECHNICAL_ERROR"
        error = {"stage": stage, "code": code, "exception_type": type(exc).__name__}
        status = getattr(getattr(exc, "response", None), "status_code", None) or getattr(exc, "status_code", None)
        if status is not None:
            error["status_code"] = status
            error["retryable"] = status in {408, 429} or status >= 500
        if isinstance(exc, EvaluationError):
            error["reason"] = str(exc)
        result.errors.append(error)
        notify("run.failed", stage=stage, error_code=code, exception_type=type(exc).__name__)
    result.timings["total_seconds"] = time.monotonic() - started
    notify("run.complete", errors=len(result.errors), seconds=round(result.timings["total_seconds"], 6))
    return result
