"""Validate the identity and observation links of a saved order diagnostic.

The JSON Schema describes field shapes. This stdlib validator checks the
cross-record constraints that JSON Schema cannot express conveniently.
"""

from pathlib import PurePosixPath


SCHEMA_VERSION = "order-diagnostic-v1"
STAGES = ("router", "evidence_search", "handoff", "llm", "citations", "consensus")
ASSESSMENTS = {"PASS", "FAIL", "PARTIAL", "NOT_EVALUATED", "SKIPPED"}
EXECUTION_STATUSES = {"COMPLETED", "FAILED", "SKIPPED", "NOT_RECORDED"}


class ContractError(ValueError):
    pass


def _fail(message):
    raise ContractError(message)


def _nonempty(value, name):
    if not isinstance(value, str) or not value.strip():
        _fail(f"{name} must be a non-empty string")


def _artifact_path(value, name):
    _nonempty(value, name)
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value != path.as_posix():
        _fail(f"{name} must be a normalized path relative to the campaign")


def _stage(value, name):
    if not isinstance(value, dict):
        _fail(f"{name} must be an object")
    if value.get("execution_status") not in EXECUTION_STATUSES:
        _fail(f"{name}.execution_status is invalid")
    if value.get("assessment") not in ASSESSMENTS:
        _fail(f"{name}.assessment is invalid")
    if value["assessment"] in {"NOT_EVALUATED", "SKIPPED"}:
        _nonempty(value.get("missing_reason"), f"{name}.missing_reason")
    if value["assessment"] == "SKIPPED" and value["execution_status"] != "SKIPPED":
        _fail(f"{name}: SKIPPED assessment requires SKIPPED execution")
    if not isinstance(value.get("observations"), dict):
        _fail(f"{name}.observations must be an object")
    checks = value.get("checks")
    if not isinstance(checks, list):
        _fail(f"{name}.checks must be an array")
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            _fail(f"{name}.checks[{index}] must be an object")
        _nonempty(check.get("code"), f"{name}.checks[{index}].code")
        if check.get("status") not in ASSESSMENTS:
            _fail(f"{name}.checks[{index}].status is invalid")
        if not isinstance(check.get("detail"), str):
            _fail(f"{name}.checks[{index}].detail must be text")


def _observation_refs(stage, document):
    for check in stage["checks"]:
        for pointer in check.get("observation_refs", []):
            if not isinstance(pointer, str) or not pointer.startswith("/"):
                _fail("observation_refs must contain absolute JSON pointers")
            current = document
            try:
                for part in pointer[1:].split("/"):
                    part = part.replace("~1", "/").replace("~0", "~")
                    current = current[int(part)] if isinstance(current, list) else current[part]
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ContractError(f"Unresolvable observation_ref: {pointer}") from exc


def validate_order_diagnostic(document):
    """Raise ContractError for a malformed or internally inconsistent snapshot."""
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
        _fail(f"Expected {SCHEMA_VERSION}")
    identity = document.get("identity")
    if not isinstance(identity, dict):
        _fail("identity must be an object")
    for name in ("campaign_id", "dataset_id", "order_id"):
        _nonempty(identity.get(name), f"identity.{name}")
    if type(identity.get("repetition")) is not int or identity["repetition"] < 1:
        _fail("identity.repetition must be a positive integer")

    refs = document.get("artifact_refs")
    if not isinstance(refs, dict) or not isinstance(refs.get("results"), list):
        _fail("artifact_refs must contain a results array")
    _artifact_path(refs.get("order"), "artifact_refs.order")
    ref_ids = set()
    for index, ref in enumerate(refs["results"]):
        if not isinstance(ref, dict):
            _fail(f"artifact_refs.results[{index}] must be an object")
        run_id = ref.get("run_id")
        _nonempty(run_id, f"artifact_refs.results[{index}].run_id")
        _artifact_path(ref.get("path"), f"artifact_refs.results[{index}].path")
        if run_id in ref_ids:
            _fail(f"Duplicate run_id reference: {run_id}")
        ref_ids.add(run_id)

    order = document.get("order")
    if not isinstance(order, dict) or not isinstance(order.get("assertions"), list):
        _fail("order must contain assertions")
    _nonempty(order.get("status"), "order.status")
    if not isinstance(order.get("original_text"), str):
        _fail("order.original_text must be text")
    _stage(order.get("generation"), "order.generation")
    assertion_ids = set()
    for index, assertion in enumerate(order["assertions"]):
        if not isinstance(assertion, dict):
            _fail(f"order.assertions[{index}] must be an object")
        assertion_id = assertion.get("assertion_id")
        _nonempty(assertion_id, f"order.assertions[{index}].assertion_id")
        if assertion_id in assertion_ids:
            _fail(f"Duplicate assertion_id: {assertion_id}")
        assertion_ids.add(assertion_id)
        if not isinstance(assertion.get("text"), str):
            _fail(f"order.assertions[{index}].text must be text")

    validations = document.get("validations")
    if not isinstance(validations, list):
        _fail("validations must be an array")
    seen_runs = set()
    seen_pairs = set()
    for index, validation in enumerate(validations):
        if not isinstance(validation, dict):
            _fail(f"validations[{index}] must be an object")
        run_id = validation.get("run_id")
        assertion_id = validation.get("assertion_id")
        validator_id = validation.get("validator_id")
        for name, value in (("run_id", run_id), ("assertion_id", assertion_id), ("validator_id", validator_id)):
            _nonempty(value, f"validations[{index}].{name}")
        if run_id in seen_runs:
            _fail(f"Duplicate validation run_id: {run_id}")
        if assertion_id not in assertion_ids:
            _fail(f"Unknown assertion_id in validation: {assertion_id}")
        pair = assertion_id, validator_id
        if pair in seen_pairs:
            _fail(f"Duplicate assertion/validator pair: {pair}")
        seen_runs.add(run_id)
        seen_pairs.add(pair)
        stages = validation.get("stages")
        if not isinstance(stages, dict) or set(stages) != set(STAGES):
            _fail(f"validations[{index}].stages must contain exactly {', '.join(STAGES)}")
        for name in STAGES:
            _stage(stages[name], f"validations[{index}].stages.{name}")
    if seen_runs != ref_ids:
        _fail("artifact_refs.results run_ids must match validation run_ids")
    _observation_refs(order["generation"], document)
    for validation in validations:
        for name in STAGES:
            _observation_refs(validation["stages"][name], document)
    return document
