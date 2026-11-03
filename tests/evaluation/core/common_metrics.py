"""Deterministic assertion matching shared with the historical benchmark."""

import re
from typing import Any

VERDICTS = {0: "UNKNOWN", 1: "TRUE", 2: "FALSE"}
NUMBER = re.compile(r"\d+(?:(?:[.,]\d+)+)?")
NEGATION = {"no", "not", "never", "nunca", "jamás", "sin", "ningún", "ninguna"}
LEGAL_IDENTIFIER = re.compile(r"\b\d{4}\s*/\s*\d{1,4}\b")
PERCENTAGE = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(?:%|por\s+ciento\b)", re.IGNORECASE)
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
SPANISH_DATE = re.compile(
    r"\b(\d{1,2})\s+de\s+"
    r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)"
    r"\s+de\s+((?:19|20)\d{2})\b",
    re.IGNORECASE,
)
QUANTITY = re.compile(
    r"(?<!\d)(\d[\d.,]*)\s*"
    r"(habitantes?|diputad[oa]s?|escaños?|gwh|mwh|twh)\b",
    re.IGNORECASE,
)
MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}
UNIT_ALIASES = {
    "habitante": "habitantes", "habitantes": "habitantes",
    "diputado": "diputados", "diputada": "diputados", "diputados": "diputados", "diputadas": "diputados",
    "escaño": "diputados", "escaños": "diputados",
    "gwh": "gwh", "mwh": "mwh", "twh": "twh",
}
ABSOLUTE_SHARE = re.compile(
    r"\b(?:toda|todo|totalidad|íntegramente|integramente|completamente)\b",
    re.IGNORECASE,
)

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


def _number_value(value: str) -> float:
    """Parse the locale forms used by the gold corpus without guessing units."""
    raw = str(value).strip().replace(" ", "")
    if "," in raw and "." in raw:
        decimal = "," if raw.rfind(",") > raw.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        raw = raw.replace(thousands, "").replace(decimal, ".")
    elif raw.count(".") > 1:
        raw = raw.replace(".", "")
    elif raw.count(",") > 1:
        raw = raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", ".")
    return float(raw)


def assertion_anchors(text: str) -> dict[str, Any]:
    """Extract comparable factual anchors; values remain typed by their role."""
    value = str(text or "")
    legal_ids = {re.sub(r"\s+", "", match.group(0)) for match in LEGAL_IDENTIFIER.finditer(value)}
    dates = {
        f"{int(year):04d}-{MONTHS[month.lower()]:02d}-{int(day):02d}"
        for day, month, year in SPANISH_DATE.findall(value)
    }
    percentages = {_number_value(match) for match in PERCENTAGE.findall(value)}
    if ABSOLUTE_SHARE.search(value):
        percentages.add(100.0)
    quantities: dict[str, set[float]] = {}
    for raw_number, raw_unit in QUANTITY.findall(value):
        unit = UNIT_ALIASES[raw_unit.lower()]
        quantities.setdefault(unit, set()).add(_number_value(raw_number))
    # Identifiers and full dates already carry their own year semantics. Remove
    # them before collecting standalone years such as a reporting period.
    remainder = LEGAL_IDENTIFIER.sub(" ", value)
    remainder = SPANISH_DATE.sub(" ", remainder)
    years = {int(year) for year in YEAR.findall(remainder)}
    return {
        "legal_identifiers": legal_ids,
        "dates": dates,
        "years": years,
        "percentages": percentages,
        "quantities": quantities,
    }


def _serialized_anchors(anchors: dict[str, Any]) -> dict[str, Any]:
    return {
        "legal_identifiers": sorted(anchors["legal_identifiers"]),
        "dates": sorted(anchors["dates"]),
        "years": sorted(anchors["years"]),
        "percentages": sorted(anchors["percentages"]),
        "quantities": {key: sorted(values) for key, values in sorted(anchors["quantities"].items())},
    }


def anchor_conflicts(expected: dict[str, Any], actual_text: str) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    """Return typed conflicts and missing required anchors for assertion identity."""
    expected_anchors = assertion_anchors(expected.get("text") or "")
    actual_anchors = assertion_anchors(actual_text)
    required_anchors = assertion_anchors(" ".join(expected.get("required_terms") or []))
    reasons: list[str] = []
    labels = {
        "legal_identifiers": "LEGAL_IDENTIFIER",
        "dates": "DATE",
        "years": "YEAR",
        "percentages": "PERCENTAGE",
    }
    for key, label in labels.items():
        wanted = expected_anchors[key]
        observed = actual_anchors[key]
        if wanted and observed and wanted.isdisjoint(observed):
            reasons.append(f"{label}_CONFLICT")
        elif key == "years" and expected_anchors["dates"] and actual_anchors["dates"]:
            # A full-date comparison already accounts for its year. Required
            # terms commonly split "25 de mayo" and "2020" into two entries.
            continue
        elif required_anchors[key] and not (required_anchors[key] & observed):
            reasons.append(f"REQUIRED_{label}_MISSING")
    for unit, wanted in expected_anchors["quantities"].items():
        observed = actual_anchors["quantities"].get(unit, set())
        required = required_anchors["quantities"].get(unit, set())
        if wanted and observed and wanted.isdisjoint(observed):
            reasons.append(f"QUANTITY_CONFLICT:{unit}")
        elif required and not (required & observed):
            reasons.append(f"REQUIRED_QUANTITY_MISSING:{unit}")
    return list(dict.fromkeys(reasons)), _serialized_anchors(expected_anchors), _serialized_anchors(actual_anchors)


