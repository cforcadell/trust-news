import hashlib
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from common.models.evidence_models import EvidenceSearchRequest
from common.utils.domain_utils import normalize_domain, normalize_domains
from common.utils.mongo import build_mongo_uri_from_env

load_dotenv()

MONGO_URI = build_mongo_uri_from_env()
MONGO_DBNAME = os.getenv("MONGO_DBNAME", "newsdb")
MONGO_COLLECTION = os.getenv("MONGO_EVIDENCES_COLLECTION", "assertion_evidences")
MONGO_CONFIG_COLLECTION = os.getenv("MONGO_EVIDENCE_CONFIG_COLLECTION", "evidence_search_configs")

TAVILY_API_URL = os.getenv("TAVILY_API_URL", "https://api.tavily.com/search")
TAVILY_SEARCH_DEPTH = os.getenv("TAVILY_SEARCH_DEPTH", "advanced")
TAVILY_INCLUDE_ANSWER = os.getenv("TAVILY_INCLUDE_ANSWER", "false").lower() == "true"
TAVILY_INCLUDE_RAW_CONTENT = os.getenv("TAVILY_INCLUDE_RAW_CONTENT", "true").lower() == "true"
TAVILY_MAX_RESULTS = int(os.getenv("TAVILY_MAX_RESULTS", "5"))
TAVILY_TIMEOUT = float(os.getenv("TAVILY_TIMEOUT", "30"))
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
TAVILY_OFFICIAL_FIRST = os.getenv("TAVILY_OFFICIAL_FIRST", "true").lower() == "true"
TAVILY_OFFICIAL_DOMAINS = [
    domain.strip()
    for domain in os.getenv(
        "TAVILY_OFFICIAL_DOMAINS",
        "idescat.cat,gencat.cat,ine.es,ec.europa.eu,eurostat.ec.europa.eu,europa.eu,who.int,un.org,oecd.org,worldbank.org",
    ).split(",")
    if domain.strip()
]

app = FastAPI(title="TrustNews Evidence Search")
mongo_client: Optional[AsyncIOMotorClient] = None
db = None
collection = None
config_collection = None


def category_key(category: Optional[str | int]) -> Optional[str]:
    if category is None or category == "":
        return None
    return str(category).strip()


def config_version(config: Dict[str, Any]) -> str:
    raw = config.get("updated_at") or config.get("config_id") or "env-default"
    if isinstance(raw, datetime):
        return iso(raw)
    return str(raw)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def normalize_assertion_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def assertion_hash(normalized_text: str) -> str:
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def build_search_query(req: EvidenceSearchRequest, query_terms: Optional[List[str]] = None) -> str:
    parts = [req.assertion_text.strip(), "fuentes oficiales datos oficiales estadística oficial"]
    parts.extend(query_terms or [])
    if req.temporal_context:
        parts.append(str(req.temporal_context))
    if req.location_context:
        parts.append(str(req.location_context))
    if req.language:
        parts.append(f"language:{req.language}")
    return " ".join(p for p in parts if p)


def source_type_for_domain(domain: str, official_domains: Optional[List[str]] = None) -> str:
    d = normalize_domain(domain)
    official_markers = (".gov", ".gob", ".int", "who.int", "un.org", "europa.eu", "ec.europa.eu", "eurostat.ec.europa.eu", "gencat.cat", "idescat.cat", "ine.es")
    preferred = normalize_domains(official_domains)
    if any(d == official or d.endswith(f".{official}") for official in preferred):
        return "official"
    agencies = ("reuters.com", "apnews.com", "afp.com", "efe.com", "bloomberg.com")
    if any(marker in d for marker in official_markers):
        return "official"
    if any(marker in d for marker in agencies):
        return "news_agency"
    if d:
        return "media"
    return "unknown"


def reliability_for_source(source_type: str, score: float) -> str:
    if source_type in {"official", "news_agency"}:
        return "high"
    if score >= 0.65:
        return "medium"
    if score > 0:
        return "low"
    return "unknown"


