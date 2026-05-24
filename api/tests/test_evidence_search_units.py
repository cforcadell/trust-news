import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "evidence-search" / "main.py"
spec = importlib.util.spec_from_file_location("evidence_search_main", MODULE_PATH)
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


def test_normalize_assertion_and_hash_are_stable():
    normalized = evidence.normalize_assertion_text("  La   Tierra es redonda.  ")
    assert normalized == "la tierra es redonda."
    assert evidence.assertion_hash(normalized) == evidence.assertion_hash("la tierra es redonda.")


def test_excerpt_prefers_raw_content_and_is_limited():
    raw = " palabra " * 300
    excerpt = evidence.useful_excerpt({"raw_content": raw, "content": "fallback"})
    assert len(excerpt) <= 900
    assert "palabra" in excerpt


def test_source_classification_and_reliability():
    assert evidence.source_type_for_domain("www.who.int") == "official"
    assert evidence.source_type_for_domain("reuters.com") == "news_agency"
    assert evidence.reliability_for_source("official", 0.1) == "high"
    assert evidence.reliability_for_source("media", 0.7) == "medium"


def test_normalize_tavily_sources_shape():
    sources = evidence.normalize_tavily_sources([
        {"url": "https://example.com/a", "title": "A", "content": "Evidence text", "score": 0.9}
    ], "query", 5)
    assert sources[0]["source_id"] == "src-1"
    assert sources[0]["domain"] == "example.com"
    assert sources[0]["query"] == "query"
    assert sources[0]["content_hash"]
