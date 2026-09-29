"""Objective observations; lexical coverage is a proxy, never semantic proof."""

from common.utils.search_normalization import normalize_domain
from evaluation.core.common_metrics import normalized_words
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
    # Missing fetch status is unknown, not a failed download (e.g. GOLD bundles).
    failed = sum(s in {"failed", "empty_text"} for s in statuses)
    return {"status": "NOT_EVALUATED" if retrieval.get("status") != "COMPLETED" or not facts else
            ("PASS" if coverage and min(coverage) == 1 else "FAIL"),
            "result_count": len(bundle), "successful_source_count": sum(s == "ok" for s in statuses),
            "failed_source_count": failed, "unknown_fetch_status_count": sum(s is None for s in statuses),
            "contexts_count": len(contexts),
            "reference_source_found": any(domain_matches(d, r) for d in domains for r in references) if references else None,
            "lexical_reference_coverage": sum(coverage) / len(coverage) if coverage else None,
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
    gold_delivered = row["execution_mode"] == "GOLD_EVIDENCE"
    if row["execution_mode"] == "VALIDATOR_REPLAY" and "reference_evidence" in expected:
        try:
            gold_delivered = evidence_bundle_hash(bundle) == evidence_bundle_hash(gold_bundle(expected))
        except EvaluationError:
            gold_delivered = False
    sufficient = gold_delivered and expected["expected_verdict"] in {"TRUE", "FALSE"} and any(
        e.get("relation") == ("SUPPORTS" if expected["expected_verdict"] == "TRUE" else "CONTRADICTS")
        for e in expected.get("reference_evidence", []))
    if any(e.get("code") == "INVALID_RESPONSE" for e in errors):
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
    if consensus.get("status") != "NOT_EVALUATED" and consensus.get("verdict"):
        consensus_status = "CONSENSUS_PASS" if consensus["verdict"] == expected["expected_verdict"] else "CONSENSUS_ERROR"
    return {
        "extraction": row.get("extraction", {"status": "NOT_EVALUATED"}),
        "routing": routing_metrics(row.get("router", {}), expected),
        "retrieval": retrieval_metrics(row.get("retrieval", {}), expected, bundle),
        "handoff": handoff_metrics(inputs),
        "validation": {"status": validation, "expected": expected["expected_verdict"], "verdict": verdict,
                       "raw_verdict": output.get("resultado"), "gold_supports_expected": sufficient, "correct": verdict == expected["expected_verdict"] if verdict else None},
        "grounding": {"status": grounding_status, "claimed_count": audit.get("claimed_count"),
                      "verified_count": audit.get("verified_count"), "rejected_count": audit.get("rejected_count")},
        "consensus": {"status": consensus_status, "verdict": consensus.get("verdict")},
    }
