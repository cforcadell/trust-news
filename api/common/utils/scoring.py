import math
from typing import Any, Callable, Dict, Optional

from common.models.async_models import ValidatorType, get_validator_type_weight, normalize_validation_result


CONSENSUS_POLICY = {
    "version": "consensus-v2",
    "min_decisive_coverage": 0.5,
    "tie_epsilon": 1e-9,
}
WEIGHTS_POLICY_VERSION = "validator-weights-v1"


def _safe_non_negative_number(value: Any, default: float = 0.0) -> float:
    """Return a finite, non-negative float without allowing corrupt weights to vote."""
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return numeric if math.isfinite(numeric) and numeric >= 0 else default


def validator_type_name(value: Any) -> str:
    try:
        return ValidatorType(int(value)).name
    except Exception:
        try:
            return ValidatorType[str(value)].name
        except Exception:
            return ValidatorType.LLM_MEMORY_VALIDATION.name


def _resolved_type_weight(validator_type: Any, validator_type_weights: Optional[dict]) -> float:
    name = validator_type_name(validator_type)
    if validator_type_weights:
        configured = validator_type_weights.get(name)
        if configured is None:
            configured = validator_type_weights.get(str(int(ValidatorType[name])))
        if configured is not None:
            return _safe_non_negative_number(configured)
    return _safe_non_negative_number(get_validator_type_weight(validator_type))


def validation_weight_snapshot(
    validator_config: Optional[dict],
    validator_type_weights: Optional[dict] = None,
) -> dict:
    """Freeze every input needed to reproduce a new validation's weight."""
    cfg = validator_config or {}
    config = cfg.get("config") or {}
    validator_type = cfg.get("validator_type") or config.get("type") or int(ValidatorType.LLM_MEMORY_VALIDATION)
    reputation = _safe_non_negative_number(cfg.get("reputation", 1.0))
    type_weight = _resolved_type_weight(validator_type, validator_type_weights)
    return {
        "validator_type": validator_type_name(validator_type),
        "validator_type_weight": type_weight,
        "reputation_at_validation": reputation,
        "effective_weight": _safe_non_negative_number(type_weight * reputation),
        "weights_policy_version": WEIGHTS_POLICY_VERSION,
        "legacy_dynamic_weight": False,
    }


def validation_weight_detail(
    validator: str,
    validation: dict,
    get_cached_validator_config: Optional[Callable[[str], Optional[dict]]] = None,
    validator_type_weights: Optional[dict] = None,
) -> dict:
    validation = validation or {}
    payload = validation.get("payload") or {}
    cfg = validation.get("validator_config") or payload.get("validator_config")
    if not cfg:
        cfg = (get_cached_validator_config(validator) if get_cached_validator_config else {}) or {}
    config = cfg.get("config") or {}

    snapshot_effective_present = "effective_weight" in validation or "effective_weight" in payload
    snapshot_type_weight_present = "validator_type_weight" in validation or "validator_type_weight" in payload
    snapshot_reputation_present = "reputation_at_validation" in validation or "reputation_at_validation" in payload
    validator_type = (
        validation.get("validator_type")
        or payload.get("validator_type")
        or cfg.get("validator_type")
        or config.get("type")
        or int(ValidatorType.LLM_MEMORY_VALIDATION)
    )

    if snapshot_effective_present:
        type_weight = _safe_non_negative_number(validation.get("validator_type_weight", payload.get("validator_type_weight")))
        reputation = _safe_non_negative_number(validation.get("reputation_at_validation", payload.get("reputation_at_validation")))
        effective_weight = _safe_non_negative_number(validation.get("effective_weight", payload.get("effective_weight")))
        legacy_dynamic_weight = False
    elif snapshot_type_weight_present and snapshot_reputation_present:
        type_weight = _safe_non_negative_number(validation.get("validator_type_weight", payload.get("validator_type_weight")))
        reputation = _safe_non_negative_number(validation.get("reputation_at_validation", payload.get("reputation_at_validation")))
        effective_weight = _safe_non_negative_number(type_weight * reputation)
        legacy_dynamic_weight = False
    else:
        # Historical records did not freeze the configured type weight. Keep the
        # former lookup as an explicit compatibility path.
        reputation = _safe_non_negative_number(cfg.get("reputation", 1.0))
        type_weight = _resolved_type_weight(validator_type, validator_type_weights)
        effective_weight = _safe_non_negative_number(type_weight * reputation)
        legacy_dynamic_weight = True

    result = normalize_validation_result(validation.get("approval", payload.get("approval")))
    return {
        "validator": validator,
        "validator_type": validator_type_name(validator_type),
        "validator_type_weight": type_weight,
        "reputation": reputation,
        "reputation_at_validation": reputation,
        "effective_weight": effective_weight,
        "weights_policy_version": validation.get("weights_policy_version") or payload.get("weights_policy_version") or WEIGHTS_POLICY_VERSION,
        "legacy_dynamic_weight": legacy_dynamic_weight,
        "result": result,
        "description": validation.get("text", ""),
        "sources": validation.get("sources") or payload.get("sources") or [],
        "sources_declared": validation.get("sources_declared") or payload.get("sources_declared") or [],
        "evidence_used": validation.get("evidence_used") or payload.get("evidence_used") or [],
        "evidence_validation": validation.get("evidence_validation") or payload.get("evidence_validation"),
    }


