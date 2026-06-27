#!/usr/bin/env python3
"""Generate the strict official evidence-domain profile from a curated seed."""
from __future__ import annotations

import argparse
import json
import re
import urllib.parse
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SEED = ROOT / "api/evidence-search/config/official-domain-seed.json"
DEFAULT_NORMALIZATION = ROOT / "api/evidence-search/config/evidence-normalization-configs.json"
DEFAULT_OUTPUT = ROOT / "api/evidence-search/config/evidence-domain-profile-official.json"

CATEGORY_CATALOG = {
    1: "ECONOMÍA",
    2: "DEPORTES",
    3: "POLÍTICA",
    4: "TECNOLOGÍA",
    5: "SALUD",
    6: "ENTRETENIMIENTO",
    7: "CIENCIA",
    8: "CULTURA",
    9: "MEDIO AMBIENTE",
    10: "SOCIAL",
}

DOMAIN_RE = re.compile(r"(?:[a-z0-9-]+\.)+[a-z]{2,}")
DENIED_HOSTS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "youtu.be",
    "blogspot.com",
    "wordpress.com",
    "medium.com",
    "substack.com",
    "wikipedia.org",
    "wikidata.org",
}

NATIONAL_SOURCE_TYPES = {"national_official", "national_government", "government"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_domain(value: str) -> str | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    try:
        host = (urllib.parse.urlsplit(candidate).hostname or "").lower().rstrip(".")
        host = host.removeprefix("www.").encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return None
    if not DOMAIN_RE.fullmatch(host):
        return None
    if any(host == denied or host.endswith(f".{denied}") for denied in DENIED_HOSTS):
        return None
    return host


def normalization_metadata(configs: list[dict]) -> tuple[dict[str, int], dict[int, list[str]], set[str]]:
    versions = {item["config_type"]: item["version"] for item in configs}
    sub_doc = next(item for item in configs if item["config_type"] == "subcategories")
    subcategories: dict[int, list[str]] = {category_id: [] for category_id in CATEGORY_CATALOG}
    for item in sub_doc["items"]:
        if not item.get("enabled", True):
            continue
        for category_id in item.get("category_ids") or []:
            if category_id in subcategories:
                subcategories[category_id].append(item["id"])
    source_doc = next(item for item in configs if item["config_type"] == "source_types")
    source_types = {item["id"] for item in source_doc["items"] if item.get("enabled", True)}
    return versions, subcategories, source_types


def score_for(entry: dict) -> float:
    if "score" in entry:
        score = float(entry["score"])
    elif any(location.get("scope") == "global" for location in entry.get("locations") or []):
        score = 0.96
    elif "statistics" in entry.get("source_types", []):
        score = 0.94
    else:
        score = 0.92
    if score < 0.85:
        raise ValueError(f"Accepted official seed entries cannot score below 0.85: domain={entry.get('domain')}")
    return round(score, 2)


def validate_seed_entry(
    entry: dict,
    *,
    source_types: set[str],
    subcategories_by_category: dict[int, list[str]],
    allow_national_officials: bool,
) -> tuple[str, dict]:
    if entry.get("official") is not True:
        raise ValueError(f"Seed entry must set official=true: domain={entry.get('domain')}")
    category_id = entry.get("category_id")
    if category_id not in CATEGORY_CATALOG:
        raise ValueError(f"Invalid category_id={category_id} for domain={entry.get('domain')}")
    if not allow_national_officials and set(entry.get("source_types") or []) & NATIONAL_SOURCE_TYPES:
        raise ValueError(f"National official seed entries require --allow-national-officials: domain={entry.get('domain')}")

    domain = normalize_domain(entry.get("domain") or entry.get("url"))
    if not domain:
        raise ValueError(f"Invalid or forbidden domain in seed entry: {entry.get('domain') or entry.get('url')}")

    unknown_sources = set(entry.get("source_types") or []) - source_types
    if unknown_sources:
        raise ValueError(f"Unknown source_types={sorted(unknown_sources)} for domain={domain}")
    if not entry.get("source_types"):
        raise ValueError(f"Seed entry requires source_types: domain={domain}")

    allowed_subcategories = subcategories_by_category[category_id]
    requested_subcategories = entry.get("subcategories") or []
    if requested_subcategories:
        unknown = set(requested_subcategories) - set(allowed_subcategories)
        if unknown:
            raise ValueError(
                f"Subcategories={sorted(unknown)} do not belong to category_id={category_id} for domain={domain}"
            )
        subcategories = requested_subcategories[:3]
    else:
        subcategories = allowed_subcategories[:3]
    if not subcategories:
        raise ValueError(f"No enabled subcategories available for category_id={category_id}")

    output = {
        "domain": domain,
        "url": entry.get("url") or f"https://{domain}/",
        "score": score_for(entry),
        "categories": [
            {
                "category_id": category_id,
                "category_name": CATEGORY_CATALOG[category_id],
                "subcategories": subcategories,
            }
        ],
        "locations": entry.get("locations") or [{"scope": "global"}],
        "source_types": entry["source_types"],
        "entities": entry.get("entities") or [],
        "languages": entry.get("languages") or [],
        "enabled": entry.get("enabled", True),
    }
    return domain, output


def build_profile(
    seed: list[dict],
    configs: list[dict],
    domains_per_category: int,
    allow_national_officials: bool,
    profile_id: str,
) -> dict:
    versions, subcategories_by_category, source_types = normalization_metadata(configs)
    domains: list[dict] = []
    seen: set[str] = set()
    counts: Counter[int] = Counter()
    rejected_disabled = 0

    for entry in seed:
        domain, output = validate_seed_entry(
            entry,
            source_types=source_types,
            subcategories_by_category=subcategories_by_category,
            allow_national_officials=allow_national_officials,
        )
        if domain in seen:
            raise ValueError(f"Duplicated domain in official seed: {domain}")
        seen.add(domain)
        if not output["enabled"]:
            rejected_disabled += 1
            continue
        category_id = output["categories"][0]["category_id"]
        if counts[category_id] >= domains_per_category:
            continue
        domains.append(output)
        counts[category_id] += 1

    incomplete = {
        category_id: counts[category_id]
        for category_id in CATEGORY_CATALOG
        if counts[category_id] < domains_per_category
    }
    if incomplete:
        missing = {category_id: domains_per_category - count for category_id, count in incomplete.items()}
        raise ValueError(
            "Official seed does not contain enough accepted domains per category: "
            f"counts={dict(sorted(counts.items()))} missing={missing}"
        )

    domains.sort(key=lambda item: (item["categories"][0]["category_id"], item["domain"]))
    return {
        "profile_id": profile_id,
        "profile_name": "Official evidence source profile",
        "enabled": True,
        "version": 1,
        "description": (
            "Strict evidence profile generated only from a curated allowlist of official, "
            "institutional, regulator, statistical, scientific, cultural, health, sports, "
            "environmental and social-protection sources."
        ),
        "normalization_versions": versions,
        "selection_policy": {
            "max_domains": 8,
            "min_score": 0.35,
            "fallback_to_general_search": False,
            "max_queries_per_domain": 2,
            "max_results": 5,
            "official_source_required_for_claim_types": [
                "legal",
                "official_statistic",
                "public_health",
                "election_result",
            ],
        },
        "scoring_weights": {
            "base_domain_score": 0.45,
            "category_match": 0.15,
            "subcategory_match": 0.12,
            "location_match": 0.12,
            "source_type_match": 0.10,
            "entity_match": 0.08,
            "official_bonus": 0.08,
            "statistics_bonus": 0.06,
            "global_location_bonus": 0.02,
        },
        "domains": domains,
        "provenance": {
            "source": "curated official-domain seed",
            "seed": str(DEFAULT_SEED.relative_to(ROOT)),
            "generated_by": "scripts/k8s/apis/generate-official-evidence-domain-profile.py",
            "domains_per_category": dict(sorted(counts.items())),
            "disabled_seed_entries": rejected_disabled,
            "allow_national_officials": allow_national_officials,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--normalization", type=Path, default=DEFAULT_NORMALIZATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--domains-per-category", type=int, default=50)
    parser.add_argument("--allow-national-officials", action="store_true")
    parser.add_argument("--profile-id", default="official-default")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.domains_per_category < 1:
        raise ValueError("--domains-per-category must be >= 1")
    seed = load_json(args.seed)
    configs = load_json(args.normalization)
    profile = build_profile(seed, configs, args.domains_per_category, args.allow_national_officials, args.profile_id)
    args.output.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"[official-domain-profile] output={args.output} domains={len(profile['domains'])} "
        f"counts={profile['provenance']['domains_per_category']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
