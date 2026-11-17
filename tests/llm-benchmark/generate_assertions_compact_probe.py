#!/usr/bin/env python3
"""Isolated, capped OpenRouter probe of single-call compact assertion schemas.

This test-side runner never calls the service, Kafka, databases, or Kubernetes.
All semantic fields remain model decisions; the adapter only expands bounded
wire structure and server-owned identifiers before validating existing models.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_assertions_isolated as bench

ROOT = Path(__file__).resolve().parents[2]
os.environ["MAX_ASSERTIONS"] = "7"  # Before loading the production AssertionBatch.
sys.path.insert(0, str(ROOT / "api"))
target = bench.load_target()
config = yaml.safe_load((ROOT / "k8s/apis/generate-asertions/configmap.yaml").read_text())["data"]
target.PROMPT = config["PROMPT"]
assert target.get_assertions_schema()["properties"]["assertions"]["maxItems"] == 7

from common.models.async_models import Assertion  # noqa: E402
from common.models.protocol_models import (  # noqa: E402
    AssertionContext, CategoryId, ContextConfidence, EntityContext,
    LocationContext, Origin, SearchHints, TemporalContext,
    build_assertions_document_v2,
)
from common.routing_taxonomy import (  # noqa: E402
    EntityRole, EntityType, EvidenceKind, JurisdictionScope,
    TemporalType, TopicCode,
)


class SemanticFull(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    categoryId: CategoryId
    topic_code: TopicCode
    evidence_kind: EvidenceKind
    context: AssertionContext
    search_hints: SearchHints
    context_confidence: ContextConfidence


class FullBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assertions: List[SemanticFull] = Field(max_length=7)


class KeyContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    locations: List[LocationContext]
    entities: List[EntityContext]
    temporal_context: List[TemporalContext]
    language: str
    jurisdiction_key: str
    applicable_country_codes: List[str]


class SemanticKey(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    categoryId: CategoryId
    topic_code: TopicCode
    evidence_kind: EvidenceKind
    context: KeyContext
    search_hints: SearchHints
    context_confidence: ContextConfidence


class KeyBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assertions: List[SemanticKey] = Field(max_length=7)


class WireLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n: str
    s: JurisdictionScope
    cc: Optional[str]
    rc: Optional[str]
    o: Origin
    p: float = Field(ge=0, le=1)


class WireEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n: str
    t: EntityType
    r: EntityRole
    o: Origin
    p: float = Field(ge=0, le=1)


class WireTemporal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: str
    t: TemporalType
    o: Origin
    p: float = Field(ge=0, le=1)


class SemanticWire(BaseModel):
    model_config = ConfigDict(extra="forbid")
    t: str
    c: CategoryId
    tp: TopicCode
    ev: EvidenceKind
    loc: List[WireLocation]
    ent: List[WireEntity]
    tm: List[WireTemporal]
    lang: str
    j: str
    ac: List[str]
    kw: List[str]
    q: List[str]
    cf: List[float] = Field(min_length=3, max_length=3)


class WireBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: List[SemanticWire] = Field(max_length=7)


SCHEMAS = {
    "LEGACY": target.get_assertions_schema(),
    "C1_semantic": FullBatch.model_json_schema(),
    "C2_jurisdiction_key": KeyBatch.model_json_schema(),
    "C3_wire": WireBatch.model_json_schema(),
}


def jurisdiction_from_key(key: str, applicable: List[str]) -> dict:
    """Expand a finite scope grammar; never infer a country or named entity."""
    parts = key.strip().upper().split(":")
    scope = parts[0]
    expected = {"GLOBAL": 1, "UNKNOWN": 1, "COUNTRY": 2,
                "SUPRANATIONAL": 2, "REGION": 3, "LOCAL": 4}
    if scope not in expected or len(parts) != expected[scope] or any(not x for x in parts):
        raise ValueError("invalid_jurisdiction_key")
    result = {"scope": scope, "country_code": None, "region_code": None,
              "jurisdiction_code": None, "applicable_country_codes": applicable}
    if scope == "COUNTRY":
        result["country_code"] = parts[1]
    elif scope == "SUPRANATIONAL":
        result["jurisdiction_code"] = parts[1]
    elif scope in {"REGION", "LOCAL"}:
        result["country_code"], result["region_code"] = parts[1:3]
        if scope == "LOCAL":
            result["jurisdiction_code"] = parts[3]
    return result


SELECTION = config["PROMPT"].split("CONTEXTO Y BÚSQUEDA", 1)[0].strip()
KEY_RULES = (
    "Representa la jurisdicción en una clave universal: GLOBAL, UNKNOWN, "
    "COUNTRY:XX, SUPRANATIONAL:CODE, REGION:XX:XX-SUBCODE o "
    "LOCAL:XX:XX-SUBCODE:LOCALCODE. XX es ISO 3166-1; no uses EU como país. "
    "En applicable_country_codes/ac, usa [] salvo que el alcance supranacional "
    "realmente requiera una lista explícita. No inventes códigos.\n"
)


def compact_prompt(variant: str, news: str) -> str:
    if variant == "LEGACY":
        return target.build_assertions_prompt(news)
    rules = (
        f"{SELECTION}\n\n"
        "Para cada aserción conserva en text/t todos los datos necesarios para verificarla "
        "de forma independiente, incluidos fecha o periodo, lugar, negación, cuantificadores y cifras. "
        "Usa el contexto global del artículo solo si está respaldado por el texto. "
        "Rellena las entidades y lugares por sus nombres reales en la noticia: no existe una lista cerrada. "
        "origin/o=explicit si el dato aparece en la aserción, inferred si solo aparece en otra parte "
        "del artículo, unknown si no hay base. Las consultas deben ser autónomas y útiles para buscar evidencia. "
        "No inventes contexto ni añadas campos que no pide el esquema.\n\n"
        f"CATEGORÍAS:\n{target.CATEGORY_CATALOG_PROMPT}\n"
        f"TOPIC_CODE:\n{target.TOPIC_PROMPT}\n"
        f"CATEGORYID PERMITIDOS POR TOPIC_CODE:\n{target.TOPIC_CATEGORY_PROMPT}\n"
        f"EVIDENCE_KIND:\n{target.EVIDENCE_KIND_PROMPT}\n"
    )
    if variant == "C1_semantic":
        rules += target.JURISDICTION_CONTRACT_PROMPT
        rules += ("Devuelve los campos semánticos text, categoryId, topic_code, evidence_kind, "
                  "context, search_hints y context_confidence. No generes IDs, índices ni taxonomy_version.\n")
    elif variant == "C2_jurisdiction_key":
        rules += KEY_RULES
        rules += ("context.jurisdiction_key contiene esa clave; context.applicable_country_codes "
                  "contiene la lista aplicable. Conserva todos los demás campos semánticos. "
                  "No generes IDs, índices ni taxonomy_version.\n")
    elif variant == "C3_wire":
        rules += KEY_RULES
        rules += (
            "Formato compacto de salida, sin pérdida semántica: a=aserciones; "
            "t=texto, c=categoryId, tp=topic_code, ev=evidence_kind; "
            "loc=locations (n=name, s=scope, cc=country_code, rc=region_code, o=origin, p=confidence); "
            "ent=entities (n=name, t=type, r=role, o=origin, p=confidence); "
            "tm=temporal_context (v=value, t=type, o=origin, p=confidence); "
            "lang=language; j=jurisdiction_key; ac=applicable_country_codes; "
            "kw=search_keywords; q=suggested_queries; "
            "cf=[location,entities,temporal] de context_confidence. "
            "Incluye hechos y consultas completos aunque las claves sean cortas.\n"
        )
    else:
        raise ValueError(variant)
    return rules + f"\nTexto a analizar:\n{news}\n\nDevuelve un máximo de 7 aserciones y solo JSON conforme al esquema.\n"


def wire_to_full(item: SemanticWire) -> dict:
    return {
        "text": item.t, "categoryId": item.c, "topic_code": item.tp,
        "evidence_kind": item.ev,
        "context": {
            "locations": [{"name": x.n, "scope": x.s, "country_code": x.cc,
                           "region_code": x.rc, "origin": x.o, "confidence": x.p}
                          for x in item.loc],
            "entities": [{"name": x.n, "type": x.t, "role": x.r,
                          "origin": x.o, "confidence": x.p} for x in item.ent],
            "temporal_context": [{"value": x.v, "type": x.t, "origin": x.o,
                                  "confidence": x.p} for x in item.tm],
            "language": item.lang,
            "jurisdiction": jurisdiction_from_key(item.j, item.ac),
        },
        "search_hints": {"search_keywords": item.kw, "suggested_queries": item.q},
        "context_confidence": {"location": item.cf[0], "entities": item.cf[1],
                               "temporal": item.cf[2]},
    }


def parse_and_validate(variant: str, content: str, news: str) -> list[dict]:
    raw = json.loads(content)
    if variant == "LEGACY":
        batch = target.AssertionBatch.model_validate(raw)
        assertions = target.parse_assertions_content(batch.model_dump(mode="json"))
    elif variant == "C1_semantic":
        items = FullBatch.model_validate(raw).assertions
        assertions = [Assertion.model_validate({**item.model_dump(mode="json"),
                      "idAssertion": str(i+1), "assertion_id": i+1,
                      "assertion_index": i}) for i, item in enumerate(items)]
    elif variant == "C2_jurisdiction_key":
        items = KeyBatch.model_validate(raw).assertions
        assertions = []
        for i, item in enumerate(items):
            fields = item.model_dump(mode="json")
            context = fields.pop("context")
            applicable = context.pop("applicable_country_codes")
            context["jurisdiction"] = jurisdiction_from_key(context.pop("jurisdiction_key"), applicable)
            assertions.append(Assertion.model_validate({**fields, "context": context,
                              "idAssertion": str(i+1), "assertion_id": i+1,
                              "assertion_index": i}))
    elif variant == "C3_wire":
        items = WireBatch.model_validate(raw).a
        assertions = [Assertion.model_validate({**wire_to_full(item),
                      "idAssertion": str(i+1), "assertion_id": i+1,
                      "assertion_index": i}) for i, item in enumerate(items)]
    else:
        raise ValueError(variant)
    for assertion in assertions:
        assertion.to_enriched()
    build_assertions_document_v2(text=news, assertions=assertions, mode="LIGHT",
                                 provider="openrouter", model="openai/gpt-5-nano")
    return [item.model_dump(mode="json") for item in assertions]


def schedule(cases: list[dict]) -> list[tuple[dict, str, int]]:
    variants = ["LEGACY", "C1_semantic", "C2_jurisdiction_key", "C3_wire"]
    orders = [variants, list(reversed(variants)),
              [variants[1], variants[3], variants[0], variants[2]],
              [variants[2], variants[0], variants[3], variants[1]],
              [variants[3], variants[0], variants[1], variants[2]]]
    return [(cases[0], v, 1) for v in orders[0]] + \
           [(cases[1], v, 1) for v in orders[1]] + \
           [(cases[0], v, 2) for v in orders[2]] + \
           [(cases[1], v, 2) for v in orders[3]] + \
           [(cases[2], v, 1) for v in orders[4]]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--cases", type=Path, nargs=3, required=True)
    parser.add_argument("--max-calls", type=int, default=20)
    parser.add_argument("--max-cost-usd", type=float, default=0.20)
    args = parser.parse_args()
    cases = [json.loads(path.read_text()) for path in args.cases]
    if not all("synthetic" in x.get("tags", []) or "evidence:synthetic" in x.get("tags", [])
               or "sintético" in x.get("description", "").lower() for x in cases):
        raise SystemExit("Only explicit synthetic test fixtures are allowed")
    planned = schedule(cases)
    if len(planned) != 20 or args.max_calls > 20:
        raise SystemExit("Campaign must have a hard ceiling of 20 provider calls")
    key = dotenv_values(ROOT / "api/generate-asertions/.env").get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("OpenRouter key unavailable")
    args.artifacts.mkdir(parents=True, exist_ok=True)
    calls = 0
    total_cost = 0.0
    for test_no, (case, variant, repetition) in enumerate(planned, 1):
        path = args.artifacts / f"{test_no:02d}-{case['id']}-{variant}-r{repetition}.json"
        if path.exists():
            saved = json.loads(path.read_text())
            calls += 1
            total_cost += saved.get("usage", {}).get("cost_usd") or 0
            continue
        if calls >= args.max_calls or total_cost >= args.max_cost_usd:
            print("CAP_REACHED", calls, round(total_cost, 8), flush=True)
            break
        prompt = compact_prompt(variant, case["news"])
        payload = bench.request_payload(prompt, SCHEMAS[variant],
                                        {"model": "openai/gpt-5-nano", "reasoning_effort": None})
        result = {"test_no": test_no, "case_id": case["id"], "variant": variant,
                  "repetition": repetition, "case_sha256": hashlib.sha256(case["news"].encode()).hexdigest(),
                  "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                  "prompt_chars": len(prompt),
                  "schema_chars": len(json.dumps(payload["response_format"]["json_schema"]["schema"])),
                  "status": "FAILED", "assertions": []}
        calls += 1
        started = time.monotonic()
        print("START", calls, case["id"], variant, repetition, flush=True)
        try:
            body = await bench.post_json(bench.CHAT_URL, key, payload, 240)
            result["seconds"] = round(time.monotonic() - started, 3)
            result["usage"] = bench.parse_usage(body)
            result["provider_model"] = body.get("model")
            result["finish_reason"] = body.get("choices", [{}])[0].get("finish_reason")
            result["content"] = bench.response_content(body)
            try:
                result["assertions"] = parse_and_validate(variant, result["content"], case["news"])
                result["status"] = "VALID"
            except Exception as exc:
                result["error_type"] = type(exc).__name__
                result["error"] = str(exc)[:300]
            total_cost += result["usage"].get("cost_usd") or 0
        except Exception as exc:
            result["seconds"] = round(time.monotonic() - started, 3)
            result["error_type"] = type(exc).__name__
            result["error"] = str(exc)[:300]
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        path.chmod(0o600)
        print("DONE", calls, result["status"], result["seconds"],
              len(result["assertions"]), round(total_cost, 8), flush=True)
    print("SUMMARY", calls, round(total_cost, 8), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
