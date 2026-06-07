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
    hints = assertion.get("search_hints") or {}
    context = assertion.get("context") or {}
    base_queries = [str(q).strip() for q in hints.get("suggested_queries") or [] if str(q).strip()]
    if not base_queries:
        terms = [assertion.get("text", "")] + list(hints.get("search_keywords") or [])
        terms.extend(item.get("value", "") for item in context.get("temporal_context") or [] if item.get("value"))
        terms.extend(item.get("name", "") for item in context.get("entities") or [] if item.get("name"))
        terms.extend(item.get("name", "") for item in context.get("locations") or [] if item.get("name"))
        base = " ".join(str(t).strip() for t in terms if str(t).strip())
        base_queries = [base] if base else [assertion.get("text", "")]
    return [q for q in base_queries if q]


def _search_request_plan(assertion: Dict[str, Any], domain_resolution: Dict[str, Any], policy) -> Dict[str, Any]:
    base_queries = base_queries_for_assertion(assertion)
    query_limit = max(1, int(getattr(policy, "max_queries_per_domain", 1) or 1))
    base_queries = base_queries[:query_limit]

    grouped: Dict[str, List[str]] = {}
    for domain_cfg in domain_resolution.get("preferred_domains") or []:
        domain = str(domain_cfg.get("domain") or "").strip()
        if not domain:
            continue
        for query in base_queries:
            grouped.setdefault(query, [])
            if domain not in grouped[query]:
                grouped[query].append(domain)

    requests = []
    for query in base_queries:
        domains = grouped.get(query, [])
        if domains:
            requests.append({"query": query, "include_domains": domains, "mode": "preferred_domains"})

    if getattr(policy, "fallback_to_general_search", False):
        for query in base_queries:
            requests.append({"query": query, "include_domains": None, "mode": "general_fallback"})

    return {"base_queries": base_queries, "requests": requests}


def build_queries_v2(assertion: Dict[str, Any], domain_resolution: Dict[str, Any], policy) -> List[str]:
    plan = _search_request_plan(assertion, domain_resolution, policy)
    queries: List[str] = []

    for request in plan["requests"]:
        query = request["query"]
        if request["mode"] == "preferred_domains":
            for domain in request.get("include_domains") or []:
                queries.append(f"site:{domain} {query}".strip())
        else:
            queries.append(query)

    return queries


def build_search_requests(assertion: Dict[str, Any], domain_resolution: Dict[str, Any], policy) -> List[Dict[str, Any]]:
    return _search_request_plan(assertion, domain_resolution, policy)["requests"]


