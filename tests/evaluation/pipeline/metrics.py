"""Objective observations; lexical coverage is a proxy, never semantic proof."""

from common.utils.search_normalization import normalize_domain
from evaluation.core.common_metrics import evidence_verdict_coherence, normalized_words
from evaluation.core.evidence import gold_bundle
from evaluation.core.artifacts import EvaluationError
from common.utils.evidence_bundle import evidence_bundle_hash


def domain_matches(actual, expected):
    a, e = normalize_domain(actual), normalize_domain(expected)
    return bool(a and e) and (a == e or a.endswith("." + e))


def routing_metrics(route, expected):
    if route.get("status") in {"SKIPPED", "INJECTED", "NOT_EVALUATED"}:
        return {"status": "NOT_EVALUATED"}
    domains = list(dict.fromkeys(normalize_domain(s.get("domain", "")) for s in route.get("sources", [])))
    acceptable = list(dict.fromkeys(normalize_domain(d) for d in expected.get("acceptable_domains", [])))
    if not acceptable:
        return {"status": "NOT_EVALUATED", "source_count": len(domains)}
    ranks = [i for i, d in enumerate(domains, 1) if any(domain_matches(d, a) for a in acceptable)]
    return {"status": "PASS" if ranks else "FAIL", "source_count": len(domains),
            "acceptable_domain_found": bool(ranks), "k": len(domains),
            "domain_recall_at_k": sum(any(domain_matches(d, a) for d in domains) for a in acceptable) / len(acceptable),
            "first_acceptable_domain_rank": min(ranks) if ranks else None}


def retrieval_metrics(retrieval, expected, bundle):
    contexts = [c for source in bundle for c in source.get("contexts", [])
                if c.get("citation_eligible") is True and c.get("text", "").strip()]
    facts = expected.get("reference_facts", []) + [e["text"] for e in expected.get("reference_evidence", [])]
    words = [normalized_words(c["text"]) for c in contexts]
    coverage = []
    for fact in facts:
        terms = normalized_words(fact)
        coverage.append(max((len(terms & w) / len(terms) for w in words), default=0) if terms else 0)
    domains = [normalize_domain(s.get("domain") or s.get("url")) for s in bundle]
    references = [normalize_domain(s.get("domain") or s.get("url")) for s in expected.get("reference_sources", [])]
    references = [r for r in references if r]
    statuses = [s.get("fetch_status") for s in bundle]
    summary = retrieval.get("retrieval_summary") or {}
    attempts = [attempt for source in bundle for attempt in source.get("fetch_attempts") or []]
    outcome_counts = {}
    for source in bundle:
        outcome = source.get("fetch_outcome")
        if outcome:
            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
    documents_attempted = summary.get("documents_attempted")
    if documents_attempted is None:
        documents_attempted = sum(bool(source.get("fetch_attempts")) for source in bundle)
    http_requests = summary.get("http_requests")
    if http_requests is None:
        http_requests = len(attempts)
    http_responses = summary.get("http_responses")
    if http_responses is None:
        http_responses = sum(attempt.get("http_status") is not None for attempt in attempts)
    http_successes = summary.get("http_successes")
    if http_successes is None:
        http_successes = sum(
            isinstance(attempt.get("http_status"), int) and 200 <= attempt["http_status"] < 300
            for attempt in attempts
        )
    reference_source_found = any(domain_matches(d, r) for d in domains for r in references) if references else None
    reference_source_citable = (
        any(
            any(domain_matches(source.get("domain") or source.get("url"), reference) for reference in references)
            and any(context.get("citation_eligible") is True and str(context.get("text") or "").strip()
                    for context in source.get("contexts", []))
            for source in bundle
        ) if references else None
    )
    # Missing fetch status is unknown, not a failed download (e.g. GOLD bundles).
    failed = sum(s in {"failed", "empty_text"} for s in statuses)
    if retrieval.get("status") != "COMPLETED":
        status = "NOT_EVALUATED"
    elif not contexts:
        status = "NO_CITABLE_EVIDENCE"
    elif references and reference_source_citable:
        status = "REFERENCE_CITABLE"
    elif references or facts:
        status = "PARTIAL"
    else:
        status = "AVAILABLE"
    return {"status": status,
            "result_count": len(bundle), "successful_source_count": sum(s == "ok" for s in statuses),
            "failed_source_count": failed, "unknown_fetch_status_count": sum(s is None for s in statuses),
            "contexts_count": len(contexts),
            "response_present": bool(retrieval),
            "response_cached": bool(retrieval.get("cached")),
            "documents_attempted": documents_attempted,
            "http_requests": http_requests,
            "http_responses": http_responses,
            "http_successes": http_successes,
            "documents_extracted": summary.get("documents_extracted", sum(s == "ok" for s in statuses)),
            "documents_citable": summary.get("documents_citable", sum(
                any(context.get("citation_eligible") is True and str(context.get("text") or "").strip()
                    for context in source.get("contexts", []))
                for source in bundle
            )),
            "fetch_outcome_counts": summary.get("outcome_counts", outcome_counts),
            "retry_actions": summary.get("retry_actions", sum(
                action.get("action") == "RETRY"
                for source in bundle for action in source.get("fetch_retry_trace", [])
            )),
            "retry_recovered": summary.get("retry_recovered", sum(
                source.get("fetch_status") == "ok" and any(
                    action.get("action") == "RETRY" for action in source.get("fetch_retry_trace") or []
                ) for source in bundle
            )),
            "retry_exhausted": summary.get("retry_exhausted", sum(
                source.get("fetch_status") != "ok" and any(
                    action.get("action") == "RETRY" for action in source.get("fetch_retry_trace") or []
                ) for source in bundle
            )),
            "candidate_substitutions": summary.get("candidate_substitutions", sum(
                source.get("retrieval_mode") == "existing_provider_candidates_after_unusable_fetch"
                for source in bundle
            )),
            "substitution_recovered": summary.get("substitution_recovered", sum(
                source.get("retrieval_mode") == "existing_provider_candidates_after_unusable_fetch"
                and source.get("citation_status") == "available" and bool(source.get("contexts"))
                for source in bundle
            )),
            "substitution_exhausted": summary.get("substitution_exhausted", sum(
                source.get("retrieval_mode") == "existing_provider_candidates_after_unusable_fetch"
                and not (source.get("citation_status") == "available" and source.get("contexts"))
                for source in bundle
            )),
            "reference_source_found": reference_source_found,
            "reference_source_citable": reference_source_citable,
            "lexical_reference_coverage": sum(coverage) / len(coverage) if coverage else None,
            "lexical_reference_complete": bool(coverage) and min(coverage) == 1,
            "reference_coverage_method": "max_per_context_word_overlap; lexical only"}


