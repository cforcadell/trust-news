#!/usr/bin/env python3
"""Generate the deterministic 1,000-domain default profile from Wikidata."""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = ROOT / "api/evidence-search/config/evidence-domain-profile-default.json"
NORMALIZATION = ROOT / "api/evidence-search/config/evidence-normalization-configs.json"
USER_AGENT = "TrustNews-domain-profile-builder/1.0"
DOMAIN_RE = re.compile(r"(?:[a-z0-9-]+\.)+[a-z]{2,}")
DENIED_HOSTS = {
    "facebook.com", "instagram.com", "linkedin.com", "tiktok.com", "twitter.com",
    "x.com", "youtube.com", "youtu.be", "blogspot.com", "wordpress.com",
}
REGIONAL_TLDS = {
    "EUROPE": set("ad al at ax ba be bg by ch cy cz de dk ee es fi fo fr gb gg gi gr hr hu ie im is it je li lt lu lv mc md me mk mt nl no pl pt ro rs ru se si sj sk sm ua va eu uk".split()),
    "ASIA": set("ae af am az bd bh bn bt cn ge hk id il in iq ir jo jp kg kh kp kr kw kz la lb lk mm mn mo mv my np om ph pk ps qa sa sg sy th tj tl tm tr tw uz vn ye".split()),
    "AFRICA": set("ao bf bi bj bw cd cf cg ci cm cv dj dz eg er et ga gh gm gn gq gw ke km lr ls ly ma mg ml mr mu mw mz na ne ng rw sc sd sh sl sn so ss st sz td tg tn tz ug za zm zw".split()),
    "NORTH_AMERICA": set("ag ai aw bb bm bs bz ca cr cu cw dm do gd gl gp gt hn ht jm kn ky lc mq ms mx ni pa pm pr sv tc tt us vc vg vi".split()),
    "SOUTH_AMERICA": set("ar bo br cl co ec fk gf gy pe py sr uy ve".split()),
    "OCEANIA": set("as au cc ck cx fj fm gu ki mh mp nc nf nr nu nz pf pg pn pw sb tk to tv vu wf ws".split()),
}
REGION_NAMES = {key: key.replace("_", " ").title() for key in REGIONAL_TLDS}

CONTINENTS = {
    "Q15": ("AFRICA", "Africa"),
    "Q18": ("SOUTH_AMERICA", "South America"),
    "Q46": ("EUROPE", "Europe"),
    "Q48": ("ASIA", "Asia"),
    "Q49": ("NORTH_AMERICA", "North America"),
    "Q51": ("ANTARCTICA", "Antarctica"),
    "Q538": ("OCEANIA", "Oceania"),
}

# Each category uses official websites of entities belonging to these Wikidata classes.
CATEGORY_SOURCES = {
    1: {"roots": ["Q4830453", "Q650241"], "source_types": ["corporate"]},
    2: {"roots": ["Q4438121", "Q476028"], "source_types": ["sports_organization"]},
    3: {"roots": ["Q327333", "Q7278"], "source_types": ["political_organization"]},
    4: {"roots": ["Q18388277"], "source_types": ["corporate", "technology"]},
    5: {"roots": ["Q4287745", "Q16917"], "source_types": ["healthcare"]},
    6: {"roots": ["Q1331793", "Q10689397", "Q215380"], "source_types": ["international_media"]},
    7: {"roots": ["Q31855", "Q3918"], "source_types": ["academic"]},
    8: {"roots": ["Q33506", "Q7075"], "source_types": ["cultural_institution"]},
    9: {"roots": ["Q1785733", "Q121096353", "Q46169"], "source_types": ["environmental_organization"]},
    10: {"roots": ["Q163740", "Q708676"], "source_types": ["nonprofit"]},
}


def query_wikidata(roots: list[str], limit: int = 300) -> list[dict]:
    values = " ".join(f"wd:{root}" for root in roots)
    query = f"""
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
SELECT DISTINCT ?item ?website WHERE {{
  VALUES ?root {{ {values} }}
  ?item wdt:P31/wdt:P279* ?root; wdt:P856 ?website.
}}
LIMIT {limit}
"""
    data = urllib.parse.urlencode({"query": query}).encode()
    request = urllib.request.Request(
        "https://qlever.dev/api/wikidata", data=data,
        headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json",
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)["results"]["bindings"]


def normalized_domain(url: str) -> str | None:
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".")
        host = host.removeprefix("www.").encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return None
    if not DOMAIN_RE.fullmatch(host) or any(host == item or host.endswith(f".{item}") for item in DENIED_HOSTS):
        return None
    return host


