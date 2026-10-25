import hashlib
import json
import logging
import os
import re
import sys
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from common.utils.evaluation_context import evaluation_context
from motor.motor_asyncio import AsyncIOMotorClient
from common.models.async_models import EvidenceSearchStrategy
from common.models.evidence_models import EvidenceSearchRequestV2, EvidenceSearchResponseV2
from common.routing_taxonomy import SourceType
from common.search.normalization import normalize_domain, normalize_url
from common.utils.evidence_bundle import evidence_bundle_hash
from common.utils.logging_utils import configure_single_line_json_logging
from common.utils.mongo import build_mongo_uri_from_env

sys.path.append(os.path.dirname(__file__))
from app.chunk_ranker import rank_chunks
from app.chunker import build_context_windows, chunk_text
from app.document_fetcher import classify_attempt_outcome, classify_fetch_outcome, fetch_main_text
from common.search import search_with_provider

load_dotenv()

log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
configure_single_line_json_logging(log_level)
logger = logging.getLogger("evidence-search")

MONGO_URI = build_mongo_uri_from_env()
MONGO_DBNAME = os.getenv("MONGO_DBNAME", "newsdb")
MONGO_CACHE_COLLECTION = os.getenv("EVIDENCE_SEARCH_CACHE_COLLECTION", "evidence_search_cache_v2")
MONGO_UNUSABLE_URL_COLLECTION = os.getenv(
    "EVIDENCE_UNUSABLE_URL_COLLECTION", "evidence_unusable_urls_v1",
)
EVIDENCE_SEARCH_CACHE_TTL_SECONDS = int(os.getenv("EVIDENCE_SEARCH_CACHE_TTL_SECONDS", "86400"))
EVIDENCE_SEARCH_TRANSIENT_FAILURE_TTL_SECONDS = int(os.getenv("EVIDENCE_SEARCH_TRANSIENT_FAILURE_TTL_SECONDS", "300"))
EVIDENCE_SEARCH_UNUSABLE_TTL_SECONDS = int(os.getenv("EVIDENCE_SEARCH_UNUSABLE_TTL_SECONDS", "1800"))

SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "").lower() or None
EVIDENCE_FETCH_FULL_TEXT = os.getenv("EVIDENCE_FETCH_FULL_TEXT", "false").lower() == "true"
EVIDENCE_MAX_CONTEXTS_PER_SOURCE = int(os.getenv("EVIDENCE_MAX_CONTEXTS_PER_SOURCE", "2"))
EVIDENCE_MAX_CONTEXTS_TOTAL = int(os.getenv("EVIDENCE_MAX_CONTEXTS_TOTAL", "8"))
EVIDENCE_CHUNK_SIZE_CHARS = int(os.getenv("EVIDENCE_CHUNK_SIZE_CHARS", "1200"))
EVIDENCE_CHUNK_OVERLAP_CHARS = int(os.getenv("EVIDENCE_CHUNK_OVERLAP_CHARS", "200"))
EVIDENCE_CONTEXT_WINDOW_BEFORE = int(os.getenv("EVIDENCE_CONTEXT_WINDOW_BEFORE", "1"))
EVIDENCE_CONTEXT_WINDOW_AFTER = int(os.getenv("EVIDENCE_CONTEXT_WINDOW_AFTER", "1"))
EVIDENCE_HTTP_TIMEOUT = float(os.getenv("EVIDENCE_HTTP_TIMEOUT", "10"))
EVIDENCE_MIN_CONTEXT_CHARS = int(os.getenv("EVIDENCE_MIN_CONTEXT_CHARS", "120"))
EVIDENCE_USER_AGENT = os.getenv("EVIDENCE_USER_AGENT", "TrustNewsEvidenceBot/1.0")
EVIDENCE_MAX_QUERY_RELAXATION_ATTEMPTS = int(os.getenv("EVIDENCE_MAX_QUERY_RELAXATION_ATTEMPTS", "3"))
EVIDENCE_MAX_RESULTS_PER_DOMAIN = int(os.getenv("EVIDENCE_MAX_RESULTS_PER_DOMAIN", "2"))
EVIDENCE_CANDIDATE_MULTIPLIER = max(1, int(os.getenv("EVIDENCE_CANDIDATE_MULTIPLIER", "3")))
EVIDENCE_TARGET_CITABLE_SOURCES = max(1, int(os.getenv("EVIDENCE_TARGET_CITABLE_SOURCES", "1")))
UNUSABLE_URL_TTL_SECONDS = int(os.getenv("EVIDENCE_UNUSABLE_URL_TTL_SECONDS", "3600"))
UNUSABLE_URL_MAX_ENTRIES = int(os.getenv("EVIDENCE_UNUSABLE_URL_MAX_ENTRIES", "1024"))
UNUSABLE_OUTCOME_TTLS = {
    "PENDING": int(os.getenv("EVIDENCE_UNUSABLE_PENDING_TTL_SECONDS", "120")),
    "ACCESS_DENIED": int(os.getenv("EVIDENCE_UNUSABLE_ACCESS_DENIED_TTL_SECONDS", "1800")),
    "RATE_LIMITED": int(os.getenv("EVIDENCE_UNUSABLE_RATE_LIMITED_TTL_SECONDS", "120")),
    "SERVER_FAILURE": int(os.getenv("EVIDENCE_UNUSABLE_SERVER_FAILURE_TTL_SECONDS", "120")),
    "NETWORK_FAILURE": int(os.getenv("EVIDENCE_UNUSABLE_NETWORK_FAILURE_TTL_SECONDS", "120")),
    "EMPTY_CONTENT": int(os.getenv("EVIDENCE_UNUSABLE_EMPTY_CONTENT_TTL_SECONDS", "1800")),
    "NOT_FOUND": int(os.getenv("EVIDENCE_UNUSABLE_NOT_FOUND_TTL_SECONDS", "3600")),
}
UNUSABLE_HISTORY_SUCCESS_TTL_SECONDS = int(
    os.getenv("EVIDENCE_UNUSABLE_SUCCESS_HISTORY_TTL_SECONDS", "86400")
)
UNUSABLE_HISTORY_POLICY = os.getenv("EVIDENCE_UNUSABLE_HISTORY_POLICY", "fetch-outcomes-v1")
_recent_unusable_urls: Dict[str, float] = {}

QUERY_OPERATIONAL_TERMS = {
    "comprobar", "comprobacion", "confirmar", "confirmacion", "evidencia", "evidencias",
    "factcheck", "fuente", "fuentes", "oficial", "oficiales", "verificacion", "verificar",
    "check", "evidence", "official", "source", "sources", "verification", "verify",
}
QUERY_CLAIM_QUALIFIERS = {
    "alcanzo", "alcanzó", "cerró", "cerro", "exclusivamente", "exactamente", "genero", "generó",
    "inferior", "negativa", "negativo", "solamente", "solo", "superior", "supero", "superó",
    "totalmente", "únicamente", "unicamente",
}
QUERY_STOPWORDS = {
    "a", "al", "and", "con", "de", "del", "durante", "el", "en", "la", "las", "los",
    "mediante", "of", "según", "segun", "the", "una", "un", "y",
}

OFFICIAL_SOURCE_TYPES = {
    SourceType.STATISTICAL_OFFICE,
    SourceType.CENTRAL_BANK,
    SourceType.GOVERNMENT_AGENCY,
    SourceType.OFFICIAL_GAZETTE,
    SourceType.LEGISLATURE,
    SourceType.COURT,
    SourceType.REGULATOR,
    SourceType.ELECTORAL_AUTHORITY,
    SourceType.PUBLIC_HEALTH_AUTHORITY,
    SourceType.INTERGOVERNMENTAL_ORGANIZATION,
}


app = FastAPI(title="TrustNews Evidence Search")
mongo_client: Optional[AsyncIOMotorClient] = None
db = None
cache_collection = None
unusable_url_collection = None



def _fold_query_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _query_tokens(value: Any) -> set[str]:
    """Return lexical tokens used to avoid overweighting repeated query context."""
    return set(re.findall(r"\w+|%", _fold_query_text(value), flags=re.UNICODE))


def _dedupe_similar_queries(queries: List[str], similarity_threshold: float = 0.8) -> List[str]:
    """Preserve query diversity while dropping exact and near-identical variants."""
    selected: List[str] = []
    selected_tokens: List[set[str]] = []
    for query in queries:
        tokens = _query_tokens(query)
        if not tokens:
            continue
        if any(len(tokens & prior) / len(tokens | prior) >= similarity_threshold for prior in selected_tokens):
            continue
        selected.append(query)
        selected_tokens.append(tokens)
    return selected


def _origin_rank(item: Dict[str, Any]) -> int:
    origin = str(item.get("origin") or "unknown").strip().lower()
    if origin == "explicit":
        return 0
    if origin == "inferred":
        return 1
    return 2