def _rounded_distribution(raw_weight: dict) -> dict:
    true_weight = raw_weight["TRUE"]
    false_weight = raw_weight["FALSE"]
    unknown_weight = raw_weight["UNKNOWN"]
    decisive_weight = true_weight + false_weight
    completed_weight = decisive_weight + unknown_weight
    return {
        "raw_weight": {key: round(value, 12) for key, value in raw_weight.items()},
        "decisive_share": {
            "TRUE": round(true_weight / decisive_weight, 12) if decisive_weight > 0 else 0.0,
            "FALSE": round(false_weight / decisive_weight, 12) if decisive_weight > 0 else 0.0,
        },
        "decisive_coverage": round(decisive_weight / completed_weight, 12) if completed_weight > 0 else 0.0,
        "abstention_share": round(unknown_weight / completed_weight, 12) if completed_weight > 0 else 0.0,
        "decision_margin": round(abs(true_weight - false_weight) / decisive_weight, 12) if decisive_weight > 0 else 0.0,
    }


def calculate_assertion_result(
    assertion_id: str,
    validators_obj: dict,
    get_cached_validator_config: Optional[Callable[[str], Optional[dict]]] = None,
    validator_type_weights: Optional[dict] = None,
) -> dict:
    responses = sorted((validators_obj or {}).items(), key=lambda item: str(item[0]))
    completed = [
        (validator, validation or {})
        for validator, validation in responses
        if (validation or {}).get("execution_status") == "COMPLETED"
    ]
    failed = [
        validator
        for validator, validation in responses
        if (validation or {}).get("execution_status") == "ERROR"
    ]
    details = [
        validation_weight_detail(validator, validation, get_cached_validator_config, validator_type_weights)
        for validator, validation in completed
    ]
    raw_weight = {"TRUE": 0.0, "FALSE": 0.0, "UNKNOWN": 0.0}
    for detail in details:
        result_name = detail["result"]
        raw_weight[result_name] = _safe_non_negative_number(
            raw_weight[result_name] + detail["effective_weight"],
            raw_weight[result_name],
        )

    distribution = _rounded_distribution(raw_weight)
    true_weight = raw_weight["TRUE"]
    false_weight = raw_weight["FALSE"]
    decisive_weight = true_weight + false_weight
    completed_weight = decisive_weight + raw_weight["UNKNOWN"]
    decisive_coverage = decisive_weight / completed_weight if completed_weight > 0 else 0.0

    if not details:
        reason_code = "ALL_VALIDATIONS_FAILED" if responses and len(failed) == len(responses) else "NO_COMPLETED_VALIDATIONS"
        verdict, decision_status = "UNKNOWN", "NO_VALID_RESPONSES"
    elif decisive_weight == 0:
        verdict, decision_status, reason_code = "UNKNOWN", "INSUFFICIENT_EVIDENCE", "NO_DECISIVE_VALIDATIONS"
    elif decisive_coverage <= CONSENSUS_POLICY["min_decisive_coverage"]:
        verdict, decision_status, reason_code = "UNKNOWN", "INSUFFICIENT_EVIDENCE", "DECISIVE_COVERAGE_TOO_LOW"
    elif abs(true_weight - false_weight) <= CONSENSUS_POLICY["tie_epsilon"]:
        verdict, decision_status, reason_code = "UNKNOWN", "NO_CONSENSUS", "TRUE_FALSE_WEIGHT_TIE"
    elif false_weight == 0 and true_weight > 0:
        verdict, decision_status, reason_code = "TRUE", "CONSENSUS", "ALL_DECISIVE_AGREE_TRUE"
    elif true_weight == 0 and false_weight > 0:
        verdict, decision_status, reason_code = "FALSE", "CONSENSUS", "ALL_DECISIVE_AGREE_FALSE"
    elif true_weight > false_weight:
        verdict, decision_status, reason_code = "TRUE", "WEIGHTED_MAJORITY", "TRUE_WEIGHT_EXCEEDS_FALSE_WEIGHT"
    else:
        verdict, decision_status, reason_code = "FALSE", "WEIGHTED_MAJORITY", "FALSE_WEIGHT_EXCEEDS_TRUE_WEIGHT"

    decisive_count = sum(detail["result"] in {"TRUE", "FALSE"} for detail in details)
    abstention_count = sum(detail["result"] == "UNKNOWN" for detail in details)
    winner = verdict if verdict in {"TRUE", "FALSE"} else None
    return {
        "assertion_id": assertion_id,
        "verdict": verdict,
        "decision_status": decision_status,
        "reason_code": reason_code,
        "distribution": distribution,
        "counts": {
            "responses": len(responses),
            "completed": len(details),
            "decisive": decisive_count,
            "abstentions": abstention_count,
            "errors": len(failed),
        },
        "consensus_policy": dict(CONSENSUS_POLICY),
        "consensus_policy_version": CONSENSUS_POLICY["version"],
        # Compatibility aliases. `scores` now contains raw weights, not the old
        # per-response normalized values. `winner` is null for every non-decision.
        "scores": distribution["raw_weight"],
        "winner": winner,
        "validations_count": len(details),
        "responses_count": len(responses),
        "errors_count": len(failed),
        "excluded_validators": failed,
        "legacy_dynamic_weight": any(detail["legacy_dynamic_weight"] for detail in details),
        "details": details,
    }


def calculate_order_assertion_results(
    order: dict,
    get_cached_validator_config: Optional[Callable[[str], Optional[dict]]] = None,
    validator_type_weights: Optional[dict] = None,
) -> Dict[str, dict]:
    validations = order.get("validations") or {}
    assertion_ids = set(str(k) for k in validations.keys())
    for index, assertion in enumerate(order.get("assertions") or []):
        assertion_ids.add(str(assertion.get("idAssertion", index)))
    return {
        aid: calculate_assertion_result(
            aid,
            validations.get(aid, {}),
            get_cached_validator_config,
            validator_type_weights,
        )
        for aid in sorted(assertion_ids)
    }