def useful_excerpt(result: Dict[str, Any]) -> str:
    raw = result.get("raw_content") or ""
    content = result.get("content") or ""
    text = re.sub(r"\s+", " ", raw or content).strip()
    return text[:900]


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def normalize_tavily_sources(results: List[Dict[str, Any]], query: str, max_sources: int, official_domains: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    now = iso(utc_now())
    sources = []
    for idx, result in enumerate(results[:max_sources], start=1):
        url = result.get("url") or ""
        domain = normalize_domain(urlparse(url).netloc)
        score = float(result.get("score") or 0.0)
        excerpt = useful_excerpt(result)
        stype = source_type_for_domain(domain, official_domains)
        sources.append({
            "source_id": f"src-{idx}",
            "url": url,
            "domain": domain,
            "title": result.get("title") or url,
            "published_at": result.get("published_date"),
            "retrieved_at": now,
            "source_type": stype,
            "reliability": reliability_for_source(stype, score),
            "query": query,
            "excerpt": excerpt,
            "content_hash": content_hash(excerpt or url),
            "ranking_score": score,
        })
    return sources


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


async def get_evidence_search_config(category: Optional[str | int]) -> Dict[str, Any]:
    fallback = {
        "config_id": "env-default",
        "category_id": None,
        "category_name": "Default",
        "enabled": True,
        "official_first": TAVILY_OFFICIAL_FIRST,
        "preferred_domains": TAVILY_OFFICIAL_DOMAINS,
        "official_domains": TAVILY_OFFICIAL_DOMAINS,
        "query_terms": [],
    }
    if config_collection is None:
        return fallback

    default_doc = await config_collection.find_one({"config_id": "default", "enabled": {"$ne": False}}, {"_id": 0}) or {}
    category_doc = {}
    key = category_key(category)
    if key:
        category_doc = await config_collection.find_one({"config_id": key, "enabled": {"$ne": False}}, {"_id": 0}) or {}

    preferred_domains = normalize_domains(
        default_doc.get("preferred_domains", [])
        + default_doc.get("official_domains", [])
        + category_doc.get("preferred_domains", [])
        + category_doc.get("official_domains", [])
        + TAVILY_OFFICIAL_DOMAINS
    )
    query_terms = list(dict.fromkeys((default_doc.get("query_terms") or []) + (category_doc.get("query_terms") or [])))
    return {
        **fallback,
        **default_doc,
        **category_doc,
        "config_id": category_doc.get("config_id") or default_doc.get("config_id") or fallback["config_id"],
        "preferred_domains": preferred_domains,
        "official_domains": preferred_domains,
        "query_terms": query_terms,
        "official_first": category_doc.get("official_first", default_doc.get("official_first", fallback["official_first"])),
    }


async def search_tavily_official_first(query: str, max_sources: int, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    limit = min(max_sources, TAVILY_MAX_RESULTS)
    preferred_domains = normalize_domains(config.get("preferred_domains") or config.get("official_domains") or [])
    official_first = bool(config.get("official_first", TAVILY_OFFICIAL_FIRST))
    if not official_first or not preferred_domains:
        tavily = await call_tavily(query, limit)
        return tavily.get("results", []) or []

    official_tavily = await call_tavily(query, limit, include_domains=preferred_domains)
    official_results = official_tavily.get("results", []) or []
    if len(official_results) >= limit:
        return official_results[:limit]

    general_tavily = await call_tavily(query, limit)
    general_results = general_tavily.get("results", []) or []
    return merge_tavily_results(official_results, general_results, max_sources=limit)


def response_from_doc(doc: Dict[str, Any], cached: bool) -> Dict[str, Any]:
    return {
        "assertion_text": doc.get("assertion_text"),
        "assertion_hash": doc.get("assertion_hash"),
        "cached": cached,
        "inserted_at": doc.get("inserted_at"),
        "last_query": doc.get("last_query"),
        "sources": doc.get("sources", []),
    }


async def ensure_indexes():
    await collection.create_index("assertion_hash", unique=True)
    await collection.create_index([("last_query", -1)])
    await collection.create_index([("inserted_at", -1)])
    await collection.create_index("search_provider")
    if config_collection is not None:
        await config_collection.create_index("config_id", unique=True)
        await config_collection.create_index("category_id")


@app.on_event("startup")
async def startup_event():
    global mongo_client, db, collection, config_collection
    mongo_client = AsyncIOMotorClient(MONGO_URI)
    db = mongo_client[MONGO_DBNAME]
    collection = db[MONGO_COLLECTION]
    config_collection = db[MONGO_CONFIG_COLLECTION]
    await ensure_indexes()


@app.on_event("shutdown")
async def shutdown_event():
    if mongo_client:
        mongo_client.close()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "evidence-search"}


@app.post("/search/evidences")
async def search_evidences(req: EvidenceSearchRequest):
    normalized = normalize_assertion_text(req.assertion_text)
    if not normalized:
        raise HTTPException(status_code=400, detail="assertion_text is required")
    ahash = assertion_hash(normalized)
    now_dt = utc_now()
    now = iso(now_dt)

    search_config = await get_evidence_search_config(req.category)
    evidence_config_version = config_version(search_config)

    existing = await collection.find_one({"assertion_hash": ahash}, {"_id": 0})
    if existing and not req.force_refresh and existing.get("evidence_config_version") == evidence_config_version:
        update = {"$set": {"last_query": now}}
        if req.order_id:
            update.setdefault("$addToSet", {})["order_ids"] = str(req.order_id)
        if req.assertion_id is not None:
            update.setdefault("$addToSet", {})["assertion_ids"] = str(req.assertion_id)
        await collection.update_one({"assertion_hash": ahash}, update)
        existing["last_query"] = now
        if req.order_id and str(req.order_id) not in existing.get("order_ids", []):
            existing.setdefault("order_ids", []).append(str(req.order_id))
        if req.assertion_id is not None and str(req.assertion_id) not in existing.get("assertion_ids", []):
            existing.setdefault("assertion_ids", []).append(str(req.assertion_id))
        return response_from_doc(existing, cached=True)

    query = build_search_query(req, search_config.get("query_terms"))
    tavily_results = await search_tavily_official_first(query, req.max_sources, search_config)
    sources = normalize_tavily_sources(tavily_results, query, req.max_sources, search_config.get("official_domains"))
    order_ids = list(dict.fromkeys((existing or {}).get("order_ids", []) + ([str(req.order_id)] if req.order_id else [])))
    assertion_ids = list(dict.fromkeys((existing or {}).get("assertion_ids", []) + ([str(req.assertion_id)] if req.assertion_id is not None else [])))
    doc = {
        "assertion_hash": ahash,
        "assertion_text": req.assertion_text,
        "normalized_assertion_text": normalized,
        "order_ids": order_ids,
        "assertion_ids": assertion_ids,
        "category": req.category,
        "language": req.language,
        "temporal_context": req.temporal_context,
        "location_context": req.location_context,
        "inserted_at": now,
        "last_query": now,
        "search_provider": "tavily",
        "search_query": query,
        "official_first": search_config.get("official_first", TAVILY_OFFICIAL_FIRST),
        "evidence_config_id": search_config.get("config_id"),
        "evidence_config_version": evidence_config_version,
        "official_domains": search_config.get("official_domains", TAVILY_OFFICIAL_DOMAINS),
        "sources": sources,
    }
    await collection.update_one({"assertion_hash": ahash}, {"$set": doc}, upsert=True)
    return response_from_doc(doc, cached=False)
