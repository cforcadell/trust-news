"""Deterministic assertion matching shared with the historical benchmark."""

import re
from typing import Any

VERDICTS = {0: "UNKNOWN", 1: "TRUE", 2: "FALSE"}

def normalize_verdict(value: Any) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int) and value in VERDICTS:
        return VERDICTS[value]
    text = str(value or "").strip().upper()
    aliases = {
        "0": "UNKNOWN", "1": "TRUE", "2": "FALSE",
        "VERDADERO": "TRUE", "FALSO": "FALSE", "DESCONOCIDO": "UNKNOWN",
    }
    return aliases.get(text, text if text in {"TRUE", "FALSE", "UNKNOWN"} else "UNKNOWN")


def collect_assertions(order: dict[str, Any]) -> list[dict[str, Any]]:
    for candidate in (
        order.get("assertions"),
        (order.get("document") or {}).get("assertions"),
        (order.get("assertions_document") or {}).get("assertions"),
    ):
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    return []


def normalized_words(text: str) -> set[str]:
    normalized = text.lower()
    substitutions = str.maketrans("áéíóúüñ", "aeiouun")
    normalized = normalized.translate(substitutions)
    return set(re.findall(r"[a-z0-9]+", normalized))


def assertion_identifier(assertion: dict[str, Any], index: int) -> str:
    return str(
        assertion.get("idAssertion")
        or assertion.get("assertion_id")
        or assertion.get("id")
        or index + 1
    )


def match_assertions(case: dict[str, Any], generated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    threshold = float(case.get("match_threshold") or 0.5)
    candidates: list[tuple[float, int, int]] = []
    for expected_index, expected in enumerate(case["assertions"]):
        required = normalized_words(" ".join(expected.get("required_terms", [])))
        for generated_index, actual in enumerate(generated):
            words = normalized_words(str(actual.get("text") or actual.get("assertion") or ""))
            score = len(required & words) / len(required) if required else 0.0
            candidates.append((score, expected_index, generated_index))
    used_expected: set[int] = set()
    used_generated: set[int] = set()
    matches: list[dict[str, Any]] = []
    for score, expected_index, generated_index in sorted(candidates, reverse=True):
        if score < threshold or expected_index in used_expected or generated_index in used_generated:
            continue
        used_expected.add(expected_index)
        used_generated.add(generated_index)
        expected = case["assertions"][expected_index]
        actual = generated[generated_index]
        expected_categories = {int(value) for value in expected.get("category_ids") or []}
        actual_category = actual.get("categoryId") or actual.get("category_id")
        matches.append({
            "expected_id": expected["id"],
            "expected_verdict": normalize_verdict(expected["expected_verdict"]),
            "expected_category_ids": sorted(expected_categories),
            "generated_index": generated_index,
            "generated_id": assertion_identifier(actual, generated_index),
            "generated_text": actual.get("text") or actual.get("assertion"),
            "generated_category_id": actual_category,
            "match_score": round(score, 6),
            "category_match": (
                int(actual_category) in expected_categories
                if actual_category is not None and expected_categories else None
            ),
        })
    return sorted(matches, key=lambda item: item["expected_id"])


def result_for_assertion(order: dict[str, Any], assertion_id: str) -> dict[str, Any] | None:
    results = order.get("assertion_results") or {}
    if isinstance(results, dict):
        value = results.get(assertion_id)
        if isinstance(value, dict):
            return value
    if isinstance(results, list):
        for value in results:
            if isinstance(value, dict) and str(value.get("assertion_id")) == assertion_id:
                return value
    return None


def validation_records(order: dict[str, Any], assertion_id: str) -> list[tuple[str, dict[str, Any]]]:
    validations = order.get("validations") or {}
    rows = validations.get(assertion_id) if isinstance(validations, dict) else None
    if isinstance(rows, dict):
        return [(str(key), value) for key, value in rows.items() if isinstance(value, dict)]
    if isinstance(rows, list):
        return [
            (str(value.get("idValidator") or value.get("validator_id") or index), value)
            for index, value in enumerate(rows) if isinstance(value, dict)
        ]
    return []

