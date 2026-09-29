"""Versioned, order-sensitive identity of evidence crossing service boundaries."""

import hashlib
import json
import unicodedata
from urllib.parse import urlsplit, urlunsplit

BUNDLE_VERSION = "evidence-bundle-v1"


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