def handoff_metrics(inputs):
    retrieved = inputs.get("retrieval_evidence_bundle_hash")
    delivered = inputs.get("validator_input_evidence_bundle_hash")
    return {"status": "NOT_EVALUATED" if not retrieved or not delivered else
            "PASS" if retrieved == delivered else "HANDOFF_EVIDENCE_MISMATCH",
            "retrieval_evidence_bundle_hash": retrieved, "validator_input_evidence_bundle_hash": delivered}


def evaluate(result):
    """Accept the common dataclass or a persisted JSON artifact."""
    row = result.to_dict() if hasattr(result, "to_dict") else result
    expected = row["expected"]
    output = row.get("validator_output", {})
    grounding = row.get("grounding", {})
    audit = grounding.get("validation", grounding)
    inputs = row.get("validator_input", {})
    bundle = inputs.get("evidences", row.get("retrieval", {}).get("evidences", []))
    verdict = output.get("effective_verdict", output.get("resultado"))
    errors = row.get("errors", [])
    scoring_eligible = row.get("provenance", {}).get("scoring_eligible", True)
    gold_delivered = row["execution_mode"] == "GOLD_EVIDENCE"
    if row["execution_mode"] == "VALIDATOR_REPLAY" and "reference_evidence" in expected:
        try:
            gold_delivered = evidence_bundle_hash(bundle) == evidence_bundle_hash(gold_bundle(expected))
        except EvaluationError:
            gold_delivered = False
    sufficient = gold_delivered and expected["expected_verdict"] in {"TRUE", "FALSE"} and any(
        e.get("relation") == ("SUPPORTS" if expected["expected_verdict"] == "TRUE" else "CONTRADICTS")
        for e in expected.get("reference_evidence", []))
    if not scoring_eligible:
        validation = "NOT_EVALUATED"
    elif any(e.get("code") == "INVALID_RESPONSE" for e in errors):
        validation = "INVALID_RESPONSE"
    elif not verdict:
        validation = "NOT_EVALUATED"
    elif verdict == expected["expected_verdict"]:
        validation = "EXPECTED_ABSTENTION" if verdict == "UNKNOWN" else "CORRECT"
    elif verdict == "UNKNOWN" and sufficient:
        validation = "UNNECESSARY_ABSTENTION"
    else:
        validation = "WRONG_VERDICT"
    citation_issues = audit.get("issues", [])
    grounding_status = "NOT_EVALUATED"
    if audit.get("basis") == "RETRIEVED_EVIDENCE":
        grounding_status = "LLM_CITATION_ERROR" if citation_issues else "GROUNDING_PASS"
    if any(e.get("stage") == "GROUNDING" for e in errors):
        grounding_status = "GROUNDING_ERROR"
    consensus = row.get("consensus", {})
    consensus_status = "NOT_EVALUATED"
    if scoring_eligible and consensus.get("status") != "NOT_EVALUATED" and consensus.get("verdict"):
        consensus_status = "CONSENSUS_PASS" if consensus["verdict"] == expected["expected_verdict"] else "CONSENSUS_ERROR"
    coherence = evidence_verdict_coherence(expected, str(row.get("assertion", {}).get("text") or
                                                          row.get("assertion", {}).get("assertion") or ""),
                                           bundle, verdict) if scoring_eligible else {"status": "NOT_EVALUATED"}
    return {
        "extraction": row.get("extraction", {"status": "NOT_EVALUATED"}),
        "routing": routing_metrics(row.get("router", {}), expected),
        "retrieval": retrieval_metrics(row.get("retrieval", {}), expected, bundle),
        "handoff": handoff_metrics(inputs),
        "validation": {"status": validation, "expected": expected["expected_verdict"] if scoring_eligible else None,
                       "verdict": verdict, "raw_verdict": output.get("resultado"),
                       "gold_supports_expected": sufficient,
                       "correct": verdict == expected["expected_verdict"] if verdict and scoring_eligible else None},
        "evidence_coherence": coherence,
        "grounding": {"status": grounding_status, "claimed_count": audit.get("claimed_count"),
                      "verified_count": audit.get("verified_count"), "rejected_count": audit.get("rejected_count")},
        "consensus": {"status": consensus_status, "verdict": consensus.get("verdict")},
    }
