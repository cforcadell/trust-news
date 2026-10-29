"""Versioned, order-sensitive identity of evidence crossing service boundaries."""

import hashlib
import json
import unicodedata
from urllib.parse import urlsplit, urlunsplit

BUNDLE_VERSION = "evidence-bundle-v1"
PROVENANCE_BUNDLE_VERSION = "evidence-bundle-v2"


def normalized_text(value):
    return unicodedata.normalize("NFC", str(value or "")).replace("\r\n", "\n").replace("\r", "\n").strip()


def text_hash(value):
    return hashlib.sha256(normalized_text(value).encode("utf-8")).hexdigest()


def canonical_url(value):
    parsed = urlsplit(normalized_text(value))
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, ""))


def canonical_bundle(evidences):
    # Never trust an incoming text_sha256: compute it from the actual text.
    return {"version": BUNDLE_VERSION, "sources": [
        {"source_id": normalized_text(source.get("source_id")), "url": canonical_url(source.get("url")),
         "relationship_to_origin": source.get("relationship_to_origin"),
         "contexts": [
             {"context_id": normalized_text(context.get("context_id")),
              "text_sha256": text_hash(context.get("text")),
              "citation_eligible": context.get("citation_eligible") is True}
             for context in source.get("contexts") or []
         ]}
        for source in evidences
    ]}


def evidence_bundle_hash(evidences):
    payload = json.dumps(canonical_bundle(evidences), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonical_provenance_bundle(evidences):
    """Bind delivered text and declared acquisition lineage without altering v1 replay."""
    legacy = canonical_bundle(evidences)
    sources = []
    for source, canonical_source in zip(evidences, legacy["sources"]):
        provenance = source.get("document_provenance") or {}
        sources.append({
            **canonical_source,
            "document_provenance": {
                "method": normalized_text(provenance.get("method")),
                "provider": normalized_text(provenance.get("provider")),
                "requested_url": canonical_url(provenance.get("requested_url")),
                "resolved_url": canonical_url(provenance.get("resolved_url")),
                "received_at": normalized_text(provenance.get("received_at")),
                "source_fetched_at": normalized_text(provenance.get("source_fetched_at")),
                "freshness_status": normalized_text(provenance.get("freshness_status")),
                "document_sha256": normalized_text(provenance.get("text_sha256")),
                "snapshot_id": normalized_text(provenance.get("snapshot_id")),
                "cache_origin_method": normalized_text(provenance.get("cache_origin_method")),
                "provider_request_id": normalized_text(provenance.get("provider_request_id")),
                "provider_call_ids": list(provenance.get("provider_call_ids") or []),
            },
            "contexts": [
                {**canonical_context,
                 "origin": normalized_text(context.get("origin")),
                 "document_sha256": normalized_text(context.get("document_sha256"))}
                for context, canonical_context in zip(source.get("contexts") or [], canonical_source["contexts"])
            ],
        })
    return {"version": PROVENANCE_BUNDLE_VERSION, "sources": sources}


def evidence_bundle_hash_v2(evidences):
    payload = json.dumps(canonical_provenance_bundle(evidences), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
