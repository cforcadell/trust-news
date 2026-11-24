"""Shared, side-effect-free rules for validation order completion."""

from datetime import datetime, timedelta, timezone


AUTOMATIC_STATUS = "VALIDATED_AUTOMATICALLY"
PENDING_STATUS = "VALIDATION_PENDING"


def expected_pairs(order: dict) -> set[tuple[str, str]]:
    pairs = set()
    for assertion in order.get("validators") or []:
        assertion_id = str(assertion.get("idAssertion"))
        for validator in assertion.get("validatorAddresses") or []:
            validator_id = validator.get("address") if isinstance(validator, dict) else validator
            if validator_id:
                pairs.add((assertion_id, str(validator_id)))
    return pairs


def missing_pairs(order: dict, validations: dict | None = None) -> set[tuple[str, str]]:
    actual = validations if validations is not None else (order.get("validations") or {})
    received = {
        (str(assertion_id), str(validator_id))
        for assertion_id, validator_results in actual.items()
        for validator_id in validator_results
    }
    return expected_pairs(order) - received


def completed_status(validations: dict) -> str:
    has_errors = any(
        result.get("execution_status") == "ERROR"
        for validator_results in validations.values()
        for result in validator_results.values()
    )
    return "VALIDATED_WITH_ERRORS" if has_errors else "VALIDATED"


def deadline_fields(minutes: int, now: datetime | None = None) -> dict:
    if minutes <= 0:
        return {}
    started = now or datetime.now(timezone.utc)
    return {
        "validation_started_at": started.isoformat(),
        "validation_deadline_at": started + timedelta(minutes=minutes),
        "validation_deadline_minutes": minutes,
        "validation_revision": 0,
    }


def mongo_utc_datetime(value: datetime) -> datetime:
    """Motor returns UTC datetimes without tzinfo unless tz_aware is enabled."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
