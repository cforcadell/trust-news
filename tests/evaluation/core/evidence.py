"""Reference evidence and replay use the production evidence/grounding shape."""

from copy import deepcopy
from urllib.parse import urlsplit

from common.utils.evidence_bundle import evidence_bundle_hash, text_hash
from .artifacts import EvaluationError


def gold_bundle(assertion: dict) -> list[dict]:
    if "reference_evidence" not in assertion:
        raise EvaluationError("GOLD_EVIDENCE requires reference_evidence (explicit [] is allowed for abstention)")
    references = assertion.get("reference_sources", [])
    indexed = {row.get("id", row.get("url")): row for row in references}
    sources = []
    for index, evidence in enumerate(assertion["reference_evidence"], 1):
        ref = evidence.get("source") or evidence.get("url")
        source = indexed.get(ref, {})
        url = source.get("url") or ref
        parsed = urlsplit(str(url or ""))
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise EvaluationError("Gold evidence source must resolve to an HTTP(S) URL")
        sources.append({
            "source_id": f"gold-source-{index}", "url": url,
            "domain": parsed.hostname, "title": source.get("title", "Reference evidence"),
            "relationship_to_origin": source.get("relationship_to_origin", "UNKNOWN"),
            "contexts": [{"context_id": f"gold-context-{index}", "text": evidence["text"],
                          "text_sha256": text_hash(evidence["text"]), "citation_eligible": True}],
        })
    return sources


def replay_bundle(artifact: dict) -> list[dict]:
    if artifact.get("schema_version") != "evaluation-result-v1":
        raise EvaluationError("Replay requires an evaluation-result-v1 artifact")
    if not all(artifact.get(key) for key in ("run_id", "case_id", "assertion", "expected")):
        raise EvaluationError("Replay artifact lacks case identity/assertion/expected fields")
    inputs = artifact.get("validator_input", {})
    if not isinstance(inputs.get("context"), str) or not inputs.get("prompt_hash"):
        raise EvaluationError("Replay artifact lacks the original context/prompt hash")
    bundle = inputs.get("evidences")
    expected_hash = inputs.get("validator_input_evidence_bundle_hash")
    if not isinstance(bundle, list) or not expected_hash:
        raise EvaluationError("Replay artifact does not contain the validator input bundle and hash")
    if evidence_bundle_hash(bundle) != expected_hash:
        raise EvaluationError("Replay evidence integrity check failed")
    return deepcopy(bundle)