def location_for(row: dict) -> list[dict]:
    continent_url = row.get("continent", {}).get("value", "")
    continent_id = continent_url.rsplit("/", 1)[-1]
    if continent_id in CONTINENTS:
        macroregion_id, name = CONTINENTS[continent_id]
        return [{"scope": "macroregion", "macroregion_id": macroregion_id, "name": name}]
    host = normalized_domain(row.get("website", {}).get("value", ""))
    tld = host.rsplit(".", 1)[-1] if host else ""
    for macroregion_id, tlds in REGIONAL_TLDS.items():
        if tld in tlds:
            return [{"scope": "macroregion", "macroregion_id": macroregion_id, "name": REGION_NAMES[macroregion_id]}]
    return [{"scope": "global"}]


def category_metadata() -> tuple[dict[int, str], dict[int, list[str]], dict[str, int]]:
    configs = json.loads(NORMALIZATION.read_text(encoding="utf-8"))
    sub_doc = next(item for item in configs if item["config_type"] == "subcategories")
    subcategories = {category_id: [] for category_id in CATEGORY_SOURCES}
    for item in sub_doc["items"]:
        if item.get("enabled", True):
            for category_id in item.get("category_ids", []):
                subcategories.setdefault(category_id, []).append(item["id"])
    names = {1: "ECONOMÍA", 2: "DEPORTES", 3: "POLÍTICA", 4: "TECNOLOGÍA", 5: "SALUD",
             6: "ENTRETENIMIENTO", 7: "CIENCIA", 8: "CULTURA", 9: "MEDIO AMBIENTE", 10: "SOCIAL"}
    versions = {item["config_type"]: item["version"] for item in configs}
    return names, subcategories, versions


def build_domains() -> tuple[list[dict], dict[int, int]]:
    names, subcategories, _ = category_metadata()
    domains, used, counts = [], set(), {}
    for category_id, source in CATEGORY_SOURCES.items():
        print(f"[domain-profile] querying category_id={category_id}", flush=True)
        candidates = query_wikidata(source["roots"])
        print(f"[domain-profile] candidates category_id={category_id} rows={len(candidates)}", flush=True)
        candidates.sort(key=lambda row: (row.get("continent", {}).get("value", ""), row["website"]["value"]))
        selected = 0
        for row in candidates:
            domain = normalized_domain(row["website"]["value"])
            if not domain or domain in used:
                continue
            subs = subcategories[category_id]
            start = selected % len(subs)
            assigned = [subs[(start + offset) % len(subs)] for offset in range(min(3, len(subs)))]
            domains.append({
                "domain": domain,
                "score": 0.72,
                "categories": [{"category_id": category_id, "category_name": names[category_id], "subcategories": assigned}],
                "locations": location_for(row),
                "source_types": source["source_types"],
                "entities": [],
                "languages": [],
                "enabled": True,
            })
            used.add(domain)
            selected += 1
            if selected == 100:
                break
        if selected < 100:
            raise RuntimeError(f"Wikidata returned only {selected} unique domains for category_id={category_id}")
        counts[category_id] = selected
        time.sleep(0.25)
    return domains, counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    _, _, versions = category_metadata()
    domains, counts = build_domains()
    profile = {
        "profile_id": "default", "profile_name": "Global and macroregional diversified profile",
        "enabled": True, "version": 3,
        "description": "Balanced profile of 1,000 official entity domains sourced from Wikidata: 100 per category.",
        "normalization_versions": versions,
        "selection_policy": {"max_domains": 8, "min_score": 0.35, "fallback_to_general_search": True,
                             "max_queries_per_domain": 2, "max_results": 5,
                             "official_source_required_for_claim_types": ["legal", "official_statistic", "public_health", "election_result"]},
        "scoring_weights": {"base_domain_score": 0.45, "category_match": 0.15, "subcategory_match": 0.12,
                            "location_match": 0.12, "source_type_match": 0.10, "entity_match": 0.08,
                            "official_bonus": 0.08, "statistics_bonus": 0.06, "global_location_bonus": 0.02},
        "domains": domains,
        "provenance": {"source": "Wikidata SPARQL", "endpoint": "QLever Wikidata mirror", "generated_by": "scripts/k8s/apis/generate-evidence-domain-profile.py",
                       "domains_per_category": counts},
    }
    args.output.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[domain-profile] output={args.output} domains={len(domains)} counts={counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
