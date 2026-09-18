import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from common.models.async_models import EvidenceSearchStrategy
from common.models.evidence_models import EvidenceSearchRequestV2, EvidenceSearchResponseV2
from common.routing_taxonomy import SourceType
from common.search.normalization import normalize_domain, normalize_url
from common.utils.logging_utils import configure_single_line_json_logging
from common.utils.mongo import build_mongo_uri_from_env

sys.path.append(os.path.dirname(__file__))
from app.chunk_ranker import rank_chunks
from app.chunker import build_context_windows, chunk_text
from app.document_fetcher import fetch_main_text
from common.search import search_with_provider

load_dotenv()

log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
configure_single_line_json_logging(log_level)
logger = logging.getLogger("evidence-search")

MONGO_URI = build_mongo_uri_from_env()
MONGO_DBNAME = os.getenv("MONGO_DBNAME", "newsdb")
MONGO_CACHE_COLLECTION = os.getenv("EVIDENCE_SEARCH_CACHE_COLLECTION", "evidence_search_cache_v2")
EVIDENCE_SEARCH_CACHE_TTL_SECONDS = int(os.getenv("EVIDENCE_SEARCH_CACHE_TTL_SECONDS", "86400"))

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



def _fold_query_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


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
    """Append missing assertion context to a provider query without replacing model suggestions."""
    query = str(query or "").strip()
    folded_query = _fold_query_text(query)
    missing = [term for term in contextual_query_terms(assertion) if _fold_query_text(term) not in folded_query]
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

    # Drop empty values so later planning only works with executable query strings.
    return [q for q in base_queries if q]


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
            })

    if strategy == EvidenceSearchStrategy.EXT_OFFICIAL_FIRST:
        for query in base_queries:
            requests.append({
                "query": query,
                "include_domains": None,
                "mode": "general_fallback",
                "external_source_policy": "none",
            })

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


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    # Centralize time creation so cache timestamps use the same timezone convention.
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    """Serialize datetimes as UTC ISO-8601 strings."""
    # Normalize any aware datetime to UTC before exposing it in API responses.
    return dt.astimezone(timezone.utc).isoformat()


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
        "search_max_results": os.getenv("SEARCH_MAX_RESULTS", "5"),
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


