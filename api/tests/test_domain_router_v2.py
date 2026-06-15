import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "evidence-search" / "app" / "domain_router"
sys.path.insert(0, str(ROOT))
resolver_spec = importlib.util.spec_from_file_location("domain_router_resolver", ROOT / "resolver.py")
resolver = importlib.util.module_from_spec(resolver_spec)
resolver_spec.loader.exec_module(resolver)
loader_spec = importlib.util.spec_from_file_location("domain_router_loader", ROOT / "profiles_loader.py")
loader = importlib.util.module_from_spec(loader_spec)
loader_spec.loader.exec_module(loader)


def enriched_assertion():
    return {
        "assertion_id": 1,
        "assertion_index": 0,
        "text": "El paro en Barcelona bajó en 2024.",
        "categoryId": 1,
        "subcategory": "EMPLOYMENT",
        "context": {
            "locations": [{"name": "Barcelona", "country_code": "ES", "region_code": "ES-CAT", "city": "Barcelona"}],
            "entities": [{"name": "INE"}],
            "temporal_context": [{"value": "2024"}],
            "language": "es",
            "jurisdiction": "local",
        },
        "search_hints": {"preferred_source_types": ["statistics", "official"], "search_keywords": [], "suggested_queries": []},
        "context_confidence": {"location": 1.0, "entities": 1.0, "temporal": 1.0},
    }


def test_domain_router_prioritizes_entity_city_and_subcategory():
    profiles = loader.minimal_default_profiles()
    profiles["countries"] = {"ES": {"preferred_domains": [{"domain": "boe.es", "source_type": "official", "weight": 0.95, "reason": "country"}]}}
    profiles["regions"] = {"ES-CAT": {"preferred_domains": [{"domain": "gencat.cat", "source_type": "official", "weight": 0.95, "reason": "region"}]}}
    profiles["cities"] = {"ES-CAT-Barcelona": {"preferred_domains": [{"domain": "barcelona.cat", "source_type": "official", "weight": 1.0, "reason": "city"}]}}
    profiles["entities"] = {"INE": {"preferred_domains": [{"domain": "ine.es", "source_type": "statistics", "weight": 1.0, "reason": "entity"}]}}

    result = resolver.resolve_domains(enriched_assertion(), profiles, max_domains=8)
    domains = [item["domain"] for item in result["preferred_domains"]]
    assert domains[0] == "ine.es"
    assert "barcelona.cat" in domains
    assert "sepe.es" in domains
    assert "category_1" in result["selected_profiles"]
    assert "subcategory_1_EMPLOYMENT" in result["selected_profiles"]
    assert "entity_INE" in result["selected_profiles"]


def test_domain_router_uses_category_fallback_when_context_empty():
    profiles = loader.minimal_default_profiles()
    assertion = enriched_assertion()
    assertion["context"] = {"locations": [], "entities": [], "temporal_context": [], "language": "es", "jurisdiction": "unknown"}
    result = resolver.resolve_domains(assertion, profiles, max_domains=3)
    domains = [item["domain"] for item in result["preferred_domains"]]
    assert "ine.es" in domains
    assert result["fallback_used"] is False