def evidence_from_source_v2(source: Dict[str, Any], rank: int, domain_resolution: Dict[str, Any]) -> Dict[str, Any]:
    url = source.get("url") or ""
    domain = normalize_domain(urlparse(url).netloc)
    matched = next((d for d in domain_resolution.get("preferred_domains", []) if d.get("domain") == domain), {})
    source_type = matched.get("source_type") or source_type_for_domain(domain)
    trust_score = float(matched.get("trust_score", 0.3) or 0.3)
    return {
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
    d = normalize_domain(domain)
    official_markers = (".gov", ".gob", ".int", "who.int", "un.org", "europa.eu", "ec.europa.eu", "eurostat.ec.europa.eu", "gencat.cat", "idescat.cat", "ine.es")
    agencies = ("reuters.com", "apnews.com", "afp.com", "efe.com", "bloomberg.com")
    if any(marker in d for marker in official_markers):
        return "official"
    if any(marker in d for marker in agencies):
        return "news_agency"
    if d:
        return "media"
    return "unknown"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def normalized_assertion_for_cache(assertion: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(assertion or {})
    if "text" in normalized:
        normalized["text"] = re.sub(r"\s+", " ", str(normalized.get("text") or "").strip()).lower()
    return normalized


def policy_for_cache(policy: Any) -> Dict[str, Any]:
    if hasattr(policy, "model_dump"):
        return policy.model_dump(mode="json")
    if isinstance(policy, dict):
        return policy
    return vars(policy)


def evidence_cache_key(assertion: Dict[str, Any], policy: Any, profile_version: str) -> str:
    payload = {
        "schema_version": "evidence-search-request-v2",
        "assertion": normalized_assertion_for_cache(assertion),
        "search_policy": policy_for_cache(policy),
        "profile_version": profile_version,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def preferred_profile_id_for_policy(policy: Any) -> str:
    if isinstance(policy, dict):
        raw_profile_id = policy.get("preferred_profile_id")
    else:
        raw_profile_id = getattr(policy, "preferred_profile_id", "")
    profile_id = str(raw_profile_id or "").strip()
    return profile_id or PROFILE_ID


async def load_profile_bundle(profile_id: str = PROFILE_ID) -> tuple[Dict[str, Any], str]:
    try:
        return await load_profiles_from_mongo(domain_profile_collection, profile_id=profile_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def empty_domain_resolution() -> Dict[str, Any]:
    return {
        "selected_profiles": [],
        "preferred_domains": [],
        "fallback_used": True,
        "reason": "preferred_domains_disabled",
    }



def useful_excerpt(result: Dict[str, Any]) -> str:
    raw = result.get("raw_content") or ""
    content = result.get("content") or ""
    text = re.sub(r"\s+", " ", raw or content).strip()
    return text[:900]



async def call_search_provider(query: str, max_sources: int, include_domains: Optional[List[str]] = None) -> Dict[str, Any]:
    return await search_with_provider(SEARCH_PROVIDER, query, max_sources, include_domains=include_domains)


def merge_search_results(*result_groups: List[Dict[str, Any]], max_sources: int) -> List[Dict[str, Any]]:
    merged = []
    seen_urls = set()
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
    if cache_collection is not None:
        await cache_collection.create_index("cache_key", unique=True)
        await cache_collection.create_index("assertion_hash")
        await cache_collection.create_index("created_at")
        await cache_collection.create_index("expires_at", expireAfterSeconds=0)


@app.on_event("startup")
async def startup_event():
    global mongo_client, db, domain_profile_collection, cache_collection
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[MONGO_DBNAME]
    domain_profile_collection = db[MONGO_DOMAIN_PROFILE_COLLECTION]
    cache_collection = db[MONGO_CACHE_COLLECTION]
    await ensure_indexes()


@app.on_event("shutdown")
async def shutdown_event():
    if mongo_client:
        mongo_client.close()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "evidence-search"}


@app.delete("/admin/cache")
async def clear_cache():
    if cache_collection is None:
        raise HTTPException(status_code=503, detail="Evidence search cache is not initialized")
    result = await cache_collection.delete_many({})
    print(f"[evidence-search] cache_clear=true deleted_count={result.deleted_count}")
    return {
        "status": "ok",
        "cache_collection": MONGO_CACHE_COLLECTION,
        "deleted_count": result.deleted_count,
    }


@app.post("/search/evidence")
async def search_evidence(req: EvidenceSearchRequestV2):
    assertion = req.assertion
    text = str(assertion.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="assertion.text is required")

    use_preferred_domains = bool(req.search_policy.use_preferred_domains)
    preferred_profile_id = preferred_profile_id_for_policy(req.search_policy)
    if use_preferred_domains:
        profiles, profile_version = await load_profile_bundle(preferred_profile_id)
    else:
        profiles, profile_version = {}, "preferred-domains-disabled"

    cache_key = evidence_cache_key(assertion, req.search_policy, profile_version)
    now = utc_now()

    if cache_collection is not None:
        cached = await cache_collection.find_one({"cache_key": cache_key, "expires_at": {"$gt": now}}, {"_id": 0})
        if cached and cached.get("response"):
            response = dict(cached["response"])
            response["cached"] = True
            response["cache_key"] = cache_key
            print(f"[evidence-search] cache_hit=true assertion_id={assertion.get('assertion_id')} cache_key={cache_key}")
            return response
    if use_preferred_domains:
        domain_resolution = resolve_domains(assertion, profiles, max_domains=req.search_policy.max_domains)
    else:
        domain_resolution = empty_domain_resolution()
    domain_resolution["profile_id"] = preferred_profile_id if use_preferred_domains else None
    domain_resolution["profile_version"] = profile_version
    logger_prefix = f"[domain-router] assertion_id={assertion.get('assertion_id')}"
    print(
        f"{logger_prefix} use_preferred_domains={use_preferred_domains} "
        f"preferred_profile_id={preferred_profile_id if use_preferred_domains else None} "
        f"selected_profiles={domain_resolution.get('selected_profiles')}"
    )

    queries = build_queries_v2(assertion, domain_resolution, req.search_policy)
    for query in queries:
        print(f"[evidence-search] query='{query}'")

    search_requests = build_search_requests(assertion, domain_resolution, req.search_policy)
    for search_request in search_requests:
        print(
            "[evidence-search] search_request "
            f"provider='{SEARCH_PROVIDER}' "
            f"query='{search_request['query']}' "
            f"include_domains={search_request.get('include_domains')} "
            f"mode={search_request.get('mode')}"
        )

    raw_results: List[Dict[str, Any]] = []
    provider_name = SEARCH_PROVIDER
    if API_KEY_PROVIDER:
        for search_request in search_requests:
            query = search_request["query"]
            include_domains = search_request.get("include_domains")
            try:
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
        for idx, domain_cfg in enumerate(domain_resolution.get("preferred_domains") or [], start=1):
            raw_results.append({
                "url": f"https://{domain_cfg['domain']}/",
                "title": domain_cfg.get("reason") or domain_cfg["domain"],
                "content": "Domain selected by contextual routing; configure API_KEY_PROVIDER for live snippets.",
                "score": domain_cfg.get("weight", 0.0),
            })

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

    if cache_collection is not None:
        assertion_hash = hashlib.sha256(canonical_json(normalized_assertion_for_cache(assertion)).encode("utf-8")).hexdigest()
        await cache_collection.update_one(
            {"cache_key": cache_key},
            {
                "$set": {
                    "cache_key": cache_key,
                    "assertion_hash": assertion_hash,
                    "profile_version": profile_version,
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

    return response