def snippet_context_for_evidence(evidence: Dict[str, Any], score: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Build a traceable context from the provider snippet when full text is unavailable."""
    snippet = re.sub(r"\s+", " ", evidence.get("snippet") or "").strip()
    if not snippet:
        return None
    return {
        "context_id": f"{evidence.get('source_id')}-context-1",
        "selected_chunk_id": None,
        "included_chunk_ids": [],
        "text": snippet,
        "score": score,
        "origin": "search_snippet",
        "char_length": len(snippet),
    }


def attach_snippet_fallback(evidence: Dict[str, Any], fetch_status: str) -> Dict[str, Any]:
    """Attach snippet context metadata without replacing the normalized evidence fields."""
    context = snippet_context_for_evidence(evidence)
    evidence["contexts"] = [context] if context else []
    evidence["fetch_status"] = fetch_status
    if fetch_status != "not_requested":
        logger.info(f"[evidence-search] fallback_to_snippet=true source_id={evidence.get('source_id')} fetch_status={fetch_status}")
    return evidence


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
) -> List[Dict[str, Any]]:
    """Normalize search results and optionally enrich them with selected document contexts."""
    evidences: List[Dict[str, Any]] = []
    total_contexts = 0

    if EVIDENCE_FETCH_FULL_TEXT:
        logger.info(f"[evidence-search] full_text_enrichment_start=true assertion_id={assertion.get('assertion_id')}")

    for idx, source in enumerate(raw_results[:max_results], start=1):
        evidence = evidence_from_source_v2(source, idx, domain_resolution, origin_document)
        source_id = evidence["source_id"]

        if not EVIDENCE_FETCH_FULL_TEXT:
            attach_snippet_fallback(evidence, "not_requested")
            if evidence.get("contexts"):
                total_contexts += 1
            evidences.append(evidence)
            continue

        if total_contexts >= EVIDENCE_MAX_CONTEXTS_TOTAL:
            attach_snippet_fallback(evidence, "not_requested")
            evidences.append(evidence)
            continue

        url = evidence.get("url") or ""
        logger.info(f"[evidence-search] downloading_url source_id={source_id} url={url}")
        fetch_result = await fetch_main_text(url, timeout=EVIDENCE_HTTP_TIMEOUT, user_agent=EVIDENCE_USER_AGENT)
        evidence["fetch_status"] = fetch_result.status
        logger.info(f"[evidence-search] fetch_status source_id={source_id} status={fetch_result.status} error={fetch_result.error}")

        if fetch_result.status != "ok":
            attach_snippet_fallback(evidence, fetch_result.status)
            evidence["contexts_total"] = len(evidence.get("contexts") or [])
            if evidence.get("contexts"):
                total_contexts += 1
            evidences.append(evidence)
            continue

        document_length = fetch_result.document_length_chars
        chunks = chunk_text(source_id, fetch_result.text, EVIDENCE_CHUNK_SIZE_CHARS, EVIDENCE_CHUNK_OVERLAP_CHARS)
        ranked = rank_chunks(assertion, chunks)
        remaining_contexts = max(0, EVIDENCE_MAX_CONTEXTS_TOTAL - total_contexts)
        contexts = build_context_windows(
            source_id,
            chunks,
            ranked,
            max_contexts=min(EVIDENCE_MAX_CONTEXTS_PER_SOURCE, remaining_contexts),
            before=EVIDENCE_CONTEXT_WINDOW_BEFORE,
            after=EVIDENCE_CONTEXT_WINDOW_AFTER,
            min_context_chars=EVIDENCE_MIN_CONTEXT_CHARS,
        )

        evidence["document_length_chars"] = document_length
        evidence["chunks_total"] = len(chunks)
        evidence["contexts_total"] = len(contexts)
        logger.info(f"[evidence-search] document_length_chars source_id={source_id} value={document_length}")
        logger.info(f"[evidence-search] chunks_total source_id={source_id} value={len(chunks)}")
        logger.info(f"[evidence-search] contexts_selected source_id={source_id} value={len(contexts)}")

        if not chunks or not contexts:
            attach_snippet_fallback(evidence, "no_ranked_chunks")
            evidence["contexts_total"] = len(evidence.get("contexts") or [])
            if evidence.get("contexts"):
                total_contexts += 1
            evidences.append(evidence)
            continue

        evidence["contexts"] = contexts
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
            dedupe_key = url or f"{result.get('title', '')}:{result.get('content', '')}"
            if dedupe_key in seen_urls:
                continue
            seen_urls.add(dedupe_key)
            merged.append(result)
            if len(merged) >= max_sources:
                return merged
    return merged



async def ensure_indexes():
    """Create indexes for the evidence response cache."""
    if cache_collection is not None:
        await cache_collection.create_index("cache_key", name="cache_key_1", unique=True)
        await cache_collection.create_index("assertion_hash", name="assertion_hash_1")
        await cache_collection.create_index("created_at", name="created_at_1")
        await cache_collection.create_index("expires_at", name="expires_at_ttl", expireAfterSeconds=0)


@app.on_event("startup")
async def startup_event():
    """Initialize Mongo collections and indexes when the FastAPI app starts."""
    # Create the shared Mongo client and bind the collections used by handlers.
    global mongo_client, db, cache_collection
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[MONGO_DBNAME]
    cache_collection = db[MONGO_CACHE_COLLECTION]

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
async def search_evidence(req: EvidenceSearchRequestV2):
    """Search for evidence supporting a validated assertion payload."""
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
    if cache_collection is not None:
        cached = await cache_collection.find_one({"cache_key": cache_key, "expires_at": {"$gt": now}}, {"_id": 0})
        if cached and cached.get("response"):
            response = dict(cached["response"])
            response["cached"] = True
            response["cache_key"] = cache_key
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
    successful_searches = 0
    provider_errors: List[Dict[str, str]] = []
    provider_name = SEARCH_PROVIDER
    for search_request in search_requests:
        query = search_request["query"]
        include_domains = search_request.get("include_domains")
        external_source_policy = search_request.get("external_source_policy") or "none"
        try:
            # Merge each provider response into the ordered, deduplicated result set.
            search_results = await search_with_provider(
                provider_name,
                query,
                effective_search_policy["max_results"],
                include_domains=include_domains or None,
                external_source_policy=external_source_policy,
            )
            successful_searches += 1
            raw_results = merge_search_results(
                raw_results,
                search_results.get("results", []) or [],
                max_sources=effective_search_policy["max_results"],
            )
            if len(raw_results) >= effective_search_policy["max_results"]:
                break
        except Exception as e:
            logger.warning(f"[evidence-search] search provider failed provider='{provider_name}' query='{query}': {e}")
            provider_errors.append({"provider": provider_name, "query": query, "error": str(e) or e.__class__.__name__})

    # Zero results is valid. Zero successful requests is a dependency failure.
    if search_requests and successful_searches == 0:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "EVIDENCE_PROVIDER_FAILED", "message": "All evidence provider requests failed",
                "provider": provider_name, "errors": provider_errors, "search_policy": effective_search_policy,
            },
        )

    if strategy == EvidenceSearchStrategy.EXT_ONLY_OFFICIAL:
        raw_results = [
            item for item in raw_results
            if is_official_source_type(
                source_type_for_domain(normalize_domain(urlparse(item.get("url") or "").netloc))
            )
        ]

    # Normalize raw provider results into the public evidence response contract.
    evidences = await build_evidences_with_optional_contexts(
        assertion,
        raw_results,
        domain_resolution,
        max_results=effective_search_policy["max_results"],
        origin_document=origin_document,
    )
    response = {
        "schema_version": "evidence-search-response-v2",
        "assertion_id": assertion.get("assertion_id"),
        "domain_resolution": domain_resolution,
        "search_policy": effective_search_policy,
        "queries_executed": search_requests,
        "evidences": evidences,
        "cached": False,
        "cache_key": cache_key,
    }

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
                    "expires_at": now + timedelta(seconds=EVIDENCE_SEARCH_CACHE_TTL_SECONDS),
                    "request": {
                        "assertion": assertion,
                        "origin_document": origin_document,
                        "search_policy": effective_search_policy,
                    },
                    "response": response,
                }
            },
            upsert=True,
        )
        logger.info(f"[evidence-search] cache_store=true assertion_id={assertion.get('assertion_id')} cache_key={cache_key}")

    # Return the fresh response to the validator service.
    return response
