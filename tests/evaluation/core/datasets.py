"""Compatible news resources, with optional objective reference annotations."""

from pathlib import Path
from urllib.parse import urlsplit

from evaluation import ROOT
from common.routing_taxonomy import EvidenceKind, TopicCode
from .artifacts import EvaluationError, read_json
from .common_metrics import normalize_verdict

TAG_FAMILIES = ("lang", "jurisdiction", "topic", "difficulty", "temporal", "evidence", "expected")


def _strings(value, name):
    if not isinstance(value, list) or any(not isinstance(s, str) or not s.strip() for s in value):
        raise EvaluationError(f"{name} must be an array of non-empty strings")


def validate_case(case: dict) -> None:
    version = case.get("schema_version")
    # V1 historically accepted schema versions encoded as strings.
    if version == "1":
        version = 1
    if type(version) is not int or version not in (1, 2):
        raise EvaluationError("schema_version must be 1 or 2")
    if not str(case.get("id") or "").strip() or not str(case.get("news") or "").strip():
        raise EvaluationError("A case needs id and news")
    assertions = case.get("assertions")
    if not isinstance(assertions, list) or not assertions:
        raise EvaluationError("A case needs assertions[]")
    ids = set()
    for item in [case, *assertions]:
        if not isinstance(item, dict):
            raise EvaluationError("Assertions must be objects")
        _strings(item.get("tags", []), "tags")
        if any(":" not in tag or not all(tag.split(":", 1)) for tag in item.get("tags", [])):
            raise EvaluationError("Tags must use family:value")
    for item in assertions:
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier.strip() or identifier in ids:
            raise EvaluationError("Each assertion needs a unique non-empty string id")
        ids.add(identifier)
        allowed = {"TRUE", "FALSE"} if version == 1 else {"TRUE", "FALSE", "UNKNOWN"}
        verdict = normalize_verdict(item.get("expected_verdict")) if version == 1 else item.get("expected_verdict")
        if verdict not in allowed:
            raise EvaluationError(f"{identifier}: invalid expected_verdict")
        if version == 1 and not item.get("required_terms"):
            raise EvaluationError(f"{identifier}: required_terms cannot be empty")
        if version == 2 and not str(item.get("text") or "").strip():
            raise EvaluationError(f"{identifier}: text is required")
        excerpt = item.get("source_excerpt")
        if excerpt is not None and (not isinstance(excerpt, str) or not excerpt.strip()
                                    or excerpt not in case["news"]):
            raise EvaluationError(f"{identifier}: source_excerpt must occur in news")
        expected_topic = item.get("expected_topic_code")
        if expected_topic is not None and expected_topic not in {value.value for value in TopicCode}:
            raise EvaluationError(f"{identifier}: expected_topic_code is not in {TopicCode.__name__}")
        expected_kind = item.get("expected_evidence_kind")
        if expected_kind is not None and expected_kind not in {value.value for value in EvidenceKind}:
            raise EvaluationError(f"{identifier}: expected_evidence_kind is not in {EvidenceKind.__name__}")
        context = item.get("expected_context")
        if context is not None:
            if not isinstance(context, dict) or set(context) - {"entities", "locations", "temporal_context", "jurisdiction"}:
                raise EvaluationError(f"{identifier}: invalid expected_context")
            for key in ("entities", "locations", "temporal_context"):
                if key in context:
                    _strings(context[key], f"{identifier}: expected_context.{key}")
            if "jurisdiction" in context and (not isinstance(context["jurisdiction"], dict)
                                              or not context["jurisdiction"]):
                raise EvaluationError(f"{identifier}: expected_context.jurisdiction must be an object")
        for key in ("required_terms", "acceptable_domains", "reference_facts"):
            _strings(item.get(key, []), key)
        for key in ("reference_sources", "reference_evidence"):
            rows = item.get(key, [])
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise EvaluationError(f"{identifier}: {key} must contain objects")
            for row in rows:
                if row.get("relation") not in (None, "SUPPORTS", "CONTRADICTS", "NEUTRAL"):
                    raise EvaluationError(f"{identifier}: invalid evidence relation")
                if key == "reference_evidence" and not str(row.get("text") or "").strip():
                    raise EvaluationError(f"{identifier}: reference evidence needs text")
                # Source may be a reference_sources ID; GOLD conversion resolves it.
                if key == "reference_sources" and row.get("url"):
                    parsed = urlsplit(row["url"])
                    if parsed.scheme not in ("http", "https") or not parsed.hostname:
                        raise EvaluationError(f"{identifier}: invalid reference URL")


def load_datasets(paths: list[str], tags: list[str] | None = None) -> list[dict]:
    """All requested tags must match a resource or its assertion's tags (AND)."""
    result = []
    seen = set()
    for value in paths:
        path = Path(value)
        if not path.exists():
            candidates = [ROOT / "tests/data/evaluation/resources/datasets" / f"{value}.json",
                          ROOT / "tests/data/benchmark/resources/cases" / f"{value}.json"]
            path = next((p for p in candidates if p.is_file()), path)
        files = sorted(path.glob("*.json")) if path.is_dir() else [path]
        for file in files:
            case = read_json(file)
            validate_case(case)
            if case["id"] in seen:
                raise EvaluationError(f"Duplicate dataset id: {case['id']}")
            seen.add(case["id"])
            wanted = set(tags or [])
            assertions = [a for a in case["assertions"] if wanted <= set(case.get("tags", [])) | set(a.get("tags", []))]
            if assertions:
                result.append({**case, "assertions": assertions})
    if not result:
        raise EvaluationError("No cases matched the dataset/tag selection")
    return result
