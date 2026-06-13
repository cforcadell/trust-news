from typing import Any, Callable, Dict, Optional

from common.models.async_models import ValidatorType, get_validator_type_weight, normalize_validation_result


def validator_type_name(value: Any) -> str:
    try:
        return ValidatorType(int(value)).name
    except Exception:
        return str(value or ValidatorType.LLM_MEMORY_VALIDATION.name)


def validation_weight_detail(
    validator: str,
    validation: dict,
    get_cached_validator_config: Optional[Callable[[str], Optional[dict]]] = None,
    validator_type_weights: Optional[dict] = None,
) -> dict:
    cfg = validation.get("validator_config") or (get_cached_validator_config(validator) if get_cached_validator_config else {}) or {}
    config = cfg.get("config") or {}
    validator_type = cfg.get("validator_type") or config.get("type") or int(ValidatorType.LLM_MEMORY_VALIDATION)
    reputation = float(cfg.get("reputation", 1.0) or 1.0)
    type_weight = get_validator_type_weight(validator_type, validator_type_weights)
    result = normalize_validation_result(validation.get("approval"))
    return {
        "validator": validator,
        "validator_type": validator_type_name(validator_type),
        "validator_type_weight": type_weight,
        "reputation": reputation,
        "effective_weight": type_weight * reputation,
        "result": result,
        "description": validation.get("text", ""),
        "sources": validation.get("sources") or (validation.get("payload") or {}).get("sources") or [],
        "evidence_used": validation.get("evidence_used") or (validation.get("payload") or {}).get("evidence_used") or [],
    }


def calculate_assertion_result(
    assertion_id: str,
    validators_obj: dict,
    get_cached_validator_config: Optional[Callable[[str], Optional[dict]]] = None,
    validator_type_weights: Optional[dict] = None,
) -> dict:
    details = [
        validation_weight_detail(validator, validation or {}, get_cached_validator_config, validator_type_weights)
        for validator, validation in (validators_obj or {}).items()
    ]
    scores = {"TRUE": 0.0, "FALSE": 0.0, "UNKNOWN": 0.0}
    count = len(details)
    if count == 0:
        return {"assertion_id": assertion_id, "scores": scores, "winner": "UNKNOWN", "validations_count": 0, "details": []}
    for detail in details:
        scores[detail["result"]] = scores.get(detail["result"], 0.0) + detail["effective_weight"] / count
    winner = max(scores.items(), key=lambda item: item[1])[0] if any(scores.values()) else "UNKNOWN"
    return {
        "assertion_id": assertion_id,
        "scores": {k: round(v, 4) for k, v in scores.items()},
        "winner": winner,
        "validations_count": count,
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
