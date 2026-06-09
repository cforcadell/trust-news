import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from common.models.evidence_models import EvidenceSearchRequestV2
from common.utils.domain_utils import normalize_domain
from common.utils.mongo import build_mongo_uri_from_env

sys.path.append(os.path.dirname(__file__))
from app.domain_router.profiles_loader import PROFILE_ID, PROFILE_INDEX_DOC_TYPE, PROFILE_SUBSET_DOC_TYPE, load_profiles_from_mongo
from app.domain_router.resolver import resolve_domains
from app.search.providers import search_with_provider

load_dotenv()

MONGO_URI = build_mongo_uri_from_env()
MONGO_DBNAME = os.getenv("MONGO_DBNAME", "newsdb")
MONGO_DOMAIN_PROFILE_COLLECTION = os.getenv("EVIDENCE_DOMAIN_CONFIG_COLLECTION", os.getenv("MONGO_EVIDENCE_DOMAIN_PROFILES_COLLECTION", "evidence_domain_profiles"))
MONGO_CACHE_COLLECTION = os.getenv("EVIDENCE_SEARCH_CACHE_COLLECTION", "evidence_search_cache")
EVIDENCE_SEARCH_CACHE_TTL_SECONDS = int(os.getenv("EVIDENCE_SEARCH_CACHE_TTL_SECONDS", "86400"))

SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "").lower() or None
API_KEY_PROVIDER = os.getenv("API_KEY_PROVIDER", "")


app = FastAPI(title="TrustNews Evidence Search")
mongo_client: Optional[AsyncIOMotorClient] = None
db = None
domain_profile_collection = None
cache_collection = None



def base_queries_for_assertion(assertion: Dict[str, Any]) -> List[str]:
    """Build initial search queries from assertion hints and contextual metadata."""
    # Prefer explicit search suggestions because they are already optimized upstream.
    hints = assertion.get("search_hints") or {}
    context = assertion.get("context") or {}
    base_queries = [str(q).strip() for q in hints.get("suggested_queries") or [] if str(q).strip()]

    # If no suggestion exists, compose a compact query from text, keywords, time, entities, and locations.
    if not base_queries:
        terms = [assertion.get("text", "")] + list(hints.get("search_keywords") or [])
        terms.extend(item.get("value", "") for item in context.get("temporal_context") or [] if item.get("value"))
        terms.extend(item.get("name", "") for item in context.get("entities") or [] if item.get("name"))
        terms.extend(item.get("name", "") for item in context.get("locations") or [] if item.get("name"))
        base = " ".join(str(t).strip() for t in terms if str(t).strip())
        base_queries = [base] if base else [assertion.get("text", "")]

    # Drop empty values so later planning only works with executable query strings.
    return [q for q in base_queries if q]


def _search_request_plan(assertion: Dict[str, Any], domain_resolution: Dict[str, Any], policy) -> Dict[str, Any]:
    """Create the structured search plan shared by query logging and execution."""
    # Limit query fan-out according to the active evidence-search policy.
    base_queries = base_queries_for_assertion(assertion)
    query_limit = max(1, int(getattr(policy, "max_queries_per_domain", 1) or 1))
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

    # Build the preferred-domain requests first, preserving the router priority.
    requests = []
    for query in base_queries:
        domains = grouped.get(query, [])
        if domains:
            requests.append({"query": query, "include_domains": domains, "mode": "preferred_domains"})

    # Optionally add general fallback searches to avoid returning no evidence when routing is sparse.
    if getattr(policy, "fallback_to_general_search", False):
        for query in base_queries:
            requests.append({"query": query, "include_domains": None, "mode": "general_fallback"})

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
            for domain in request.get("include_domains") or []:
                queries.append(f"site:{domain} {query}".strip())
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