def _context_values(items: Any, field: str) -> List[str]:
    values: List[tuple[int, str]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        value = str(item.get(field) or "").strip()
        if value and value.lower() != "unknown":
            values.append((_origin_rank(item), value))
    values.sort(key=lambda pair: pair[0])

    deduped: List[str] = []
    seen = set()
    for _, value in values:
        folded = _fold_query_text(value)
        if folded not in seen:
            deduped.append(value)
            seen.add(folded)
    return deduped


def contextual_query_terms(assertion: Dict[str, Any]) -> List[str]:
    """Return assertion context terms ordered so explicit context outranks inferred context."""
    hints = assertion.get("search_hints") or {}
    context = assertion.get("context") or {}
    terms: List[str] = []

    # Time is usually the highest-impact disambiguator for evidence search.
    terms.extend(_context_values(context.get("temporal_context"), "value"))
    terms.extend(_context_values(context.get("entities"), "name"))
    terms.extend(_context_values(context.get("locations"), "name"))
    terms.extend(str(item).strip() for item in hints.get("search_keywords") or [] if str(item).strip())

    deduped: List[str] = []
    seen = set()
    for term in terms:
        folded = _fold_query_text(term)
        if folded and folded not in seen:
            deduped.append(term)
            seen.add(folded)
    return deduped


def enrich_query_with_context(query: str, assertion: Dict[str, Any], max_terms: int = 8) -> str:
    """Append only contextual words absent from a provider query."""
    query = str(query or "").strip()
    query_tokens = _query_tokens(query)
    missing: List[str] = []
    for term in contextual_query_terms(assertion):
        # A phrase such as "población España 2025" is already represented when
        # its individual terms are in the suggestion, even if word order differs.
        for token in re.findall(r"\w+|%", term, flags=re.UNICODE):
            folded_token = _fold_query_text(token)
            if folded_token and folded_token not in query_tokens:
                missing.append(token)
                query_tokens.add(folded_token)
    if not missing:
        return query
    suffix = " ".join(missing[:max_terms])
    return " ".join(part for part in [query, suffix] if part).strip()


def base_queries_for_assertion(assertion: Dict[str, Any]) -> List[str]:
    """Build initial search queries from assertion hints and contextual metadata."""
    # Prefer explicit search suggestions because they are already optimized upstream.
    hints = assertion.get("search_hints") or {}
    base_queries = [str(q).strip() for q in hints.get("suggested_queries") or [] if str(q).strip()]

    # Suggested queries must still carry assertion context so providers can disambiguate.
    if base_queries:
        base_queries = [enrich_query_with_context(query, assertion) for query in base_queries]
    else:
        terms = [assertion.get("text", "")] + contextual_query_terms(assertion)
        base = " ".join(str(t).strip() for t in terms if str(t).strip())
        base_queries = [base] if base else [assertion.get("text", "")]

    # Keep paraphrases only when they carry materially different retrieval terms.
    return _dedupe_similar_queries(base_queries)


def _relax_query_text(query: str) -> str:
    """Remove retrieval instructions, disputed qualifiers and non-year quantities."""
    relaxed = []
    for token in re.findall(r"[^\W_]+|%", str(query or ""), flags=re.UNICODE):
        folded = _fold_query_text(token)
        if folded in QUERY_OPERATIONAL_TERMS or folded in QUERY_CLAIM_QUALIFIERS or folded in QUERY_STOPWORDS:
            continue
        if token == "%" or (token.isdigit() and not re.fullmatch(r"(?:19|20)\d{2}", token)):
            continue
        relaxed.append(token)
    return " ".join(relaxed)


def relaxed_query_variants(assertion: Dict[str, Any], exact_queries: List[str]) -> List[Dict[str, Any]]:
    """Build a bounded, deterministic query ladder from generator-provided hints."""
    hints = assertion.get("search_hints") or {}
    candidates = [
        *[str(value) for value in hints.get("suggested_queries") or []],
        *[str(value) for value in hints.get("search_keywords") or []],
        str(assertion.get("text") or ""),
    ]
    exact_tokens = _query_tokens(exact_queries[0]) if exact_queries else set()
    anchors = []
    context = assertion.get("context") or {}
    anchors.extend(_context_values(context.get("locations"), "name"))
    anchors.extend(_context_values(context.get("entities"), "name"))
    anchors.extend(_context_values(context.get("temporal_context"), "value"))
    anchor_tokens = {token for value in anchors for token in _query_tokens(value)}

    relaxed_queries = []
    for candidate in candidates:
        relaxed = _relax_query_text(candidate)
        tokens = _query_tokens(relaxed)
        # Preserve explicit disambiguators and require at least one topical term.
        if not tokens or (anchor_tokens and not anchor_tokens.issubset(tokens)):
            continue
        if not (tokens - anchor_tokens):
            continue
        if exact_tokens and tokens == exact_tokens:
            continue
        relaxed_queries.append(relaxed)

    selected = _dedupe_similar_queries(relaxed_queries, similarity_threshold=0.8)
    selected.sort(key=lambda value: (len(_query_tokens(value)), relaxed_queries.index(value)))
    variants = []
    for level, query in enumerate(selected[:max(0, EVIDENCE_MAX_QUERY_RELAXATION_ATTEMPTS)], start=1):
        query_tokens = _query_tokens(query)
        variants.append({
            "query": query,
            "relaxation_level": level,
            "relaxation_reason": "INITIAL_QUERY_EMPTY",
            "removed_terms": sorted(exact_tokens - query_tokens),
        })
    return variants


def _policy_value(policy: Any, name: str, default: Any = None) -> Any:
    return policy.get(name, default) if isinstance(policy, dict) else getattr(policy, name, default)


def _search_request_plan(assertion: Dict[str, Any], domain_resolution: Dict[str, Any], policy) -> Dict[str, Any]:
    """Create the structured search plan shared by query logging and execution."""
    # Limit query fan-out according to the active evidence-search policy.
    base_queries = base_queries_for_assertion(assertion)
    query_limit = max(1, int(_policy_value(policy, "max_queries", 1) or 1))
    base_queries = base_queries[:query_limit]

    # Group preferred domains by query so providers can receive include-domain filters.
    grouped: Dict[str, List[str]] = {}
    for domain_cfg in domain_resolution.get("preferred_sources") or []:
        domain = str(domain_cfg.get("domain") or "").strip()
        if not domain:
            continue
        for query in base_queries:
            grouped.setdefault(query, [])
            if domain not in grouped[query]:
                grouped[query].append(domain)

    strategy = strategy_for_policy(policy)

    # Build the preferred-domain requests first, preserving the router priority.
    requests = []
    if strategy == EvidenceSearchStrategy.LOCAL:
        for query in base_queries:
            domains = grouped.get(query, [])
            requests.append({
                "query": query,
                "include_domains": domains,
                "mode": "local_routed",
                "external_source_policy": "none",
                "relaxation_level": 0,
                "relaxation_reason": None,
                "removed_terms": [],
            })

    if strategy in {EvidenceSearchStrategy.EXT_OFFICIAL_FIRST, EvidenceSearchStrategy.EXT_ONLY_OFFICIAL}:
        external_source_policy = (
            "official_first"
            if strategy == EvidenceSearchStrategy.EXT_OFFICIAL_FIRST
            else "only_official"
        )
        request_mode = (
            "external_official_first"
            if strategy == EvidenceSearchStrategy.EXT_OFFICIAL_FIRST
            else "external_only_official"
        )
        for query in base_queries:
            requests.append({
                "query": query,
                "include_domains": None,
                "mode": request_mode,
                "external_source_policy": external_source_policy,
                "relaxation_level": 0,
                "relaxation_reason": None,
                "removed_terms": [],
            })

    if strategy == EvidenceSearchStrategy.EXT_OFFICIAL_FIRST:
        for query in base_queries:
            requests.append({
                "query": query,
                "include_domains": None,
                "mode": "general_fallback",
                "external_source_policy": "none",
                "relaxation_level": 0,
                "relaxation_reason": None,
                "removed_terms": [],
            })

    # Conditional requests are executed only while no candidate has survived
    # the active domain/source policy.
    for variant in relaxed_query_variants(assertion, base_queries):
        if strategy == EvidenceSearchStrategy.LOCAL:
            requests.append({
                **variant,
                "include_domains": grouped.get(base_queries[0], []) if base_queries else [],
                "mode": "local_routed_relaxed",
                "external_source_policy": "none",
            })
        elif strategy == EvidenceSearchStrategy.EXT_ONLY_OFFICIAL:
            requests.append({
                **variant,
                "include_domains": None,
                "mode": "external_only_official_relaxed",
                "external_source_policy": "only_official",
            })
        elif strategy == EvidenceSearchStrategy.EXT_OFFICIAL_FIRST:
            requests.extend([
                {**variant, "include_domains": None, "mode": "external_official_first_relaxed",
                 "external_source_policy": "official_first"},
                {**variant, "include_domains": None, "mode": "general_fallback_relaxed",
                 "external_source_policy": "none"},
            ])

    # Return both the normalized base queries and the executable request plan for callers/tests.
    return {"base_queries": base_queries, "requests": requests}


def build_queries_v2(assertion: Dict[str, Any], domain_resolution: Dict[str, Any], policy) -> List[str]:
    """Render the structured search plan as human-readable query strings."""
    # Reuse the canonical request plan so operator-facing logs mirror execution.
    plan = _search_request_plan(assertion, domain_resolution, policy)
    queries: List[str] = []

    # Preferred-domain requests are displayed as site: queries for easy operator inspection.
    for request in plan["requests"]:
        query = request["query"]
        if request["mode"] == "local_routed":
            domains = [str(domain).strip() for domain in request.get("include_domains") or [] if str(domain).strip()]
            if domains:
                if len(domains) == 1:
                    queries.append(f"site:{domains[0]} {query}".strip())
                else:
                    site_terms = " OR ".join(f"site:{domain}" for domain in domains)
                    queries.append(f"({site_terms}) {query}".strip())
            else:
                queries.append(query)
        else:
            queries.append(query)

    # Keep the operator-facing representation separate from provider requests.
    return queries


def build_search_requests(assertion: Dict[str, Any], domain_resolution: Dict[str, Any], policy) -> List[Dict[str, Any]]:
    """Return provider-ready search requests with optional domain filters."""
    # The endpoint executes this structured representation instead of parsing site: strings.
    return _search_request_plan(assertion, domain_resolution, policy)["requests"]


def evidence_from_source_v2(
    source: Dict[str, Any],
    rank: int,
    domain_resolution: Dict[str, Any],
    origin_document: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Normalize a raw provider result into the evidence-search response schema."""
    # Extract and normalize the domain so it can be matched against router metadata.
    url = source.get("url") or ""
    domain = normalize_domain(urlparse(url).netloc)
    matched = next((d for d in domain_resolution.get("preferred_sources", []) if d.get("domain") == domain), {})

    # Use router source metadata when available, otherwise fall back to domain heuristics.
    source_type = matched.get("source_type") or source_type_for_domain(domain)
    route_score = float(matched.get("route_score", 0.3) or 0.3)
    origin_document = origin_document or {}
    origin_url = normalize_url(origin_document.get("url") or "")
    origin_domain = normalize_domain(origin_document.get("domain") or origin_url)
    if origin_url and normalize_url(url) == origin_url:
        relationship_to_origin = "ORIGINAL"
    elif origin_domain and domain == origin_domain:
        relationship_to_origin = "UNKNOWN"
    else:
        relationship_to_origin = "INDEPENDENT"

    # Preserve useful provider text and add stable ids for downstream validator prompts.
    evidence = {
        "source_id": f"source-{rank}",
        "title": source.get("title") or url,
        "url": url,
        "domain": domain,
        "source_type": source_type,
        "snippet": source.get("content") or source.get("snippet") or useful_excerpt(source),
        "rank": rank,
        "authority_level": matched.get("authority_level", "UNKNOWN"),
        "route_score": route_score,
        "retrieved_at": iso(utc_now()),
        "why_selected": matched.get("reason") or "Matched contextual search policy",
        "profile_version": matched.get("profile_version"),
        "document_type": "UNKNOWN",
        "relationship_to_origin": relationship_to_origin,
    }
    return evidence


def source_type_for_domain(domain: str) -> str:
    """Infer a broad source type when no profile metadata matched the domain."""
    # Normalize before marker checks so provider URL variations do not change classification.
    d = normalize_domain(domain)
    statistical_domains = ("ine.es", "idescat.cat")
    intergovernmental_domains = ("europa.eu", "who.int", "un.org", "oecd.org", "worldbank.org", "imf.org")
    government_domains = ("gencat.cat",)
    agencies = ("reuters.com", "apnews.com", "afp.com", "efe.com", "bloomberg.com")

    def belongs_to(domains: tuple[str, ...]) -> bool:
        return any(d == item or d.endswith(f".{item}") for item in domains)

    # Apply a simple taxonomy used as a fallback trust signal.
    official_suffix = re.search(r"\.(?:gov|gob|gouv|go)(?:\.[a-z]{2})?$", d)
    if belongs_to(statistical_domains):
        return SourceType.STATISTICAL_OFFICE.value
    if belongs_to(intergovernmental_domains):
        return SourceType.INTERGOVERNMENTAL_ORGANIZATION.value
    if official_suffix or belongs_to(government_domains):
        return SourceType.GOVERNMENT_AGENCY.value
    if belongs_to(agencies):
        return SourceType.NEWS_AGENCY.value
    if d:
        return SourceType.MEDIA.value
    return SourceType.UNKNOWN.value


def is_official_source_type(value: str) -> bool:
    try:
        return SourceType(value) in OFFICIAL_SOURCE_TYPES
    except ValueError:
        return False


def is_same_domain_family(domain: str, other: str) -> bool:
    """Match a domain and its subdomains when suppressing a failed site."""
    domain = normalize_domain(domain)
    other = normalize_domain(other)
    return bool(domain and other and (domain == other or domain.endswith(f".{other}") or other.endswith(f".{domain}")))


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    # Centralize time creation so cache timestamps use the same timezone convention.
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    """Serialize datetimes as UTC ISO-8601 strings."""
    # Normalize any aware datetime to UTC before exposing it in API responses.
    return dt.astimezone(timezone.utc).isoformat()


def provider_trace_summary(requests: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize actual provider calls without counting planned/skipped requests."""
    calls = [item for item in requests if item.get("provider_call_id")]
    returned_urls = [
        normalize_url(url) or str(url)
        for item in calls
        for url in item.get("returned_urls") or []
        if str(url or "").strip()
    ]
    return {
        "calls_attempted": len(calls),
        "calls_succeeded": sum(item.get("status") == "EXECUTED" for item in calls),
        "calls_failed": sum(item.get("status") == "FAILED" for item in calls),
        "requests_skipped": sum(item.get("status") == "SKIPPED" for item in requests),
        "urls_returned": len(returned_urls),
        "unique_urls_returned": len(set(returned_urls)),
    }


def attach_provider_lineage(evidences: List[Dict[str, Any]], requests: List[Dict[str, Any]]) -> None:
    """Link every retained evidence URL to every provider call that returned it."""
    calls_by_url: Dict[str, List[str]] = {}
    for request in requests:
        call_id = request.get("provider_call_id")
        if not call_id:
            continue
        for result in request.get("result_decisions") or []:
            normalized = normalize_url(result.get("url") or "")
            if normalized and call_id not in calls_by_url.setdefault(normalized, []):
                calls_by_url[normalized].append(call_id)
    for evidence in evidences:
        call_ids = calls_by_url.get(normalize_url(evidence.get("url") or ""), [])
        evidence["provider_call_ids"] = call_ids
        evidence["first_provider_call_id"] = call_ids[0] if call_ids else None


def canonical_json(value: Any) -> str:
    """Serialize values deterministically for hashing and cache keys."""
    # Stable separators and key ordering make equivalent payloads hash identically.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def normalized_assertion_for_cache(assertion: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize assertion fields that should not create separate cache entries."""
    # Copy the assertion so cache normalization never mutates the request object.
    normalized = dict(assertion or {})

    # Collapse whitespace and case in the main text to avoid duplicate searches.
    if "text" in normalized:
        normalized["text"] = re.sub(r"\s+", " ", str(normalized.get("text") or "").strip()).lower()
    return normalized


def normalized_origin_for_cache(origin_document: Dict[str, Any]) -> Dict[str, Any]:
    url = normalize_url(origin_document.get("url") or "") or None
    domain = normalize_domain(origin_document.get("domain") or url or "") or None
    return {"url": url, "domain": domain}


def policy_for_cache(policy: Any) -> Dict[str, Any]:
    """Convert policy objects or dictionaries into cache-key-safe dictionaries."""
    # Pydantic policies need JSON-mode dumping to handle constrained values consistently.
    if hasattr(policy, "model_dump"):
        return policy.model_dump(mode="json")
    if isinstance(policy, dict):
        return policy

    # Plain objects used in tests can still participate in cache key generation.
    return vars(policy)


def search_backend_for_cache() -> Dict[str, Any]:
    """Return search-provider settings that affect evidence content shape."""
    # Provider and content extraction flags must partition cache entries when operators switch backends.
    return {
        "provider": SEARCH_PROVIDER or os.getenv("SEARCH_PROVIDER", "tavily"),
        "search_provider_max_results": os.getenv("SEARCH_PROVIDER_MAX_RESULTS", "50"),
        "search_include_raw_content": os.getenv("SEARCH_INCLUDE_RAW_CONTENT", "true"),
        "exa_include_highlights": os.getenv("EXA_INCLUDE_HIGHLIGHTS", "true"),
        "exa_include_text": os.getenv("EXA_INCLUDE_TEXT", "true"),
        "evidence_fetch_full_text": EVIDENCE_FETCH_FULL_TEXT,
        "evidence_max_contexts_per_source": EVIDENCE_MAX_CONTEXTS_PER_SOURCE,
        "evidence_max_contexts_total": EVIDENCE_MAX_CONTEXTS_TOTAL,
        "evidence_chunk_size_chars": EVIDENCE_CHUNK_SIZE_CHARS,
        "evidence_chunk_overlap_chars": EVIDENCE_CHUNK_OVERLAP_CHARS,
        "evidence_context_window_before": EVIDENCE_CONTEXT_WINDOW_BEFORE,
        "evidence_context_window_after": EVIDENCE_CONTEXT_WINDOW_AFTER,
        "evidence_max_query_relaxation_attempts": EVIDENCE_MAX_QUERY_RELAXATION_ATTEMPTS,
        "evidence_max_results_per_domain": EVIDENCE_MAX_RESULTS_PER_DOMAIN,
        "evidence_candidate_multiplier": EVIDENCE_CANDIDATE_MULTIPLIER,
        "evidence_target_citable_sources": EVIDENCE_TARGET_CITABLE_SOURCES,
        "progressive_query_relaxation": "v1",
        "citation_contract": "retrieved-context-id-v1",
        "provider_trace_contract": "v1",
        # Refill never widens LOCAL or EXT_ONLY_OFFICIAL beyond their active policy.
        "policy_safe_refill": "v1",
        "resilient_retrieval": "v3",
    }


def evidence_cache_key(
    assertion: Dict[str, Any],
    origin_document: Dict[str, Any],
    policy: Any,
    profile_version: str,
) -> str:
    """Build the cache key for an assertion, policy, profile version, and search backend."""
    # Include every input that can change the evidence search result.
    payload = {
        "schema_version": "evidence-search-request-v2",
        "assertion": normalized_assertion_for_cache(assertion),
        "origin_document": normalized_origin_for_cache(origin_document),
        "search_policy": policy_for_cache(policy),
        "profile_version": profile_version,
        "search_backend": search_backend_for_cache(),
    }

    # Hash the canonical payload so Mongo stores a compact, index-friendly key.
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def strategy_for_policy(policy: Any) -> EvidenceSearchStrategy:
    """Return the required evidence-search strategy."""
    raw_strategy = _policy_value(policy, "strategy")
    if isinstance(raw_strategy, EvidenceSearchStrategy):
        return raw_strategy
    return EvidenceSearchStrategy(str(raw_strategy or "").strip().upper())


def empty_domain_resolution() -> Dict[str, Any]:
    """Return the domain-resolution shape used by external strategies."""
    return {
        "selected_profiles": [],
        "preferred_sources": [],
        "selected_domains": [],
        "reason": "external_strategy",
    }



def useful_excerpt(result: Dict[str, Any]) -> str:
    """Extract a bounded text excerpt from raw provider content."""
    # Prefer raw page content when available, otherwise use the shorter provider snippet.
    raw = result.get("raw_content") or ""
    content = result.get("content") or ""

    # Compact whitespace and cap length so prompts and cache entries stay bounded.
    text = re.sub(r"\s+", " ", raw or content).strip()
    return text[:900]


def mark_evidence_uncitable(evidence: Dict[str, Any], fetch_status: str) -> Dict[str, Any]:
    """Keep provider metadata but expose no citable context without fetched text."""
    evidence["contexts"] = []
    evidence["fetch_status"] = fetch_status
    evidence["citation_status"] = "unavailable"
    logger.info(
        f"[evidence-search] citation_context_unavailable=true "
        f"source_id={evidence.get('source_id')} fetch_status={fetch_status}"
    )
    return evidence


def make_contexts_citable(contexts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Mark contexts derived from fetched documents and bind them to their text hash."""
    for context in contexts:
        text = str(context.get("text") or "")
        context["origin"] = "fetched_document"
        context["citation_eligible"] = True
        context["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return contexts


def chunks_metadata(ranked_chunks: List[Dict[str, Any]], selected_contexts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Expose rank metadata while keeping non-selected chunk text out of the response."""
    selected_ids = {context.get("selected_chunk_id") for context in selected_contexts}
    return [
        {
            "chunk_id": chunk.get("chunk_id"),
            "score": chunk.get("score"),
            "selected": chunk.get("chunk_id") in selected_ids,
            "char_length": chunk.get("char_length"),
            "ranking_reason": chunk.get("ranking_reason"),
            "matched_signals": chunk.get("matched_signals", []),
        }
        for chunk in ranked_chunks
    ]


async def build_evidences_with_optional_contexts(
    assertion: Dict[str, Any],
    raw_results: List[Dict[str, Any]],
    domain_resolution: Dict[str, Any],
    max_results: int,
    origin_document: Optional[Dict[str, Any]] = None,
    capture_chunks: bool = False,
    rank_offset: int = 0,
) -> List[Dict[str, Any]]:
    """Normalize search results and optionally enrich them with selected document contexts."""
    evidences: List[Dict[str, Any]] = []
    total_contexts = 0

    if EVIDENCE_FETCH_FULL_TEXT:
        logger.info(f"[evidence-search] full_text_enrichment_start=true assertion_id={assertion.get('assertion_id')}")

    for idx, source in enumerate(raw_results[:max_results], start=1 + rank_offset):
        evidence = evidence_from_source_v2(source, idx, domain_resolution, origin_document)
        source_id = evidence["source_id"]

        if not EVIDENCE_FETCH_FULL_TEXT:
            mark_evidence_uncitable(evidence, "full_text_disabled")
            evidences.append(evidence)
            continue

        if total_contexts >= EVIDENCE_MAX_CONTEXTS_TOTAL:
            mark_evidence_uncitable(evidence, "context_limit_reached")
            evidences.append(evidence)
            continue

        url = evidence.get("url") or ""
        logger.info(f"[evidence-search] downloading_url source_id={source_id} url={url}")
        fetch_result = await fetch_main_text(url, timeout=EVIDENCE_HTTP_TIMEOUT, user_agent=EVIDENCE_USER_AGENT)
        evidence["fetch_status"] = fetch_result.status
        evidence["content_type"] = getattr(fetch_result, "content_type", None)
        evidence["fetch_error"] = fetch_result.error
        evidence["fetched_url"] = getattr(fetch_result, "fetched_url", None)
        evidence["url_normalized"] = bool(getattr(fetch_result, "url_normalized", False))
        evidence["normalization_reason"] = getattr(fetch_result, "normalization_reason", None)
        evidence["fetch_attempted_urls"] = getattr(fetch_result, "attempted_urls", None) or [url]
        evidence["fetch_attempts"] = getattr(fetch_result, "attempts", None) or []
        evidence["fetch_retry_trace"] = getattr(fetch_result, "retry_trace", None) or []
        for attempt in evidence["fetch_attempts"]:
            attempt["classification"] = classify_attempt_outcome(attempt)
        http_status = getattr(fetch_result, "http_status", None)
        fetch_outcome = getattr(fetch_result, "outcome", None) or classify_fetch_outcome(
            status=fetch_result.status,
            failure_code=getattr(fetch_result, "failure_code", None),
            http_status=http_status,
        )
        fetch_diagnostics = getattr(fetch_result, "diagnostics", None) or {
            "outcome": fetch_outcome,
            "stage": getattr(fetch_result, "failure_stage", None)
            or ("COMPLETE" if fetch_result.status == "ok" else "FETCH"),
            "retryable": bool(getattr(fetch_result, "retryable", False)),
            "http_response_received": http_status is not None,
            "http_success": http_status is not None and 200 <= http_status < 300,
            "extracted": fetch_result.status == "ok",
            "retry_count": sum(
                action.get("action") == "RETRY" for action in evidence["fetch_retry_trace"]
            ),
        }
        evidence["fetch_outcome"] = fetch_outcome
        evidence["fetch_diagnostics"] = {**fetch_diagnostics, "citable": False}
        evidence["http_status"] = http_status
        evidence["response_bytes"] = int(getattr(fetch_result, "response_bytes", 0) or 0)
        evidence["extraction"] = {
            "detected_format": getattr(fetch_result, "detected_format", None),
            "extractor": getattr(fetch_result, "extractor", None),
            "text_length": int(getattr(fetch_result, "document_length_chars", 0) or 0),
        }
        logger.info(f"[evidence-search] fetch_status source_id={source_id} status={fetch_result.status} error={fetch_result.error}")

        if fetch_result.status != "ok":
            failure_code = getattr(fetch_result, "failure_code", None) or (
                str(fetch_result.error or fetch_result.status).upper())
            evidence["failure"] = {
                "stage": getattr(fetch_result, "failure_stage", None) or "FETCH",
                "code": failure_code,
                "retryable": bool(getattr(fetch_result, "retryable", False)),
            }
            mark_evidence_uncitable(evidence, fetch_result.status)
            evidence["contexts_total"] = 0
            evidences.append(evidence)
            continue

        document_length = fetch_result.document_length_chars
        chunks = chunk_text(source_id, fetch_result.text, EVIDENCE_CHUNK_SIZE_CHARS, EVIDENCE_CHUNK_OVERLAP_CHARS)
        ranked = rank_chunks(assertion, chunks)
        remaining_contexts = max(0, EVIDENCE_MAX_CONTEXTS_TOTAL - total_contexts)
        selection_decisions = {} if capture_chunks else None
        contexts = build_context_windows(
            source_id,
            chunks,
            ranked,
            max_contexts=min(EVIDENCE_MAX_CONTEXTS_PER_SOURCE, remaining_contexts),
            before=EVIDENCE_CONTEXT_WINDOW_BEFORE,
            after=EVIDENCE_CONTEXT_WINDOW_AFTER,
            min_context_chars=EVIDENCE_MIN_CONTEXT_CHARS,
            selection_decisions=selection_decisions,
        )

        evidence["document_length_chars"] = document_length
        evidence["chunks_total"] = len(chunks)
        evidence["contexts_total"] = len(contexts)
        logger.info(f"[evidence-search] document_length_chars source_id={source_id} value={document_length}")
        logger.info(f"[evidence-search] chunks_total source_id={source_id} value={len(chunks)}")
        logger.info(f"[evidence-search] contexts_selected source_id={source_id} value={len(contexts)}")

        if capture_chunks:
            ranked_by_id = {item["chunk_id"]: (rank, item) for rank, item in enumerate(ranked, 1)}
            selected_ids = {context.get("selected_chunk_id") for context in contexts}
            included_ids = {chunk_id for context in contexts for chunk_id in context.get("included_chunk_ids", [])}
            evidence["evaluation_chunks"] = [{
                "chunk_id": chunk["chunk_id"], "text": chunk["text"],
                "char_length": chunk["char_length"], "chunk_index": chunk["chunk_index"],
                "rank": ranked_by_id[chunk["chunk_id"]][0] if chunk["chunk_id"] in ranked_by_id else None,
                "score": ranked_by_id[chunk["chunk_id"]][1].get("score") if chunk["chunk_id"] in ranked_by_id else 0.0,
                "lexical_score": ranked_by_id[chunk["chunk_id"]][1].get("lexical_score") if chunk["chunk_id"] in ranked_by_id else 0.0,
                "boost_components": ranked_by_id[chunk["chunk_id"]][1].get("boost_components", {}) if chunk["chunk_id"] in ranked_by_id else {},
                "matched_signals": ranked_by_id[chunk["chunk_id"]][1].get("matched_signals", []) if chunk["chunk_id"] in ranked_by_id else [],
                "ranking_reason": ranked_by_id[chunk["chunk_id"]][1].get("ranking_reason") if chunk["chunk_id"] in ranked_by_id else "low lexical coverage",
                "context_ids": [context["context_id"] for context in contexts if chunk["chunk_id"] in context.get("included_chunk_ids", [])],
                "selected": chunk["chunk_id"] in selected_ids,
                "included_in_context": chunk["chunk_id"] in included_ids,
                "selection_reason": selection_decisions.get(chunk["chunk_id"], "LOW_COVERAGE_FALLBACK_TRUNCATED")
                                    if selection_decisions is not None else "NOT_RECORDED",
            } for chunk in chunks]

        if not chunks or not contexts:
            evidence["failure"] = {
                "stage": "RANKING",
                "code": "NO_RANKED_CONTEXT",
                "retryable": False,
            }
            mark_evidence_uncitable(evidence, "no_ranked_chunks")
            evidence["contexts_total"] = 0
            evidences.append(evidence)
            continue

        evidence["contexts"] = make_contexts_citable(contexts)
        evidence["citation_status"] = "available"
        evidence["fetch_diagnostics"]["citable"] = bool(evidence["contexts"])
        evidence["chunks_metadata"] = chunks_metadata(ranked, contexts)
        total_contexts += len(contexts)
        evidences.append(evidence)

    logger.info(f"[evidence-search] total_contexts_returned={total_contexts}")
    return evidences



async def call_search_provider(
    query: str,
    max_sources: int,
    include_domains: Optional[List[str]] = None,
    external_source_policy: str = "none",
) -> Dict[str, Any]:
    """Call the configured provider with optional domain and source-policy hints."""
    # Delegate provider-specific payload details to the search provider module.
    return await search_with_provider(
        SEARCH_PROVIDER,
        query,
        max_sources,
        include_domains=include_domains,
        external_source_policy=external_source_policy,
    )


def merge_search_results(*result_groups: List[Dict[str, Any]], max_sources: int) -> List[Dict[str, Any]]:
    """Merge provider result batches while preserving order and deduplicating URLs."""
    # Track URLs first, with a title/content fallback for sources without URLs.
    merged = []
    seen_urls = set()

    # Walk result groups in priority order and stop as soon as enough sources exist.
    for results in result_groups:
        for result in results or []:
            url = result.get("url") or ""
            dedupe_key = normalize_url(url) or f"{result.get('title', '')}:{result.get('content', '')}"
            if dedupe_key in seen_urls:
                continue
            seen_urls.add(dedupe_key)
            merged.append(result)
            if len(merged) >= max_sources:
                return merged
    return merged


def diversify_search_results(
    results: List[Dict[str, Any]],
    max_sources: int,
    max_per_domain: int = EVIDENCE_MAX_RESULTS_PER_DOMAIN,
) -> List[Dict[str, Any]]:
    """Select distinct candidates, deferring recently unusable URLs when possible."""
    now = time.monotonic()
    for url, expiry in list(_recent_unusable_urls.items()):
        if expiry <= now:
            del _recent_unusable_urls[url]
    ranked_results = sorted(
        results or [],
        key=lambda item: normalize_url(item.get("url") or "") in _recent_unusable_urls,
    )
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    domain_order: List[str] = []
    seen_urls = set()
    for result in ranked_results:
        normalized = normalize_url(result.get("url") or "")
        if normalized and normalized in seen_urls:
            continue
        if normalized:
            seen_urls.add(normalized)
        domain = normalize_domain(urlparse(result.get("url") or "").netloc) or "__unknown__"
        if domain not in buckets:
            buckets[domain] = []
            domain_order.append(domain)
        if len(buckets[domain]) < max_per_domain:
            buckets[domain].append(result)

    selected: List[Dict[str, Any]] = []
    offset = 0
    while len(selected) < max_sources:
        added = False
        for domain in domain_order:
            bucket = buckets[domain]
            if offset < len(bucket):
                selected.append(bucket[offset])
                added = True
                if len(selected) >= max_sources:
                    break
        if not added:
            break
        offset += 1
    return selected


def remember_unusable_urls(evidences: List[Dict[str, Any]]) -> None:
    """Use completed fetches to rank future candidates, without extra requests."""
    now = time.monotonic()
    for item in evidences:
        url = normalize_url(item.get("url") or "")
        if not url:
            continue
        status = item.get("fetch_status")
        if status == "ok":
            _recent_unusable_urls.pop(url, None)
        elif _is_unusable_url_outcome(item):
            outcome_class = _unusable_outcome_class(item) or "UNCLASSIFIED"
            ttl_seconds = UNUSABLE_OUTCOME_TTLS.get(outcome_class, UNUSABLE_URL_TTL_SECONDS)
            _recent_unusable_urls[url] = now + ttl_seconds
    if len(_recent_unusable_urls) > UNUSABLE_URL_MAX_ENTRIES:
        for url, _ in sorted(_recent_unusable_urls.items(), key=lambda pair: pair[1])[
            :len(_recent_unusable_urls) - UNUSABLE_URL_MAX_ENTRIES
        ]:
            del _recent_unusable_urls[url]


def _is_unusable_url_outcome(item: Dict[str, Any]) -> bool:
    return _unusable_outcome_class(item) is not None


def _document_identity(url: str) -> str:
    """Stable opaque identity shared by replicas for a normalized document URL."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _unusable_outcome_class(item: Dict[str, Any]) -> Optional[str]:
    code = (item.get("failure") or {}).get("code") or item.get("fetch_error")
    http_status = item.get("http_status")
    outcome = classify_fetch_outcome(
        status=str(item.get("fetch_status") or "failed"),
        failure_code=str(code).upper() if code else None,
        http_status=http_status if isinstance(http_status, int) else None,
    )
    if outcome in UNUSABLE_OUTCOME_TTLS:
        return outcome
    if outcome == "ACCESS_DENIED":
        return outcome
    # Keep compatibility with older evidence payloads that only carry fetch_error.
    legacy_code = str(item.get("fetch_error") or "").lower()
    if legacy_code in {"http_401", "http_403"}:
        return "ACCESS_DENIED"
    if legacy_code == "http_404":
        return "NOT_FOUND"
    if legacy_code == "connect_error":
        return "NETWORK_FAILURE"
    if item.get("fetch_status") == "empty_text":
        return "EMPTY_CONTENT"
    return None


async def hydrate_unusable_url_history(results: List[Dict[str, Any]]) -> None:
    """Load unexpired URL outcomes shared by all evidence-search replicas."""
    if unusable_url_collection is None:
        return
    urls = list({
        normalize_url(item.get("url") or "")
        for item in results or []
        if normalize_url(item.get("url") or "")
    })
    if not urls:
        return
    now = utc_now()
    try:
        cursor = unusable_url_collection.find(
            {"url": {"$in": urls}, "expires_at": {"$gt": now}, "active_failure": {"$ne": False}},
            {"_id": 0, "url": 1, "expires_at": 1, "active_failure": 1},
        )
        records = await cursor.to_list(length=len(urls))
        monotonic_now = time.monotonic()
        for record in records:
            expires_at = record.get("expires_at")
            if not isinstance(expires_at, datetime):
                continue
            # Motor commonly decodes BSON dates as naive UTC datetimes unless
            # tz_aware was enabled on the client.
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            remaining = max(0.0, (expires_at - now).total_seconds())
            _recent_unusable_urls[record["url"]] = monotonic_now + remaining
    except Exception as exc:
        # Candidate selection remains operational if the advisory history is
        # temporarily unavailable.
        logger.warning(f"[evidence-search] unusable_url_history_read_failed error='{exc}'")


async def persist_unusable_url_outcomes(evidences: List[Dict[str, Any]]) -> None:
    """Persist URL outcomes so another pod can avoid a known unusable source."""
    remember_unusable_urls(evidences)
    if unusable_url_collection is None:
        return
    now = utc_now()
    try:
        for item in evidences:
            url = normalize_url(item.get("url") or "")
            if not url:
                continue
            identity = _document_identity(url)
            if item.get("fetch_status") == "ok":
                await unusable_url_collection.update_one(
                    {"url": url},
                    {"$set": {
                        "url": url, "document_identity": identity, "active_failure": False,
                        "last_success_at": now, "updated_at": now,
                        "expires_at": now + timedelta(seconds=UNUSABLE_HISTORY_SUCCESS_TTL_SECONDS),
                        "policy": UNUSABLE_HISTORY_POLICY,
                    }, "$setOnInsert": {"first_attempt_at": now}, "$inc": {"success_count": 1}},
                    upsert=True,
                )
                _recent_unusable_urls.pop(url, None)
            elif _is_unusable_url_outcome(item):
                outcome_class = _unusable_outcome_class(item) or "UNCLASSIFIED"
                ttl_seconds = UNUSABLE_OUTCOME_TTLS.get(outcome_class, UNUSABLE_URL_TTL_SECONDS)
                await unusable_url_collection.update_one(
                    {"url": url},
                    {"$set": {
                        "url": url,
                        "document_identity": identity,
                        "outcome_class": outcome_class,
                        "active_failure": True,
                        "failure_code": (item.get("failure") or {}).get("code"),
                        "http_status": item.get("http_status"),
                        "last_attempt_at": now,
                        "updated_at": now,
                        "expires_at": now + timedelta(seconds=ttl_seconds),
                        "policy": UNUSABLE_HISTORY_POLICY,
                    }, "$setOnInsert": {"first_attempt_at": now},
                        "$inc": {"attempt_count": max(1, len(item.get("fetch_attempts") or []))}},
                    upsert=True,
                )
    except Exception as exc:
        logger.warning(f"[evidence-search] unusable_url_history_write_failed error='{exc}'")


def response_cache_policy(evidences: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Choose a TTL without letting temporary retrieval failures linger."""
    if any(item.get("citation_status") == "available" and item.get("contexts") for item in evidences):
        return {"classification": "POSITIVE", "ttl_seconds": EVIDENCE_SEARCH_CACHE_TTL_SECONDS}
    if not evidences or any((item.get("failure") or {}).get("retryable") for item in evidences):
        return {"classification": "TRANSIENT_NEGATIVE",
                "ttl_seconds": EVIDENCE_SEARCH_TRANSIENT_FAILURE_TTL_SECONDS}
    return {"classification": "UNUSABLE_NEGATIVE", "ttl_seconds": EVIDENCE_SEARCH_UNUSABLE_TTL_SECONDS}


def retrieval_summary(
    evidences: List[Dict[str, Any]],
    candidates_considered: int,
    target_documents: int,
    fallback_rounds: int,
    negative_history_hits: int = 0,
    negative_history_attempts_avoided: int = 0,
) -> Dict[str, Any]:
    citable = sum(bool(item.get("citation_status") == "available" and item.get("contexts")) for item in evidences)
    extracted = sum(item.get("fetch_status") == "ok" for item in evidences)
    attempts = sum(max(1, len(item.get("fetch_attempts") or [])) for item in evidences)
    http_requests = sum(len(item.get("fetch_attempts") or []) for item in evidences)
    http_responses = sum(
        attempt.get("http_status") is not None
        for item in evidences for attempt in item.get("fetch_attempts") or []
    )
    http_successes = sum(
        isinstance(attempt.get("http_status"), int) and 200 <= attempt["http_status"] < 300
        for item in evidences for attempt in item.get("fetch_attempts") or []
    )
    attempted_documents = sum(bool(item.get("fetch_attempts")) for item in evidences)
    outcome_counts: Dict[str, int] = {}
    for item in evidences:
        outcome = item.get("fetch_outcome")
        if outcome:
            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
    retry_actions = sum(
        action.get("action") == "RETRY"
        for item in evidences for action in item.get("fetch_retry_trace") or []
    )
    candidate_substitutions = sum(
        item.get("retrieval_mode") == "existing_provider_candidates_after_unusable_fetch"
        for item in evidences
    )
    retry_recovered = sum(
        any(action.get("action") == "RETRY" for action in item.get("fetch_retry_trace") or [])
        and item.get("fetch_status") == "ok"
        for item in evidences
    )
    substitution_recovered = sum(
        item.get("retrieval_mode") == "existing_provider_candidates_after_unusable_fetch"
        and item.get("citation_status") == "available" and bool(item.get("contexts"))
        for item in evidences
    )
    failures: Dict[str, int] = {}
    for item in evidences:
        code = (item.get("failure") or {}).get("code")
        if code:
            failures[code] = failures.get(code, 0) + 1
    return {
        "target_documents": target_documents,
        "candidates_considered": candidates_considered,
        "fetch_attempts": attempts,
        "http_requests": http_requests,
        "http_responses": http_responses,
        "http_successes": http_successes,
        "documents_scheduled": len(evidences),
        "documents_attempted": attempted_documents,
        "documents_extracted": extracted,
        "documents_citable": citable,
        "outcome_counts": outcome_counts,
        "retry_actions": retry_actions,
        "retry_recovered": retry_recovered,
        "retry_exhausted": sum(
            any(action.get("action") == "RETRY" for action in item.get("fetch_retry_trace") or [])
            and item.get("fetch_status") != "ok" for item in evidences
        ),
        "candidate_substitutions": candidate_substitutions,
        "substitution_recovered": substitution_recovered,
        "substitution_exhausted": candidate_substitutions - substitution_recovered,
        "fallback_rounds": fallback_rounds,
        "failure_counts": failures,
        "negative_history_hits": negative_history_hits,
        "negative_history_attempts_avoided": negative_history_attempts_avoided,
        "stop_reason": "TARGET_REACHED" if citable >= target_documents else "BUDGET_EXHAUSTED",
    }



async def ensure_indexes():
    """Create indexes for the evidence response cache."""
    if cache_collection is not None:
        await cache_collection.create_index("cache_key", name="cache_key_1", unique=True)
        await cache_collection.create_index("assertion_hash", name="assertion_hash_1")
        await cache_collection.create_index("created_at", name="created_at_1")
        await cache_collection.create_index("expires_at", name="expires_at_ttl", expireAfterSeconds=0)
    if unusable_url_collection is not None:
        await unusable_url_collection.create_index("url", name="url_1", unique=True)
        await unusable_url_collection.create_index(
            "expires_at", name="expires_at_ttl", expireAfterSeconds=0,
        )


@app.on_event("startup")
async def startup_event():
    """Initialize Mongo collections and indexes when the FastAPI app starts."""
    # Create the shared Mongo client and bind the collections used by handlers.
    global mongo_client, db, cache_collection, unusable_url_collection
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[MONGO_DBNAME]
    cache_collection = db[MONGO_CACHE_COLLECTION]
    unusable_url_collection = db[MONGO_UNUSABLE_URL_COLLECTION]

    # Create or update indexes before serving traffic.
    await ensure_indexes()


@app.on_event("shutdown")
async def shutdown_event():
    """Close the Mongo client when the FastAPI app shuts down."""
    # Motor clients should be closed explicitly to release sockets cleanly.
    if mongo_client:
        mongo_client.close()


@app.get("/health")
async def health():
    """Return a lightweight liveness response for orchestration checks."""
    # Avoid touching external dependencies so health stays cheap and reliable.
    return {"status": "ok", "service": "evidence-search"}


@app.delete("/admin/cache")
async def clear_cache():
    """Delete all cached evidence-search responses."""
    # Refuse cache operations until startup has initialized the collection.
    if cache_collection is None:
        raise HTTPException(status_code=503, detail="Evidence search cache is not initialized")

    # Remove every cache document and return the deleted count for operators.
    result = await cache_collection.delete_many({})
    logger.info(f"[evidence-search] cache_clear=true deleted_count={result.deleted_count}")
    return {
        "status": "ok",
        "cache_collection": MONGO_CACHE_COLLECTION,
        "deleted_count": result.deleted_count,
    }


@app.post("/search/evidence", response_model=EvidenceSearchResponseV2)
async def search_evidence(req: EvidenceSearchRequestV2, request: Request = None):
    """Search for evidence supporting a validated assertion payload."""
    cold, run_id = evaluation_context(request)
    if run_id:
        logger.info({"event": "evaluation.retrieval", "run_id": run_id, "assertion_id": str(req.assertion.assertion_id), "cold": cold})
    # Validate the minimum assertion text required to build any useful query.
    assertion = req.assertion.model_dump(mode="json")
    text = str(assertion.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="assertion.text is required")

    strategy = strategy_for_policy(req.search_policy)
    use_local_routing = strategy == EvidenceSearchStrategy.LOCAL
    preferred_sources = [source.model_dump(mode="json") for source in req.search_policy.preferred_sources]
    selected_domains = list(dict.fromkeys(
        normalize_domain(source.get("domain")) for source in preferred_sources if normalize_domain(source.get("domain"))
    ))
    if use_local_routing and not selected_domains:
        raise HTTPException(
            status_code=400,
            detail={"code": "LOCAL_PREFERRED_SOURCES_REQUIRED", "message": "LOCAL evidence search requires sources resolved by Source Router"},
        )
    profile_version = (
        "routed-sources:" + hashlib.sha256(canonical_json(preferred_sources).encode("utf-8")).hexdigest()[:16]
        if use_local_routing else f"external-{strategy.value.lower()}"
    )
    origin_document = req.origin_document.model_dump(mode="json")

    # Build the cache key from the normalized assertion, policy, and profile version.
    cache_key = evidence_cache_key(assertion, origin_document, req.search_policy, profile_version)
    now = utc_now()

    # Return a fresh cached response when one exists and has not expired.
    if cache_collection is not None and not cold:
        cached = await cache_collection.find_one({"cache_key": cache_key, "expires_at": {"$gt": now}}, {"_id": 0})
        if cached and cached.get("response"):
            response = dict(cached["response"])
            origin_trace = response.get("provider_trace") or {}
            origin_requests = origin_trace.get("requests") or []
            response["evidence_bundle_hash"] = evidence_bundle_hash(response.get("evidences", []))
            response["cached"] = True
            response["cache_key"] = cache_key
            response["provider_trace"] = {
                "provider": origin_trace.get("provider") or SEARCH_PROVIDER,
                "cache_hit": True,
                "capture_status": "CACHE_HIT" if origin_requests else "NOT_RECORDED_LEGACY_CACHE",
                "requests": [],
                "cached_origin_requests": origin_requests,
                "summary": provider_trace_summary([]),
                "cached_origin_summary": origin_trace.get("summary") or provider_trace_summary(origin_requests),
            }
            if run_id:
                response["evaluation_trace"] = {"run_id": run_id, "cache_hit": True,
                                                "query_execution": [],
                                                "chunk_detail": "NOT_RECORDED_ON_CACHE_HIT"}
            logger.info(f"[evidence-search] cache_hit=true assertion_id={assertion.get('assertion_id')} cache_key={cache_key}")
            return response

    # Attach caller-selected LOCAL domains as metadata; no discovery or route memory lives here.
    if use_local_routing:
        domain_resolution = {
            "selected_profiles": [],
            "preferred_sources": preferred_sources[:req.search_policy.max_domains],
            "selected_domains": selected_domains[:req.search_policy.max_domains],
            "reason": "source_router",
        }
    else:
        domain_resolution = empty_domain_resolution()
        domain_resolution["reason"] = strategy.value.lower()
    domain_resolution["strategy"] = strategy.value
    domain_resolution["profile_version"] = profile_version
    effective_search_policy = req.search_policy.model_dump(mode="json") if hasattr(req.search_policy, "model_dump") else dict(vars(req.search_policy))

    # Log the routing decision to make evidence selection auditable.
    logger_prefix = f"[evidence-search] assertion_id={assertion.get('assertion_id')}"
    logger.info(
        f"{logger_prefix} strategy={strategy.value} "
        f"selected_domains={selected_domains if use_local_routing else []}"
    )

    # Log the rendered query list for operator debugging.
    queries = build_queries_v2(assertion, domain_resolution, effective_search_policy)
    for query in queries:
        logger.info(f"[evidence-search] query='{query}'")

    # Build provider-ready requests and log their domain filters.
    search_requests = build_search_requests(assertion, domain_resolution, effective_search_policy)
    trace_requests = [
        {**item, "plan_sequence": index, "provider": SEARCH_PROVIDER, "status": "NOT_EXECUTED",
         "returned_urls": [], "result_decisions": []}
        for index, item in enumerate(search_requests, start=1)
    ]
    for search_request in search_requests:
        logger.info(
            "[evidence-search] search_request "
            f"provider='{SEARCH_PROVIDER}' "
            f"query='{search_request['query']}' "
            f"include_domains={search_request.get('include_domains')} "
            f"external_source_policy={search_request.get('external_source_policy')} "
            f"mode={search_request.get('mode')}"
        )

    # Execute provider searches. Missing credentials are a dependency error, never placeholders.
    raw_results: List[Dict[str, Any]] = []
    candidate_budget = max(
        effective_search_policy["max_results"],
        effective_search_policy["max_results"] * EVIDENCE_CANDIDATE_MULTIPLIER,
    )
    target_citable_sources = min(
        effective_search_policy["max_results"], EVIDENCE_TARGET_CITABLE_SOURCES,
    )
    successful_searches = 0
    provider_errors: List[Dict[str, str]] = []
    policy_drops: List[Dict[str, str]] = []
    provider_name = SEARCH_PROVIDER
    provider_call_sequence = 0
    for request_index, search_request in enumerate(search_requests):
        query = search_request["query"]
        trace_request = trace_requests[request_index]
        relaxation_level = int(search_request.get("relaxation_level") or 0)
        if relaxation_level > 0 and raw_results:
            trace_request["status"] = "SKIPPED"
            trace_request["outcome"] = "RESULTS_ALREADY_FOUND"
            continue
        provider_call_sequence += 1
        trace_request["provider_call_id"] = f"{provider_name or 'provider'}-{provider_call_sequence}"
        trace_request["call_sequence"] = provider_call_sequence
        trace_request["status"] = "EXECUTED"
        trace_request["started_at"] = iso(utc_now())
        call_started = time.perf_counter()
        include_domains = search_request.get("include_domains")
        external_source_policy = search_request.get("external_source_policy") or "none"
        try:
            # Merge each provider response into the ordered, deduplicated result set.
            search_results = await search_with_provider(
                provider_name,
                query,
                candidate_budget,
                include_domains=include_domains or None,
                external_source_policy=external_source_policy,
            )
            successful_searches += 1
            provider_returned = search_results.get("results", []) or []
            returned = provider_returned
            dropped_urls = set()
            if strategy == EvidenceSearchStrategy.EXT_ONLY_OFFICIAL:
                returned = []
                for item in provider_returned:
                    url = str(item.get("url") or "")
                    if is_official_source_type(source_type_for_domain(normalize_domain(urlparse(url).netloc))):
                        returned.append(item)
                    else:
                        dropped_urls.add(url)
                        policy_drops.append({"url": url, "reason": "NOT_OFFICIAL_SOURCE_TYPE"})
            trace_request["returned_urls"] = [str(item.get("url") or "") for item in provider_returned]
            trace_request["result_count"] = len(provider_returned)
            trace_request["outcome"] = (
                "RESULTS" if returned else "FILTERED_EMPTY" if provider_returned else "EMPTY"
            )
            seen = {
                normalize_url(item.get("url") or "") or f"{item.get('title', '')}:{item.get('content', '')}"
                for item in raw_results
            }
            retained = len(raw_results)
            for provider_rank, item in enumerate(provider_returned, start=1):
                url = str(item.get("url") or "")
                key = normalize_url(url) or f"{item.get('title', '')}:{item.get('content', '')}"
                if url in dropped_urls:
                    decision = "DROPPED_NOT_OFFICIAL"
                elif retained >= candidate_budget:
                    decision = "NOT_CONSIDERED_LIMIT"
                elif key in seen:
                    decision = "DUPLICATE"
                else:
                    decision = "RETAINED"
                    seen.add(key)
                    retained += 1
                trace_request["result_decisions"].append(
                    {"url": url, "provider_rank": provider_rank, "decision": decision}
                )
            trace_request["retained_result_count"] = sum(
                item["decision"] == "RETAINED" for item in trace_request["result_decisions"]
            )
            raw_results = merge_search_results(
                raw_results,
                returned,
                max_sources=candidate_budget,
            )
            if len(raw_results) >= candidate_budget:
                break
        except Exception as e:
            trace_request["status"] = "FAILED"
            trace_request["error_type"] = type(e).__name__
            trace_request["error"] = str(e) or e.__class__.__name__
            trace_request["outcome"] = "ERROR"
            logger.warning(f"[evidence-search] search provider failed provider='{provider_name}' query='{query}': {e}")
            provider_errors.append({"provider": provider_name, "query": query, "error": str(e) or e.__class__.__name__})
        finally:
            trace_request["completed_at"] = iso(utc_now())
            trace_request["duration_ms"] = round((time.perf_counter() - call_started) * 1000, 3)

    for trace_request in trace_requests:
        if trace_request.get("status") == "NOT_EXECUTED":
            trace_request["status"] = "SKIPPED"
            trace_request["outcome"] = "CANDIDATE_BUDGET_REACHED"

    # Zero results is valid. Zero successful requests is a dependency failure.
    if search_requests and successful_searches == 0:
        failed_provider_trace = {
            "provider": provider_name,
            "cache_hit": False,
            "capture_status": "CAPTURED",
            "requests": trace_requests,
            "summary": provider_trace_summary(trace_requests),
        }
        raise HTTPException(
            status_code=502,
            detail={
                "code": "EVIDENCE_PROVIDER_FAILED", "message": "All evidence provider requests failed",
                "provider": provider_name, "errors": provider_errors, "search_policy": effective_search_policy,
                "provider_trace": failed_provider_trace,
            },
        )

    # Normalize raw provider results into the public evidence response contract.
    # Shared history is advisory: it only changes ordering among URLs that the
    # provider has already returned for this request.
    await hydrate_unusable_url_history(raw_results)
    scheduled_results = diversify_search_results(
        raw_results,
        max_sources=min(
            effective_search_policy["max_results"],
            max(2, target_citable_sources, effective_search_policy["max_results"] - 2),
        ),
    )
    negative_history_urls = {
        normalize_url(item.get("url") or "")
        for item in raw_results
        if normalize_url(item.get("url") or "") in _recent_unusable_urls
    }
    evidences = await build_evidences_with_optional_contexts(
        assertion,
        scheduled_results,
        domain_resolution,
        max_results=effective_search_policy["max_results"],
        origin_document=origin_document,
        capture_chunks=bool(run_id),
    )
    await persist_unusable_url_outcomes(evidences)

    # If a scheduled URL is unusable, consume spare candidates from the same
    # provider response before issuing any new search.  Each URL is downloaded
    # at most once; this is candidate substitution, not an HTTP retry.
    local_refill_used = False
    local_refill_candidate_count = 0
    scheduled_urls = {
        normalize_url(item.get("url") or "") for item in scheduled_results
    }
    remaining_candidates = [
        item for item in raw_results
        if normalize_url(item.get("url") or "") not in scheduled_urls
    ]
    initial_citable = sum(
        bool(item.get("citation_status") == "available" and item.get("contexts"))
        for item in evidences
    )
    while (
        EVIDENCE_FETCH_FULL_TEXT
        and initial_citable < target_citable_sources
        and remaining_candidates
        and len(evidences) < effective_search_policy["max_results"]
    ):
        next_candidates = diversify_search_results(remaining_candidates, max_sources=1)
        if not next_candidates:
            break
        candidate = next_candidates[0]
        candidate_url = normalize_url(candidate.get("url") or "")
        remaining_candidates = [
            item for item in remaining_candidates
            if normalize_url(item.get("url") or "") != candidate_url
        ]
        local_refill_used = True
        local_refill_candidate_count += 1
        refill_resolution = deepcopy(domain_resolution)
        refill_resolution["fallback_used"] = True
        refill_resolution["fallback_reason"] = "EXISTING_CANDIDATES_AFTER_UNUSABLE_FETCH"
        refill_evidences = await build_evidences_with_optional_contexts(
            assertion,
            [candidate],
            refill_resolution,
            max_results=1,
            origin_document=origin_document,
            capture_chunks=bool(run_id),
            rank_offset=len(evidences),
        )
        for item in refill_evidences:
            item["retrieval_mode"] = "existing_provider_candidates_after_unusable_fetch"
            item["fallback_reason"] = "EXISTING_CANDIDATES_AFTER_UNUSABLE_FETCH"
            item["recovery_trace"] = {
                "action": "SUBSTITUTE_CANDIDATE",
                "reason": "INSUFFICIENT_CITABLE_SOURCES",
                "candidate_source": "EXISTING_PROVIDER_BATCH",
            }
        evidences.extend(refill_evidences)
        await persist_unusable_url_outcomes(refill_evidences)
        initial_citable = sum(
            bool(item.get("citation_status") == "available" and item.get("contexts"))
            for item in evidences
        )

    # Refill the retrieval budget when the first pass cannot produce the
    # configured number of citable sources. Every fallback keeps the active
    # source policy; EXT_ONLY_OFFICIAL is filtered again after provider search.
    fallback_used = False
    fallback_reason = None
    fallback_excluded_domains: List[str] = []
    fallback_candidate_count = 0
    fallback_rounds = 1 if local_refill_used else 0
    if (
        EVIDENCE_FETCH_FULL_TEXT
        and initial_citable < target_citable_sources
        and len(evidences) < effective_search_policy["max_results"]
    ):
        fallback_rounds += 1
        fallback_reason = (
            "NO_INITIAL_RESULTS" if not evidences else
            "ALL_INITIAL_FETCHES_UNUSABLE" if initial_citable == 0 else
            "INSUFFICIENT_CITABLE_SOURCES"
        )
        fallback_used = True
        initial_urls = {normalize_url(item.get("url") or "") for item in evidences}
        fallback_include_domains = selected_domains if strategy == EvidenceSearchStrategy.LOCAL else None
        fallback_policy = {
            EvidenceSearchStrategy.LOCAL: "none",
            EvidenceSearchStrategy.EXT_ONLY_OFFICIAL: "only_official",
            EvidenceSearchStrategy.EXT_OFFICIAL_FIRST: "official_first",
        }[strategy]
        fallback_mode_prefix = {
            EvidenceSearchStrategy.LOCAL: "local_routed",
            EvidenceSearchStrategy.EXT_ONLY_OFFICIAL: "official_only",
            EvidenceSearchStrategy.EXT_OFFICIAL_FIRST: "official_first",
        }[strategy]
        highest_relaxation = max((int(item.get("relaxation_level") or 0) for item in search_requests), default=0)
        fallback_seed_requests = [
            item for item in search_requests
            if int(item.get("relaxation_level") or 0) == highest_relaxation
        ]
        fallback_requests = [{
            "query": item["query"],
            "include_domains": fallback_include_domains,
            "mode": f"{fallback_mode_prefix}_after_no_results" if not evidences else
                    f"{fallback_mode_prefix}_after_all_fetches_unusable",
            "external_source_policy": fallback_policy,
            "excluded_domains": fallback_excluded_domains,
            "trigger": fallback_reason,
            "relaxation_level": item.get("relaxation_level", 0),
            "relaxation_reason": item.get("relaxation_reason"),
            "removed_terms": item.get("removed_terms", []),
        } for item in fallback_seed_requests]
        fallback_raw_results: List[Dict[str, Any]] = []

        for fallback_request in fallback_requests:
            provider_call_sequence += 1
            trace_request = {
                **fallback_request,
                "plan_sequence": len(trace_requests) + 1,
                "provider": SEARCH_PROVIDER,
                "provider_call_id": f"{provider_name or 'provider'}-{provider_call_sequence}",
                "call_sequence": provider_call_sequence,
                "status": "EXECUTED",
                "started_at": iso(utc_now()),
                "returned_urls": [],
                "result_decisions": [],
            }
            trace_requests.append(trace_request)
            call_started = time.perf_counter()
            try:
                search_results = await search_with_provider(
                    provider_name,
                    fallback_request["query"],
                    candidate_budget,
                    include_domains=fallback_include_domains,
                    external_source_policy=fallback_policy,
                )
                provider_returned = search_results.get("results", []) or []
                returned = provider_returned
                dropped_urls = set()
                if strategy == EvidenceSearchStrategy.EXT_ONLY_OFFICIAL:
                    returned = []
                    for item in provider_returned:
                        url = str(item.get("url") or "")
                        if is_official_source_type(
                            source_type_for_domain(normalize_domain(urlparse(url).netloc))
                        ):
                            returned.append(item)
                        else:
                            dropped_urls.add(url)
                            policy_drops.append({"url": url, "reason": "NOT_OFFICIAL_SOURCE_TYPE"})
                retained = []
                seen_urls = {normalize_url(item.get("url") or "") for item in fallback_raw_results}
                for provider_rank, item in enumerate(provider_returned, start=1):
                    url = str(item.get("url") or "")
                    normalized_url = normalize_url(url)
                    domain = normalize_domain(urlparse(url).netloc)
                    if url in dropped_urls:
                        decision = "DROPPED_NOT_OFFICIAL"
                    elif any(is_same_domain_family(domain, excluded) for excluded in fallback_excluded_domains):
                        decision = "EXCLUDED_INITIAL_UNUSABLE_DOMAIN"
                    elif normalized_url and normalized_url in initial_urls:
                        decision = "DUPLICATE_INITIAL_URL"
                    elif normalized_url and normalized_url in seen_urls:
                        decision = "DUPLICATE_FALLBACK_URL"
                    else:
                        decision = "RETAINED"
                        retained.append(item)
                        if normalized_url:
                            seen_urls.add(normalized_url)
                    trace_request["result_decisions"].append(
                        {"url": url, "provider_rank": provider_rank, "decision": decision}
                    )
                trace_request["returned_urls"] = [str(item.get("url") or "") for item in provider_returned]
                trace_request["result_count"] = len(provider_returned)
                trace_request["retained_result_count"] = len(retained)
                trace_request["outcome"] = "RESULTS" if returned else "EMPTY"
                fallback_raw_results = merge_search_results(
                    fallback_raw_results, retained, max_sources=candidate_budget,
                )
                if len(fallback_raw_results) >= candidate_budget:
                    break
            except Exception as exc:
                trace_request["status"] = "FAILED"
                trace_request["error_type"] = type(exc).__name__
                trace_request["error"] = str(exc) or exc.__class__.__name__
                trace_request["outcome"] = "ERROR"
                logger.warning(
                    f"[evidence-search] policy-safe refill provider failed "
                    f"provider='{provider_name}' query='{fallback_request['query']}': {exc}"
                )
            finally:
                trace_request["completed_at"] = iso(utc_now())
                trace_request["duration_ms"] = round((time.perf_counter() - call_started) * 1000, 3)

        if fallback_raw_results:
            fallback_candidate_count = len(fallback_raw_results)
            fallback_resolution = deepcopy(domain_resolution)
            fallback_resolution["fallback_used"] = True
            fallback_resolution["fallback_reason"] = fallback_reason
            fallback_resolution["fallback_excluded_domains"] = fallback_excluded_domains
            fallback_scheduled = diversify_search_results(
                fallback_raw_results,
                max_sources=min(
                    effective_search_policy["max_results"] - len(evidences),
                    max(1, target_citable_sources - initial_citable),
                ),
            )
            fallback_evidences = await build_evidences_with_optional_contexts(
                assertion,
                fallback_scheduled,
                fallback_resolution,
                max_results=effective_search_policy["max_results"] - len(evidences),
                origin_document=origin_document,
                capture_chunks=bool(run_id),
                rank_offset=len(evidences),
            )
            for item in fallback_evidences:
                item["retrieval_mode"] = fallback_requests[0]["mode"]
                item["fallback_reason"] = fallback_reason
            evidences.extend(fallback_evidences)
            await persist_unusable_url_outcomes(fallback_evidences)

        domain_resolution["fallback_used"] = fallback_used
        domain_resolution["fallback_reason"] = fallback_reason
        domain_resolution["fallback_excluded_domains"] = fallback_excluded_domains
        domain_resolution["local_candidate_refill_count"] = local_refill_candidate_count
        search_requests.extend(fallback_requests)
    elif local_refill_used:
        domain_resolution["fallback_used"] = True
        domain_resolution["fallback_reason"] = "EXISTING_CANDIDATES_AFTER_UNUSABLE_FETCH"
        domain_resolution["fallback_excluded_domains"] = []
        domain_resolution["local_candidate_refill_count"] = local_refill_candidate_count

    attach_provider_lineage(evidences, trace_requests)
    summary = retrieval_summary(
        evidences,
        candidates_considered=len(raw_results) + fallback_candidate_count,
        target_documents=target_citable_sources,
        fallback_rounds=fallback_rounds,
        negative_history_hits=len(negative_history_urls),
        negative_history_attempts_avoided=len(
            negative_history_urls - {
                normalize_url(item.get("url") or "") for item in evidences
            }
        ),
    )
    cache_policy = response_cache_policy(evidences)
    response = {
        "schema_version": "evidence-search-response-v2",
        "assertion_id": assertion.get("assertion_id"),
        "domain_resolution": domain_resolution,
        "search_policy": effective_search_policy,
        "queries_executed": search_requests,
        "evidences": evidences,
        "retrieval_summary": summary,
        "cache_policy": cache_policy,
        "evidence_bundle_hash": evidence_bundle_hash(evidences),
        "provider_trace": {
            "provider": provider_name,
            "cache_hit": False,
            "capture_status": "CAPTURED",
            "requests": trace_requests,
            "summary": provider_trace_summary(trace_requests),
        },
        "cached": False,
        "cache_key": cache_key,
    }

    # Evaluation-only chunk text must never be stored in the shared response cache.
    cache_response = response
    if run_id:
        cache_response = deepcopy(response)
        for source in cache_response["evidences"]:
            source.pop("evaluation_chunks", None)

    # Store the response with TTL metadata so identical future requests can reuse it.
    if cache_collection is not None:
        assertion_hash = hashlib.sha256(canonical_json(normalized_assertion_for_cache(assertion)).encode("utf-8")).hexdigest()
        await cache_collection.update_one(
            {"cache_key": cache_key},
            {
                "$set": {
                    "cache_key": cache_key,
                    "assertion_hash": assertion_hash,
                    "profile_version": profile_version,
                    "search_strategy": strategy.value,
                    "search_backend": search_backend_for_cache(),
                    "created_at": now,
                    "expires_at": now + timedelta(seconds=cache_policy["ttl_seconds"]),
                    "request": {
                        "assertion": assertion,
                        "origin_document": origin_document,
                        "search_policy": effective_search_policy,
                    },
                    "response": cache_response,
                }
            },
            upsert=True,
        )
        logger.info(f"[evidence-search] cache_store=true assertion_id={assertion.get('assertion_id')} cache_key={cache_key}")

    logger.info({"event": "retrieval.summary", "assertion_id": str(assertion.get("assertion_id")), **summary,
                 "cache_classification": cache_policy["classification"]})

    if run_id:
        response["evaluation_trace"] = {"run_id": run_id, "cache_hit": False,
                                        "query_execution": trace_requests,
                                        "policy_drops": policy_drops,
                                        "chunk_detail": "CAPTURED",
                                        "limits": {"max_results": effective_search_policy["max_results"],
                                                   "candidate_budget": candidate_budget,
                                                   "max_results_per_domain": EVIDENCE_MAX_RESULTS_PER_DOMAIN,
                                                   "target_citable_sources": target_citable_sources,
                                                   "max_contexts_per_source": EVIDENCE_MAX_CONTEXTS_PER_SOURCE,
                                                   "max_contexts_total": EVIDENCE_MAX_CONTEXTS_TOTAL,
                                                   "window_before": EVIDENCE_CONTEXT_WINDOW_BEFORE,
                                                   "window_after": EVIDENCE_CONTEXT_WINDOW_AFTER,
                                                   "chunk_size_chars": EVIDENCE_CHUNK_SIZE_CHARS,
                                                   "chunk_overlap_chars": EVIDENCE_CHUNK_OVERLAP_CHARS}}
    # Return the fresh response to the validator service.
    return response
