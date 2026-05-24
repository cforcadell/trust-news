from typing import Iterable, List

from common.models.async_models import ValidatorType


AUTOMATIC_VALIDATOR_TYPES = {
    ValidatorType.LLM_MEMORY_VALIDATION,
    ValidatorType.LLM_SEARCH_VALIDATION,
    ValidatorType.RAG_EVIDENCE_VALIDATION,
}


def is_validator_active(validator: dict) -> bool:
    config = validator.get("config") or {}
    status = config.get("status")
    return status in (None, 1, "1", "Registered", "registered")


def validator_supports_category(validator: dict, category_id: int) -> bool:
    categories = validator.get("categories") or []
    for category in categories:
        if isinstance(category, dict) and int(category.get("id", -1)) == int(category_id):
            return True
        try:
            if int(category) == int(category_id):
                return True
        except Exception:
            continue
    return False


def is_automatic_validator_config(validator: dict) -> bool:
    config = validator.get("config") or {}
    validator_type = validator.get("validator_type") or config.get("type") or int(ValidatorType.LLM_MEMORY_VALIDATION)
    try:
        return ValidatorType(int(validator_type)) in AUTOMATIC_VALIDATOR_TYPES
    except Exception:
        return True


def light_validators_for_category(validators: Iterable[dict], category_id: int) -> List[dict]:
    return [
        v for v in validators
        if v.get("validator") and is_validator_active(v) and is_automatic_validator_config(v) and validator_supports_category(v, category_id)
    ]
