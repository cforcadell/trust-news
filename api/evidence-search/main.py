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
from common.models.async_models import EvidencePreferredDomainsMode
from common.models.evidence_models import EvidenceSearchRequestV2
from common.utils.domain_utils import normalize_domain
from common.utils.logging_utils import configure_single_line_json_logging
from common.utils.mongo import build_mongo_uri_from_env

sys.path.append(os.path.dirname(__file__))
from app.domain_router.profiles_loader import PROFILE_ID, DomainProfileNotFound, load_profile_bundle as load_domain_profile_bundle, normalize_assertion
from app.chunk_ranker import rank_chunks
from app.chunker import build_context_windows, chunk_text
from app.document_fetcher import fetch_main_text
from app.domain_router.resolver import resolve_domains
from app.search.providers import search_with_provider

load_dotenv()

log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
configure_single_line_json_logging(log_level)
logger = logging.getLogger("evidence-search")

MONGO_URI = build_mongo_uri_from_env()
MONGO_DBNAME = os.getenv("MONGO_DBNAME", "newsdb")
MONGO_DOMAIN_PROFILE_COLLECTION = os.getenv("EVIDENCE_DOMAIN_CONFIG_COLLECTION", os.getenv("MONGO_EVIDENCE_DOMAIN_PROFILES_COLLECTION", "evidence_domain_profiles"))
MONGO_NORMALIZATION_CONFIG_COLLECTION = os.getenv("EVIDENCE_NORMALIZATION_CONFIG_COLLECTION", "evidence_normalization_configs")
MONGO_CACHE_COLLECTION = os.getenv("EVIDENCE_SEARCH_CACHE_COLLECTION", "evidence_search_cache")
EVIDENCE_SEARCH_CACHE_TTL_SECONDS = int(os.getenv("EVIDENCE_SEARCH_CACHE_TTL_SECONDS", "86400"))

SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "").lower() or None
API_KEY_PROVIDER = os.getenv("API_KEY_PROVIDER", "")
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


app = FastAPI(title="TrustNews Evidence Search")
mongo_client: Optional[AsyncIOMotorClient] = None
db = None
domain_profile_collection = None
normalization_config_collection = None
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
    query_limit = max(1, int(_policy_value(policy, "max_queries_per_domain", 1) or 1))
    base_queries = base_queries[:query_limit]

    # Group preferred domains by query so providers can receive include-domain filters.
    grouped: Dict[str, List[str]] = {}
    for domain_cfg in domain_resolution.get("preferred_domains") or []:
        domain = str(domain_cfg.get("domain") or "").strip()
        if not domain:
            continue
        for query in base_queries:
            grouped.setdefault(query, [])
            if domain not in grouped[query]:
                grouped[query].append(domain)

    preferred_domains_mode = preferred_domains_mode_for_policy(policy)

    # Build the preferred-domain requests first, preserving the router priority.
    requests = []
    for query in base_queries:
        domains = grouped.get(query, [])
        if domains:
            requests.append({
                "query": query,
                "include_domains": domains,
                "mode": "preferred_domains",
                "external_source_policy": "none",
            })

    if preferred_domains_mode in {EvidencePreferredDomainsMode.EXT_OFFICIAL_FIRST, EvidencePreferredDomainsMode.EXT_ONLY_OFFICIAL}:
        external_source_policy = (
            "official_first"
            if preferred_domains_mode == EvidencePreferredDomainsMode.EXT_OFFICIAL_FIRST
            else "only_official"
        )
        request_mode = (
            "external_official_first"
            if preferred_domains_mode == EvidencePreferredDomainsMode.EXT_OFFICIAL_FIRST
            else "external_only_official"
        )
        for query in base_queries:
            requests.append({
                "query": query,
                "include_domains": None,
                "mode": request_mode,
                "external_source_policy": external_source_policy,
            })

    # Optionally add general fallback searches to avoid returning no evidence when routing is sparse.
    general_fallback = _policy_value(policy, "fallback_to_general_search", False)
    if preferred_domains_mode == EvidencePreferredDomainsMode.LOCAL:
        general_fallback = bool(domain_resolution.get("fallback_used"))
    if preferred_domains_mode != EvidencePreferredDomainsMode.EXT_ONLY_OFFICIAL and general_fallback:
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
    # Reuse the canonical request plan so legacy query logs mirror execution.
    plan = _search_request_plan(assertion, domain_resolution, policy)
    queries: List[str] = []

    # Preferred-domain requests are displayed as site: queries for easy operator inspection.
    for request in plan["requests"]:
        query = request["query"]
        if request["mode"] == "preferred_domains":
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

    # Keep the return value as a plain list because older tests and logs expect it.
    return queries


