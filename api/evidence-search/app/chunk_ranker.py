import math
import re
from typing import Any, Dict, List

try:
    from rank_bm25 import BM25Okapi
except Exception:  # pragma: no cover - dependency is installed in the service image.
    BM25Okapi = None


TOKEN_RE = re.compile(r"[\wÀ-ÿ]+", re.UNICODE)
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _tokens(text: str) -> List[str]:
    return [token.lower() for token in TOKEN_RE.findall(str(text or ""))]


def _names(items: Any) -> List[str]:
    return [str(item.get("name") or "").strip() for item in items or [] if isinstance(item, dict) and str(item.get("name") or "").strip()]


def _values(items: Any) -> List[str]:
    return [str(item.get("value") or "").strip() for item in items or [] if isinstance(item, dict) and str(item.get("value") or "").strip()]


def ranking_query_parts(assertion: Dict[str, Any]) -> Dict[str, List[str]]:
    context = assertion.get("context") or {}
    hints = assertion.get("search_hints") or {}
    return {
        "text": [str(assertion.get("text") or "").strip()],
        "keywords": [str(item).strip() for item in hints.get("search_keywords") or [] if str(item).strip()],
        "suggested_queries": [str(item).strip() for item in hints.get("suggested_queries") or [] if str(item).strip()],
        "entities": _names(context.get("entities")),
        "locations": _names(context.get("locations")),
        "temporal": _values(context.get("temporal_context")),
    }


def build_ranking_query(assertion: Dict[str, Any]) -> str:
    parts = ranking_query_parts(assertion)
    values: List[str] = []
    for group in parts.values():
        values.extend(group)
    return " ".join(value for value in values if value)


def rank_chunks(assertion: Dict[str, Any], chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not chunks:
        return []

    query = build_ranking_query(assertion)
    query_tokens = _tokens(query)
    corpus = [_tokens(chunk.get("text", "")) for chunk in chunks]
    if BM25Okapi is not None and query_tokens and any(corpus):
        bm25 = BM25Okapi(corpus)
        lexical_scores = list(bm25.get_scores(query_tokens))
    else:
        lexical_scores = [_simple_overlap_score(query_tokens, tokens) for tokens in corpus]

    scored = []
    for chunk, lexical_score in zip(chunks, lexical_scores):
        signals = _matched_signals(assertion, chunk.get("text", ""))
        boost = _boost(signals)
        score = float(lexical_score or 0.0) + boost
        scored.append({
            **chunk,
            "score": round(score, 6),
            "matched_signals": signals,
            "ranking_reason": _ranking_reason(float(lexical_score or 0.0), signals),
        })

    scored.sort(key=lambda item: item["score"], reverse=True)
    if all(math.isclose(item["score"], 0.0) for item in scored):
        fallback = []
        for item in scored[: min(3, len(scored))]:
            fallback.append({
                **item,
                "score": 0.0,
                "ranking_reason": "low lexical coverage",
                "matched_signals": item.get("matched_signals") or [],
            })
        return fallback
    return scored


def _simple_overlap_score(query_tokens: List[str], chunk_tokens: List[str]) -> float:
    if not query_tokens or not chunk_tokens:
        return 0.0
    chunk_set = set(chunk_tokens)
    return float(sum(1 for token in query_tokens if token in chunk_set))


def _matched_signals(assertion: Dict[str, Any], text: str) -> List[str]:
    text_lower = str(text or "").lower()
    parts = ranking_query_parts(assertion)
    signals: List[str] = []

    if any(value.lower() in text_lower for value in parts["entities"]):
        signals.append("entity")
    if any(value.lower() in text_lower for value in parts["locations"]):
        signals.append("location")
    if any(value.lower() in text_lower for value in parts["temporal"]):
        signals.append("temporal")
    numbers = set(NUMBER_RE.findall(str(assertion.get("text") or "")))
    if numbers and any(number in text_lower for number in numbers):
        signals.append("number")
    if any(keyword.lower() in text_lower for keyword in parts["keywords"]):
        signals.append("keyword")
    return signals


def _boost(signals: List[str]) -> float:
    weights = {
        "entity": 1.5,
        "location": 1.0,
        "temporal": 1.2,
        "number": 1.0,
        "keyword": 0.5,
    }
    return sum(weights.get(signal, 0.0) for signal in signals)


def _ranking_reason(lexical_score: float, signals: List[str]) -> str:
    if lexical_score <= 0 and not signals:
        return "low lexical coverage"
    details = []
    if lexical_score > 0:
        details.append("bm25 lexical match")
    details.extend(f"{signal} boost" for signal in signals)
    return ", ".join(details)