def numbers_in(text: str) -> list[float]:
    """Return locale-independent numbers observed in a piece of text."""
    return [_number_value(value) for value in NUMBER.findall(str(text or ""))]


def approximate_value_matches_text(spec: dict[str, Any], text: str) -> bool:
    """Evaluate an explicit dataset equivalence, never infer one implicitly."""
    value = float(spec["value"])
    tolerance = float(spec.get("tolerance", 0))
    if any(abs(observed - value) <= tolerance for observed in numbers_in(text)):
        return True
    words = normalized_words(text)
    return any(normalized_words(alias) <= words for alias in spec.get("aliases", []))


def missing_expected_numbers(expected: dict[str, Any], actual_text: str) -> list[str]:
    """Find missing literals while honoring annotated approximate equivalents."""
    actual_numbers = numbers_in(actual_text)
    equivalents = expected.get("approximate_values") or []
    missing = []
    for literal in NUMBER.findall(str(expected.get("text") or "")):
        value = _number_value(literal)
        if any(observed == value for observed in actual_numbers):
            continue
        applicable = [spec for spec in equivalents if float(spec["value"]) == value]
        if applicable and any(approximate_value_matches_text(spec, actual_text) for spec in applicable):
            continue
        missing.append(literal)
    return sorted(set(missing))


def match_incompatibilities(expected: dict[str, Any], actual_text: str) -> list[str]:
    """Return deterministic reasons why a lexical match must not inherit gold."""
    reasons, _, _ = anchor_conflicts(expected, actual_text)
    expected_negation = normalized_words(expected.get("text") or "") & NEGATION
    actual_negation = normalized_words(actual_text) & NEGATION
    if bool(expected_negation) != bool(actual_negation):
        reasons.append("NEGATION_POLARITY_CONFLICT")
    return reasons


def evidence_verdict_coherence(expected: dict[str, Any], assertion_text: str,
                               bundle: list[dict[str, Any]], verdict: str | None) -> dict[str, Any]:
    """Detect contradictions backed by explicit numeric-equivalence annotations."""
    specs = expected.get("approximate_values") or []
    if expected.get("expected_verdict") != "TRUE" or verdict != "FALSE" or not specs:
        return {"status": "NOT_EVALUATED"}
    contexts = [str(context.get("text") or "") for source in bundle if isinstance(source, dict)
                for context in source.get("contexts") or [] if isinstance(context, dict)
                and context.get("citation_eligible") is True]
    matches = []
    for spec in specs:
        if approximate_value_matches_text(spec, assertion_text) and any(
                approximate_value_matches_text(spec, context) for context in contexts):
            matches.append({"value": spec["value"], "tolerance": spec.get("tolerance", 0),
                            "aliases": spec.get("aliases", [])})
    return ({"status": "VERDICT_EVIDENCE_CONTRADICTION", "matches": matches}
            if matches else {"status": "NOT_EVALUATED"})


def assertion_identifier(assertion: dict[str, Any], index: int) -> str:
    return str(
        assertion.get("idAssertion")
        or assertion.get("assertion_id")
        or assertion.get("id")
        or index + 1
    )


def match_assertions(case: dict[str, Any], generated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    threshold = float(case.get("match_threshold") or 0.5)
    candidates: list[tuple[float, int, int, list[str]]] = []
    for expected_index, expected in enumerate(case["assertions"]):
        reference = " ".join(expected.get("required_terms", [])) or str(expected.get("text") or "")
        required = normalized_words(reference)
        for generated_index, actual in enumerate(generated):
            words = normalized_words(str(actual.get("text") or actual.get("assertion") or ""))
            score = len(required & words) / len(required) if required else 0.0
            candidates.append((score, expected_index, generated_index,
                               match_incompatibilities(expected, str(actual.get("text") or actual.get("assertion") or ""))))
    used_expected: set[int] = set()
    used_generated: set[int] = set()
    matches: list[dict[str, Any]] = []
    for score, expected_index, generated_index, incompatibilities in sorted(
            candidates, key=lambda row: (bool(row[3]), -row[0], row[1], row[2])):
        if score < threshold or expected_index in used_expected or generated_index in used_generated:
            continue
        used_expected.add(expected_index)
        used_generated.add(generated_index)
        expected = case["assertions"][expected_index]
        actual = generated[generated_index]
        expected_anchors = assertion_anchors(expected.get("text") or "")
        actual_anchors = assertion_anchors(str(actual.get("text") or actual.get("assertion") or ""))
        expected_categories = {int(value) for value in expected.get("category_ids") or []}
        actual_category = actual.get("categoryId")
        if actual_category is None:
            actual_category = actual.get("category_id")
        matches.append({
            "expected_id": expected["id"],
            "expected_verdict": normalize_verdict(expected["expected_verdict"]),
            "expected_category_ids": sorted(expected_categories),
            "generated_index": generated_index,
            "generated_id": assertion_identifier(actual, generated_index),
            "generated_text": actual.get("text") or actual.get("assertion"),
            "generated_category_id": actual_category,
            "match_score": round(score, 6),
            "required_term_coverage": round(score, 6),
            "match_status": "INCOMPATIBLE" if incompatibilities else "HEURISTIC_MATCH",
            "semantic_match_status": "INCOMPATIBLE" if incompatibilities else "COMPATIBLE",
            "anchor_match": not incompatibilities,
            "expected_anchors": _serialized_anchors(expected_anchors),
            "generated_anchors": _serialized_anchors(actual_anchors),
            "anchor_conflicts": incompatibilities,
            "incompatibility_reasons": incompatibilities,
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
