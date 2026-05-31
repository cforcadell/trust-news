import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from common.models.evidence_models import EvidenceSearchRequestV2
from common.utils.domain_utils import normalize_domain
from common.utils.mongo import build_mongo_uri_from_env

sys.path.append(os.path.dirname(__file__))
from app.domain_router.profiles_loader import PROFILE_INDEX_DOC_TYPE, PROFILE_SUBSET_DOC_TYPE, load_profiles_from_mongo
from app.domain_router.resolver import resolve_domains

load_dotenv()

MONGO_URI = build_mongo_uri_from_env()
MONGO_DBNAME = os.getenv("MONGO_DBNAME", "newsdb")
MONGO_DOMAIN_PROFILE_COLLECTION = os.getenv("EVIDENCE_DOMAIN_CONFIG_COLLECTION", os.getenv("MONGO_EVIDENCE_DOMAIN_PROFILES_COLLECTION", "evidence_domain_profiles"))
MONGO_CACHE_COLLECTION = os.getenv("EVIDENCE_SEARCH_CACHE_COLLECTION", "evidence_search_cache")
EVIDENCE_SEARCH_CACHE_TTL_SECONDS = int(os.getenv("EVIDENCE_SEARCH_CACHE_TTL_SECONDS", "86400"))

TAVILY_API_URL = os.getenv("TAVILY_API_URL", "https://api.tavily.com/search")
TAVILY_SEARCH_DEPTH = os.getenv("TAVILY_SEARCH_DEPTH", "advanced")
TAVILY_INCLUDE_ANSWER = os.getenv("TAVILY_INCLUDE_ANSWER", "false").lower() == "true"
TAVILY_INCLUDE_RAW_CONTENT = os.getenv("TAVILY_INCLUDE_RAW_CONTENT", "true").lower() == "true"
TAVILY_MAX_RESULTS = int(os.getenv("TAVILY_MAX_RESULTS", "5"))
TAVILY_TIMEOUT = float(os.getenv("TAVILY_TIMEOUT", "30"))
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")


app = FastAPI(title="TrustNews Evidence Search")
mongo_client: Optional[AsyncIOMotorClient] = None
db = None
domain_profile_collection = None
cache_collection = None



def build_queries_v2(assertion: Dict[str, Any], domain_resolution: Dict[str, Any], policy) -> List[str]:
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

    queries: List[str] = []
    for domain_cfg in domain_resolution.get("preferred_domains") or []:
        domain = domain_cfg.get("domain")
        for query in base_queries[: policy.max_queries_per_domain]:
            queries.append(f"site:{domain} {query}".strip())
    if policy.fallback_to_general_search:
        queries.extend(q for q in base_queries if q not in queries)
    return queries


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


async def load_profile_bundle() -> tuple[Dict[str, Any], str]:
    try:
        return await load_profiles_from_mongo(domain_profile_collection)
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



async def call_tavily(query: str, max_sources: int, include_domains: Optional[List[str]] = None) -> Dict[str, Any]:
    if not TAVILY_API_KEY:
        raise HTTPException(status_code=500, detail="TAVILY_API_KEY is not configured")
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": TAVILY_SEARCH_DEPTH,
        "include_answer": TAVILY_INCLUDE_ANSWER,
        "include_raw_content": TAVILY_INCLUDE_RAW_CONTENT,
        "max_results": min(max_sources, TAVILY_MAX_RESULTS),
    }
    if include_domains:
        # Tavily supports include_domains to restrict a search pass to selected domains.
        payload["include_domains"] = include_domains
    async with httpx.AsyncClient(timeout=TAVILY_TIMEOUT) as client:
        resp = await client.post(TAVILY_API_URL, json=payload)
        resp.raise_for_status()
        return resp.json()


def merge_tavily_results(*result_groups: List[Dict[str, Any]], max_sources: int) -> List[Dict[str, Any]]:
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
        await domain_profile_collection.create_index([("doc_type", 1), ("profile_id", 1)], name="idx_profile_docs")
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



@app.post("/search/evidence")
async def search_evidence(req: EvidenceSearchRequestV2):
    assertion = req.assertion
    text = str(assertion.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="assertion.text is required")

    use_preferred_domains = bool(req.search_policy.use_preferred_domains)
    if use_preferred_domains:
        profiles, profile_version = await load_profile_bundle()
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
    logger_prefix = f"[domain-router] assertion_id={assertion.get('assertion_id')}"
    print(f"{logger_prefix} use_preferred_domains={use_preferred_domains} selected_profiles={domain_resolution.get('selected_profiles')}")

    queries = build_queries_v2(assertion, domain_resolution, req.search_policy)
    for query in queries:
        print(f"[evidence-search] query='{query}'")

    raw_results: List[Dict[str, Any]] = []
    if TAVILY_API_KEY:
        for query in queries:
            include_domains = []
            if query.startswith("site:"):
                include_domains = [query.split()[0].replace("site:", "")]
            try:
                tavily = await call_tavily(query, req.search_policy.max_results, include_domains=include_domains or None)
                raw_results = merge_tavily_results(raw_results, tavily.get("results", []) or [], max_sources=req.search_policy.max_results)
                if len(raw_results) >= req.search_policy.max_results:
                    break
            except Exception as e:
                print(f"[evidence-search] search provider failed query='{query}': {e}")
    else:
        for idx, domain_cfg in enumerate(domain_resolution.get("preferred_domains") or [], start=1):
            raw_results.append({
                "url": f"https://{domain_cfg['domain']}/",
                "title": domain_cfg.get("reason") or domain_cfg["domain"],
                "content": "Domain selected by contextual routing; configure TAVILY_API_KEY for live snippets.",
                "score": domain_cfg.get("weight", 0.0),
            })

    evidences = [evidence_from_source_v2(source, idx, domain_resolution) for idx, source in enumerate(raw_results[: req.search_policy.max_results], start=1)]
    response = {
        "schema_version": "evidence-search-response-v2",
        "assertion_id": assertion.get("assertion_id"),
        "domain_resolution": domain_resolution,
        "queries_executed": queries,
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
