#!/usr/bin/env python3
"""Initialize evidence-search preferred official domains by assertion category.

Usage:
  ADMIN_URL=http://localhost:8400 scripts/k8s/apis/init-evidence-search-domains.py
  scripts/k8s/apis/init-evidence-search-domains.py --admin-url http://localhost:8400 --dry-run

The script is idempotent: it uses PUT /evidence-search/configs/{config_id}.
Official domains were selected from Spanish, Catalan, EU and international
public institutions relevant to each category.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


DEFAULT_ADMIN_URL = os.getenv("ADMIN_URL", "http://localhost:8400")
DEFAULT_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "15"))

CONFIGS: list[dict[str, Any]] = [
    {
        "config_id": "1",
        "category_id": 1,
        "category_name": "ECONOMIA",
        "preferred_domains": [
            "ine.es",
            "idescat.cat",
            "bde.es",
            "hacienda.gob.es",
            "economia.gob.es",
            "tesoro.es",
            "eurostat.ec.europa.eu",
            "datos.gob.es",
        ],
        "query_terms": ["estadistica oficial", "datos oficiales", "serie estadistica"],
    },
    {
        "config_id": "2",
        "category_id": 2,
        "category_name": "DEPORTES",
        "preferred_domains": [
            "csd.gob.es",
            "rfef.es",
            "rfeb.es",
            "rfeba.com",
            "paralimpicos.es",
            "olympics.com",
            "uefa.com",
            "fifa.com",
            "esport.gencat.cat",
        ],
        "query_terms": ["organismo oficial", "federacion oficial", "resultado oficial"],
    },
    {
        "config_id": "3",
        "category_id": 3,
        "category_name": "POLITICA",
        "preferred_domains": [
            "lamoncloa.gob.es",
            "congreso.es",
            "senado.es",
            "boe.es",
            "interior.gob.es",
            "juntaelectoralcentral.es",
            "parlament.cat",
            "govern.cat",
            "gencat.cat",
        ],
        "query_terms": ["fuente oficial", "boletin oficial", "nota de prensa oficial"],
    },
    {
        "config_id": "4",
        "category_id": 4,
        "category_name": "TECNOLOGIA",
        "preferred_domains": [
            "digital.gob.es",
            "red.es",
            "datos.gob.es",
            "incibe.es",
            "aepd.es",
            "ciencia.gob.es",
            "ec.europa.eu",
            "accio.gencat.cat",
        ],
        "query_terms": ["administracion digital", "ciberseguridad", "datos oficiales"],
    },
    {
        "config_id": "5",
        "category_id": 5,
        "category_name": "SALUD",
        "preferred_domains": [
            "sanidad.gob.es",
            "isciii.es",
            "aemps.gob.es",
            "salut.gencat.cat",
            "who.int",
            "ecdc.europa.eu",
            "ine.es",
            "idescat.cat",
        ],
        "query_terms": ["salud publica", "informe oficial", "vigilancia epidemiologica"],
    },
    {
        "config_id": "6",
        "category_id": 6,
        "category_name": "ENTRETENIMIENTO",
        "preferred_domains": [
            "cultura.gob.es",
            "icaa.cultura.gob.es",
            "rtve.es",
            "ine.es",
            "idescat.cat",
            "cultura.gencat.cat",
            "boe.es",
        ],
        "query_terms": ["industria cultural", "cine", "audiovisual", "datos oficiales"],
    },
    {
        "config_id": "7",
        "category_id": 7,
        "category_name": "CIENCIA",
        "preferred_domains": [
            "ciencia.gob.es",
            "csic.es",
            "aei.gob.es",
            "fecyt.es",
            "isciii.es",
            "esa.int",
            "cordis.europa.eu",
            "recercaiuniversitats.gencat.cat",
        ],
        "query_terms": ["investigacion", "publicacion oficial", "I+D+i"],
    },
    {
        "config_id": "8",
        "category_id": 8,
        "category_name": "CULTURA",
        "preferred_domains": [
            "cultura.gob.es",
            "cultura.gencat.cat",
            "patrimoni.gencat.cat",
            "bne.es",
            "cervantes.es",
            "europeana.eu",
            "unesco.org",
            "boe.es",
        ],
        "query_terms": ["patrimonio cultural", "ministerio de cultura", "datos oficiales"],
    },
    {
        "config_id": "9",
        "category_id": 9,
        "category_name": "MEDIO AMBIENTE",
        "preferred_domains": [
            "miteco.gob.es",
            "aemet.es",
            "eea.europa.eu",
            "climate.copernicus.eu",
            "aca.gencat.cat",
            "gencat.cat",
            "ec.europa.eu",
            "datos.gob.es",
        ],
        "query_terms": ["medio ambiente", "clima", "datos oficiales", "informe oficial"],
    },
    {
        "config_id": "10",
        "category_id": 10,
        "category_name": "SOCIAL",
        "preferred_domains": [
            "dsca.gob.es",
            "inclusion.gob.es",
            "seg-social.es",
            "mites.gob.es",
            "sepe.es",
            "imserso.es",
            "ine.es",
            "idescat.cat",
            "treball.gencat.cat",
        ],
        "query_terms": ["derechos sociales", "inclusion", "proteccion social", "datos oficiales"],
    },
]


def build_payload(config: dict[str, Any]) -> dict[str, Any]:
    domains = config["preferred_domains"]
    return {
        "category_id": config["category_id"],
        "category_name": config["category_name"],
        "preferred_domains": domains,
        "official_domains": domains,
        "query_terms": config["query_terms"],
        "official_first": True,
        "enabled": True,
    }


def put_json(url: str, payload: dict[str, Any], timeout: float) -> tuple[int, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize evidence-search official domain configs")
    parser.add_argument("--admin-url", default=DEFAULT_ADMIN_URL, help="Admin API base URL")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="HTTP timeout in seconds")
    parser.add_argument("--dry-run", action="store_true", help="Print payloads without writing them")
    parser.add_argument(
        "--only",
        help="Comma-separated category ids to initialize, for example: 1,5,9",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected_ids: set[str] | None = None
    if args.only:
        selected_ids = {item.strip() for item in args.only.split(",") if item.strip()}

    admin_url = args.admin_url.rstrip("/")
    configs = [cfg for cfg in CONFIGS if selected_ids is None or cfg["config_id"] in selected_ids]

    if not configs:
        print("No configs selected", file=sys.stderr)
        return 2

    for config in configs:
        payload = build_payload(config)
        url = f"{admin_url}/evidence-search/configs/{config['config_id']}"
        if args.dry_run:
            print(f"# PUT {url}")
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            continue

        status, body = put_json(url, payload, args.timeout)
        if status < 200 or status >= 300:
            print(f"ERROR {status} initializing category {config['config_id']}: {body}", file=sys.stderr)
            return 1
        print(f"OK category {config['config_id']} {config['category_name']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