async def load_profile_bundle(profile_id: str = PROFILE_ID) -> tuple[Dict[str, Any], str]:
    """Load the domain routing profile bundle and translate loader errors to HTTP."""
    # Keep Mongo/profile validation failures visible to API callers as service errors.
    try:
        return await load_profiles_from_mongo(domain_profile_collection, profile_id=profile_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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



async def call_search_provider(query: str, max_sources: int, include_domains: Optional[List[str]] = None) -> Dict[str, Any]:
    """Call the configured provider with an optional include-domain filter."""
    # Delegate provider-specific payload details to the search provider module.
    return await search_with_provider(SEARCH_PROVIDER, query, max_sources, include_domains=include_domains)


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
    """Create Mongo indexes required by profile lookup and evidence cache access."""
    # Ensure profile documents remain unique by profile id and subset.
    if domain_profile_collection is not None:
        index_names = [idx.get("name") async for idx in domain_profile_collection.list_indexes()]
        if "idx_profile_docs" in index_names:
            await domain_profile_collection.drop_index("idx_profile_docs")
        await domain_profile_collection.create_index(
            [("doc_type", 1), ("profile_id", 1)],
            name="uniq_profile_index",
            unique=True,
            partialFilterExpression={"doc_type": PROFILE_INDEX_DOC_TYPE},
        )
        await domain_profile_collection.create_index(
            [("doc_type", 1), ("profile_id", 1), ("subset", 1)],
            name="uniq_profile_subset",
            unique=True,
            partialFilterExpression={"doc_type": PROFILE_SUBSET_DOC_TYPE},
        )

    # Cache indexes support lookup by cache key and TTL-based expiry.
    if cache_collection is not None:
        await cache_collection.create_index("cache_key", unique=True)
        await cache_collection.create_index("assertion_hash")
        await cache_collection.create_index("created_at")
        await cache_collection.create_index("expires_at", expireAfterSeconds=0)


@app.on_event("startup")
async def startup_event():
    """Initialize Mongo collections and indexes when the FastAPI app starts."""
    # Create the shared Mongo client and bind the collections used by handlers.
    global mongo_client, db, domain_profile_collection, cache_collection
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[MONGO_DBNAME]
    domain_profile_collection = db[MONGO_DOMAIN_PROFILE_COLLECTION]
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
    print(f"[evidence-search] cache_clear=true deleted_count={result.deleted_count}")
    return {
        "status": "ok",
        "cache_collection": MONGO_CACHE_COLLECTION,
        "deleted_count": result.deleted_count,
    }


@app.post("/search/evidence")
async def search_evidence(req: EvidenceSearchRequestV2):
    """Search for evidence supporting a validated assertion payload."""
    # Validate the minimum assertion text required to build any useful query.
    assertion = req.assertion
    text = str(assertion.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="assertion.text is required")

    # Load routing profiles only when the request policy enables preferred domains.
    use_preferred_domains = bool(req.search_policy.use_preferred_domains)
    preferred_profile_id = preferred_profile_id_for_policy(req.search_policy)
    if use_preferred_domains:
        profiles, profile_version = await load_profile_bundle(preferred_profile_id)
    else:
        profiles, profile_version = {}, "preferred-domains-disabled"

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
            print(f"[evidence-search] cache_hit=true assertion_id={assertion.get('assertion_id')} cache_key={cache_key}")
            return response

    # Resolve contextual preferred domains, or keep the same response shape when disabled.
    if use_preferred_domains:
        domain_resolution = resolve_domains(assertion, profiles, max_domains=req.search_policy.max_domains)
    else:
        domain_resolution = empty_domain_resolution()
    domain_resolution["profile_id"] = preferred_profile_id if use_preferred_domains else None
    domain_resolution["profile_version"] = profile_version

    # Log the routing decision to make evidence selection auditable.
    logger_prefix = f"[domain-router] assertion_id={assertion.get('assertion_id')}"
    print(
        f"{logger_prefix} use_preferred_domains={use_preferred_domains} "
        f"preferred_profile_id={preferred_profile_id if use_preferred_domains else None} "
        f"selected_profiles={domain_resolution.get('selected_profiles')}"
    )

    # Log the legacy rendered query list for easier debugging in existing logs.
    queries = build_queries_v2(assertion, domain_resolution, req.search_policy)
    for query in queries:
        print(f"[evidence-search] query='{query}'")

    # Build provider-ready requests and log their domain filters.
    search_requests = build_search_requests(assertion, domain_resolution, req.search_policy)
    for search_request in search_requests:
        print(
            "[evidence-search] search_request "
            f"provider='{SEARCH_PROVIDER}' "
            f"query='{search_request['query']}' "
            f"include_domains={search_request.get('include_domains')} "
            f"mode={search_request.get('mode')}"
        )

    # Execute live provider searches when an API key is configured.
    raw_results: List[Dict[str, Any]] = []
    provider_name = SEARCH_PROVIDER
    if API_KEY_PROVIDER:
        for search_request in search_requests:
            query = search_request["query"]
            include_domains = search_request.get("include_domains")
            try:
                # Merge each provider response into the ordered, deduplicated result set.
                search_results = await search_with_provider(provider_name, query, req.search_policy.max_results, include_domains=include_domains or None)
                raw_results = merge_search_results(
                    raw_results,
                    search_results.get("results", []) or [],
                    max_sources=req.search_policy.max_results,
                )
                if len(raw_results) >= req.search_policy.max_results:
                    break
            except Exception as e:
                print(f"[evidence-search] search provider failed provider='{provider_name}' query='{query}': {e}")
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
    evidences = [evidence_from_source_v2(source, idx, domain_resolution) for idx, source in enumerate(raw_results[: req.search_policy.max_results], start=1)]
    response = {
        "schema_version": "evidence-search-response-v2",
        "assertion_id": assertion.get("assertion_id"),
        "domain_resolution": domain_resolution,
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
                    "search_backend": search_backend_for_cache(),
                    "created_at": now,
                    "expires_at": now + timedelta(seconds=EVIDENCE_SEARCH_CACHE_TTL_SECONDS),
                    "request": {
                        "assertion": assertion,
                        "search_policy": req.search_policy.model_dump(mode="json"),
                    },
                    "response": response,
                }
            },
            upsert=True,
        )
        print(f"[evidence-search] cache_store=true assertion_id={assertion.get('assertion_id')} cache_key={cache_key}")

    # Return the fresh response to the validator service.
    return response