def build_search_requests(assertion: Dict[str, Any], domain_resolution: Dict[str, Any], policy) -> List[Dict[str, Any]]:
    """Return provider-ready search requests with optional domain filters."""
    # The endpoint executes this structured representation instead of parsing site: strings.
    return _search_request_plan(assertion, domain_resolution, policy)["requests"]


def evidence_from_source_v2(source: Dict[str, Any], rank: int, domain_resolution: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a raw provider result into the evidence-search response schema."""
    # Extract and normalize the domain so it can be matched against router metadata.
    url = source.get("url") or ""
    domain = normalize_domain(urlparse(url).netloc)
    matched = next((d for d in domain_resolution.get("preferred_domains", []) if d.get("domain") == domain), {})

    # Use router source metadata when available, otherwise fall back to domain heuristics.
    source_type = matched.get("source_type") or source_type_for_domain(domain)
    trust_score = float(matched.get("trust_score", 0.3) or 0.3)

    # Preserve useful provider text and add stable ids for downstream validator prompts.
    return {
        "source_id": f"source-{rank}",
        "title": source.get("title") or url,
        "url": url,
        "domain": domain,
        "source_type": source_type,
        "snippet": source.get("content") or source.get("snippet") or useful_excerpt(source),
        "rank": rank,
        "trust_score": trust_score,
        "retrieved_at": iso(utc_now()),
        "why_selected": matched.get("reason") or "Matched contextual search policy",
        "matched_profiles": matched.get("matched_profiles", []),
    }


def source_type_for_domain(domain: str) -> str:
    """Infer a broad source type when no profile metadata matched the domain."""
    # Normalize before marker checks so provider URL variations do not change classification.
    d = normalize_domain(domain)
    official_markers = (".gov", ".gob", ".int", "who.int", "un.org", "europa.eu", "ec.europa.eu", "eurostat.ec.europa.eu", "gencat.cat", "idescat.cat", "ine.es")
    agencies = ("reuters.com", "apnews.com", "afp.com", "efe.com", "bloomberg.com")

    # Apply a simple taxonomy used as a fallback trust signal.
    if any(marker in d for marker in official_markers):
        return "official"
    if any(marker in d for marker in agencies):
        return "news_agency"
    if d:
        return "media"
    return "unknown"


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


def evidence_cache_key(assertion: Dict[str, Any], policy: Any, profile_version: str) -> str:
    """Build the cache key for an assertion, policy, profile version, and search backend."""
    # Include every input that can change the evidence search result.
    payload = {
        "schema_version": "evidence-search-request-v2",
        "assertion": normalized_assertion_for_cache(assertion),
        "search_policy": policy_for_cache(policy),
        "profile_version": profile_version,
        "search_backend": search_backend_for_cache(),
    }

    # Hash the canonical payload so Mongo stores a compact, index-friendly key.
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def preferred_profile_id_for_policy(policy: Any) -> str:
    """Resolve the requested profile id, falling back to the default profile."""
    # Support both dict policies and Pydantic model instances.
    if isinstance(policy, dict):
        raw_profile_id = policy.get("preferred_profile_id")
    else:
        raw_profile_id = getattr(policy, "preferred_profile_id", "")

    # Empty strings should behave like an omitted profile id.
    profile_id = str(raw_profile_id or "").strip()
    return profile_id or PROFILE_ID


def preferred_domains_mode_for_policy(policy: Any) -> EvidencePreferredDomainsMode:
    """Return the configured evidence-search domain preference mode."""
    if isinstance(policy, dict):
        raw_mode = policy.get("use_preferred_domains", EvidencePreferredDomainsMode.NONE)
    else:
        raw_mode = getattr(policy, "use_preferred_domains", EvidencePreferredDomainsMode.NONE)
    if isinstance(raw_mode, EvidencePreferredDomainsMode):
        return raw_mode
    return EvidencePreferredDomainsMode(str(raw_mode or "").strip().upper())


async def load_profile_bundle(profile_id: str = PROFILE_ID):
    """Load one complete profile plus its independent normalization configs."""
    try:
        return await load_domain_profile_bundle(
            domain_profile_collection, normalization_config_collection, profile_id=profile_id
        )
    except DomainProfileNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)}) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail={"code": "DOMAIN_PROFILE_INVALID", "message": str(exc)}) from exc


def empty_domain_resolution() -> Dict[str, Any]:
    """Return the domain-resolution shape used when preferred routing is disabled."""
    # Preserve the response contract even when no domain router is involved.
    return {
        "selected_profiles": [],
        "preferred_domains": [],
        "fallback_used": True,
        "reason": "preferred_domains_disabled",
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
    """Build a traceable context from the provider snippet for compatibility/fallback."""
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
) -> List[Dict[str, Any]]:
    """Normalize search results and optionally enrich them with selected document contexts."""
    evidences: List[Dict[str, Any]] = []
    total_contexts = 0

    if EVIDENCE_FETCH_FULL_TEXT:
        logger.info(f"[evidence-search] full_text_enrichment_start=true assertion_id={assertion.get('assertion_id')}")

    for idx, source in enumerate(raw_results[:max_results], start=1):
        evidence = evidence_from_source_v2(source, idx, domain_resolution)
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
    """Create indexes for one-document profiles, normalization configs, and cache."""
    if domain_profile_collection is not None:
        await domain_profile_collection.create_index("profile_id", name="uniq_domain_profile_id", unique=True)
    if normalization_config_collection is not None:
        await normalization_config_collection.create_index("config_type", name="uniq_normalization_config_type", unique=True)
    if cache_collection is not None:
        await cache_collection.create_index("cache_key", unique=True)
        await cache_collection.create_index("assertion_hash")
        await cache_collection.create_index("created_at")
        await cache_collection.create_index("expires_at", expireAfterSeconds=0)


@app.on_event("startup")
async def startup_event():
    """Initialize Mongo collections and indexes when the FastAPI app starts."""
    # Create the shared Mongo client and bind the collections used by handlers.
    global mongo_client, db, domain_profile_collection, normalization_config_collection, cache_collection
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[MONGO_DBNAME]
    domain_profile_collection = db[MONGO_DOMAIN_PROFILE_COLLECTION]
    normalization_config_collection = db[MONGO_NORMALIZATION_CONFIG_COLLECTION]
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


@app.post("/search/evidence")
async def search_evidence(req: EvidenceSearchRequestV2):
    """Search for evidence supporting a validated assertion payload."""
    # Validate the minimum assertion text required to build any useful query.
    assertion = req.assertion.model_dump(mode="json")
    text = str(assertion.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="assertion.text is required")

    # Load routing profiles only when the request policy enables local preferred domains.
    preferred_domains_mode = preferred_domains_mode_for_policy(req.search_policy)
    use_local_preferred_domains = preferred_domains_mode == EvidencePreferredDomainsMode.LOCAL
    preferred_profile_id = preferred_profile_id_for_policy(req.search_policy)
    if use_local_preferred_domains:
        profile, normalization_configs, profile_version = await load_profile_bundle(preferred_profile_id)
        assertion = normalize_assertion(assertion, normalization_configs)
    else:
        profile, profile_version = None, f"preferred-domains-{preferred_domains_mode.value.lower()}"

    # Build the cache key from the normalized assertion, policy, and profile version.
    cache_key = evidence_cache_key(assertion, req.search_policy, profile_version)
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

    # Resolve contextual preferred domains only for LOCAL mode.
    if use_local_preferred_domains:
        domain_resolution = resolve_domains(assertion, profile, max_domains=req.search_policy.max_domains)
    else:
        domain_resolution = empty_domain_resolution()
        domain_resolution["reason"] = f"{preferred_domains_mode.value.lower()}_mode"
    domain_resolution["preferred_domains_mode"] = preferred_domains_mode.value
    domain_resolution["profile_id"] = profile.profile_id if use_local_preferred_domains else None
    domain_resolution["profile_version"] = profile_version
    effective_search_policy = req.search_policy.model_dump(mode="json") if hasattr(req.search_policy, "model_dump") else dict(vars(req.search_policy))
    if use_local_preferred_domains:
        selection_policy = profile.selection_policy
        effective_search_policy.update({
            "mode": "local_scored_domains",
            "preferred_profile_id": profile.profile_id,
            "domain_scoring_enabled": True,
            "max_domains": min(req.search_policy.max_domains, selection_policy.max_domains),
            "max_results": selection_policy.max_results,
            "max_queries_per_domain": selection_policy.max_queries_per_domain,
            "fallback_to_general_search": selection_policy.fallback_to_general_search,
            "selected_domains": domain_resolution.get("selected_domains", []),
        })
    else:
        effective_search_policy["domain_scoring_enabled"] = False
        effective_search_policy["selected_domains"] = []

    # Log the routing decision to make evidence selection auditable.
    logger_prefix = f"[domain-router] assertion_id={assertion.get('assertion_id')}"
    logger.info(
        f"{logger_prefix} preferred_domains_mode={preferred_domains_mode.value} "
        f"preferred_profile_id={preferred_profile_id if use_local_preferred_domains else None} "
        f"selected_profiles={domain_resolution.get('selected_profiles')}"
    )

    # Log the legacy rendered query list for easier debugging in existing logs.
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

    # Execute live provider searches when an API key is configured.
    raw_results: List[Dict[str, Any]] = []
    successful_searches = 0
    provider_errors: List[Dict[str, str]] = []
    provider_name = SEARCH_PROVIDER
    if API_KEY_PROVIDER:
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
        # Raise before cache storage so transient provider failures are never cached.
        if search_requests and successful_searches == 0:
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "EVIDENCE_PROVIDER_FAILED",
                    "message": "All evidence provider requests failed",
                    "provider": provider_name,
                    "errors": provider_errors,
                    "search_policy": effective_search_policy,
                },
            )
    else:
        # Without a provider key, return routed domains as placeholder evidence.
        for idx, domain_cfg in enumerate(domain_resolution.get("preferred_domains") or [], start=1):
            raw_results.append({
                "url": f"https://{domain_cfg['domain']}/",
                "title": domain_cfg.get("reason") or domain_cfg["domain"],
                "content": "Domain selected by contextual routing; configure API_KEY_PROVIDER for live snippets.",
                "score": domain_cfg.get("weight", 0.0),
            })

    # Normalize raw provider results into the public evidence response contract.
    evidences = await build_evidences_with_optional_contexts(
        assertion,
        raw_results,
        domain_resolution,
        max_results=effective_search_policy["max_results"],
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
                    "search_strategy": effective_search_policy["mode"],
                    "preferred_domains_mode": preferred_domains_mode.value,
                    "search_backend": search_backend_for_cache(),
                    "created_at": now,
                    "expires_at": now + timedelta(seconds=EVIDENCE_SEARCH_CACHE_TTL_SECONDS),
                    "request": {
                        "assertion": assertion,
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
