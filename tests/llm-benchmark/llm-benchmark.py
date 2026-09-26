#!/usr/bin/env python3
"""Batch benchmark for versioned OpenRouter configurations in Assermetry."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import pathlib
import re
import sqlite3
import ssl
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Callable

ROOT = pathlib.Path(__file__).resolve().parents[2]
TEST_ROOT = ROOT / "tests" / "llm-benchmark"
DEFAULT_CASE = TEST_ROOT / "resources/cases/eu-news-2025-v1.json"
DEFAULT_PROFILE = TEST_ROOT / "resources/profiles/current-openrouter.json"
DEFAULT_ARTIFACTS = TEST_ROOT / "artifacts"
DEFAULT_DATABASE = DEFAULT_ARTIFACTS / "history.sqlite"
DEFAULT_GENERATED_PLANS = DEFAULT_ARTIFACTS / "generated"
TERMINAL_OK = {"VALIDATED", "VALIDATED_WITH_ERRORS"}
TERMINAL_FAIL = {
    "ERROR", "FAILED", "QUOTA_EXCEDED", "ASSERTIONS_NOT_AVAILABLE",
    "NO_VALIDATORS_AVAILABLE",
}
LLM_VALIDATOR_TYPES = {
    "LLM_MEMORY_VALIDATION", "LLM_SEARCH_VALIDATION", "RAG_EVIDENCE_VALIDATION",
}
VERDICTS = {0: "UNKNOWN", 1: "TRUE", 2: "FALSE"}
QUALITY_WEIGHTS = {
    "extraction": 0.25,
    "verdict": 0.45,
    "evidence": 0.20,
    "reliability": 0.10,
}


class BenchmarkError(RuntimeError):
    pass


def trace(phase: str, **fields: Any) -> None:
    """Emit a concise, secret-free progress record for interactive runs and logs."""
    parts = [f"phase={phase}"]
    for key, value in fields.items():
        if value is None:
            continue
        text = str(value).replace("\n", " ").replace("\r", " ").strip()
        parts.append(f"{key}={text or '-'}")
    print("LLM_BENCHMARK_TRACE " + " ".join(parts), flush=True)


class ApiError(BenchmarkError):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def slug_timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"No se pudo leer JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BenchmarkError(f"{path} debe contener un objeto JSON")
    return value


def write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def mean(values: list[float | None]) -> float | None:
    usable = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return round(statistics.fmean(usable), 8) if usable else None


def normalize_verdict(value: Any) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int) and value in VERDICTS:
        return VERDICTS[value]
    text = str(value or "").strip().upper()
    aliases = {
        "0": "UNKNOWN", "1": "TRUE", "2": "FALSE",
        "VERDADERO": "TRUE", "FALSO": "FALSE", "DESCONOCIDO": "UNKNOWN",
    }
    return aliases.get(text, text if text in {"TRUE", "FALSE", "UNKNOWN"} else "UNKNOWN")


def git_metadata() -> dict[str, Any]:
    def command(*args: str) -> str | None:
        result = subprocess.run(
            ["git", *args], cwd=ROOT, text=True, capture_output=True, check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None

    status = command("status", "--porcelain")
    return {
        "commit": command("rev-parse", "HEAD"),
        "dirty": bool(status) if status is not None else None,
    }


class TokenProvider:
    def __init__(self, origin: str, verify_tls: bool):
        self.origin = origin.rstrip("/")
        self.verify_tls = verify_tls
        self.static_token = os.getenv("ASSERMETRY_ACCESS_TOKEN", "").strip()
        self.username = os.getenv("ASSERMETRY_USERNAME", "").strip()
        self.password = os.getenv("ASSERMETRY_PASSWORD", "")
        self.realm = os.getenv("ASSERMETRY_KEYCLOAK_REALM", "TrustNews")
        self.client_secret = os.getenv("ASSERMETRY_KEYCLOAK_CLIENT_SECRET", "")
        self.client_id = os.getenv("ASSERMETRY_KEYCLOAK_CLIENT_ID", "TrustNewsApi")
        self.token_endpoint = os.getenv(
            "ASSERMETRY_TOKEN_URL",
            f"{self.origin}/auth/realms/{urllib.parse.quote(self.realm)}/protocol/openid-connect/token",
        )
        self.access_token: str | None = self.static_token or None
        self.refresh_token: str | None = None
        self.expires_at = float("inf") if self.static_token else 0.0

    def token(self) -> str:
        if self.static_token:
            return self.static_token
        if time.time() < self.expires_at - 30 and self.access_token:
            return self.access_token
        if self.refresh_token:
            try:
                self._request_token({
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                    "refresh_token": self.refresh_token,
                })
                return str(self.access_token)
            except BenchmarkError:
                self.refresh_token = None
        if self.client_secret:
            self._request_token({
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            })
            return str(self.access_token)
        if not self.username or not self.password:
            raise BenchmarkError(
                "Define ASSERMETRY_ACCESS_TOKEN, ASSERMETRY_KEYCLOAK_CLIENT_SECRET "
                "o ASSERMETRY_USERNAME y ASSERMETRY_PASSWORD"
            )
        self._request_token({
            "grant_type": "password",
            "client_id": self.client_id,
            "username": self.username,
            "password": self.password,
        })
        return str(self.access_token)

    def _request_token(self, form: dict[str, str]) -> None:
        request = urllib.request.Request(
            self.token_endpoint,
            data=urllib.parse.urlencode(form).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        context = ssl.create_default_context() if self.verify_tls else ssl._create_unverified_context()
        try:
            with urllib.request.urlopen(request, timeout=30, context=context) as response:
                payload = json.loads(response.read())
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            raise BenchmarkError(f"No se pudo obtener token de Keycloak: {exc}") from exc
        self.access_token = payload.get("access_token")
        self.refresh_token = payload.get("refresh_token")
        if not self.access_token:
            raise BenchmarkError("Keycloak no devolvió access_token")
        self.expires_at = time.time() + int(payload.get("expires_in") or 60)


class ApiClient:
    def __init__(self, base_url: str, token_provider: TokenProvider, verify_tls: bool, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.token_provider = token_provider
        self.verify_tls = verify_tls
        self.timeout = timeout

    def request(self, method: str, path: str, body: Any = None) -> Any:
        data = None if body is None else canonical_json(body).encode()
        request = urllib.request.Request(
            f"{self.base_url}/{path.lstrip('/')}",
            data=data,
            headers={
                "Authorization": f"Bearer {self.token_provider.token()}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method=method,
        )
        context = ssl.create_default_context() if self.verify_tls else ssl._create_unverified_context()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=context) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ApiError(exc.code, detail[:1000]) from exc
        except urllib.error.URLError as exc:
            raise BenchmarkError(f"Error de red en {method} {path}: {exc}") from exc
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BenchmarkError(f"Respuesta no JSON en {method} {path}") from exc

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, body: Any) -> Any:
        return self.request("POST", path, body)

    def put(self, path: str, body: Any) -> Any:
        return self.request("PUT", path, body)


def clear_evidence_cache(base_url: str, verify_tls: bool, timeout: float) -> dict[str, Any]:
    """Clear only Evidence Search's response cache and return its audit payload."""
    endpoint = f"{base_url.rstrip('/')}/admin/cache"
    request = urllib.request.Request(
        endpoint, headers={"Accept": "application/json"}, method="DELETE",
    )
    context = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ApiError(exc.code, f"Evidence Search cache: {detail[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise BenchmarkError(
            f"No se pudo limpiar la caché de Evidence Search en {endpoint}: {exc}"
        ) from exc
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise BenchmarkError(
            "Evidence Search devolvió una respuesta no JSON al limpiar la caché"
        ) from exc
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise BenchmarkError(f"Evidence Search no confirmó la limpieza de caché: {payload!r}")
    return {
        "cleared_at": utc_now(),
        "endpoint": endpoint,
        "deleted_count": int(payload.get("deleted_count") or 0),
        "cache_collection": payload.get("cache_collection"),
        "duration_seconds": round(time.monotonic() - started, 6),
    }


def actual_config(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("actual") if isinstance(payload.get("actual"), dict) else payload
    return {
        "provider": str(source.get("provider") or "").lower(),
        "model": str(source.get("model") or ""),
        "temperature": finite_number(source.get("temperature")),
        "config_version": int(source.get("config_version") or 0),
    }


def validator_type_name(value: dict[str, Any]) -> str:
    raw = value.get("validator_type")
    if isinstance(raw, dict):
        return str(raw.get("name") or "").upper()
    return str(raw or "").upper()


class ConfigurationManager:
    def __init__(self, client: ApiClient):
        self.client = client
        self.applied_targets: list[tuple[str, str]] = []

    def snapshot(self) -> dict[str, Any]:
        component_rows = self.client.get("/admin/llm/components").get("components") or []
        components = {
            str(row.get("component")): actual_config(row)
            for row in component_rows if row.get("component")
        }
        validators: dict[str, Any] = {}
        for row in self.client.get("/admin/llm/validators").get("validators") or []:
            type_name = validator_type_name(row)
            if type_name not in LLM_VALIDATOR_TYPES:
                continue
            validator_id = str(row.get("validator_id") or "")
            if not validator_id:
                continue
            detail = self.client.get(f"/admin/llm/validators/{urllib.parse.quote(validator_id, safe='')}")
            validators[validator_id] = {
                **actual_config(detail),
                "validator_type": type_name,
                "strategy": str(detail.get("evidence_search_strategy") or "").upper() or None,
            }
        return {"captured_at": utc_now(), "components": components, "validators": validators}

    @staticmethod
    def _resolve(desired: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
        provider = str(desired.get("provider") or "openrouter").lower()
        if provider != "openrouter":
            raise BenchmarkError("Todos los perfiles del benchmark deben usar provider=openrouter")
        model = desired.get("model")
        if model == "$current":
            if str(current.get("provider") or "").lower() != "openrouter":
                raise BenchmarkError("$current solo es válido cuando el proveedor efectivo es OpenRouter")
            model = current.get("model")
        if not isinstance(model, str) or not model.strip():
            raise BenchmarkError("Cada configuración debe indicar un modelo OpenRouter")
        result: dict[str, Any] = {"provider": "openrouter", "model": model.strip()}
        if desired.get("temperature") is not None:
            temperature = finite_number(desired["temperature"])
            if temperature is None or temperature < 0:
                raise BenchmarkError("temperature debe ser finita y mayor o igual que cero")
            result["temperature"] = temperature
        return result

    @staticmethod
    def _matches(rule: dict[str, Any], validator_id: str, current: dict[str, Any]) -> bool:
        selector = rule.get("selector") or {}
        if selector.get("id") and str(selector["id"]).lower() != validator_id.lower():
            return False
        types = selector.get("types")
        if types and current.get("validator_type") not in {str(item).upper() for item in types}:
            return False
        strategies = selector.get("strategies")
        if strategies and current.get("strategy") not in {str(item).upper() for item in strategies}:
            return False
        return True

    def resolve_profile(self, profile: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
        validate_profile(profile)
        resolved = {"components": {}, "validators": {}}
        for component, current in snapshot["components"].items():
            desired = (profile.get("components") or {}).get(component, {"model": "$current"})
            resolved["components"][component] = self._resolve(desired, current)
        rules = profile.get("validators") or [{"selector": {}, "provider": "openrouter", "model": "$current"}]
        for validator_id, current in snapshot["validators"].items():
            desired = None
            for rule in rules:
                if self._matches(rule, validator_id, current):
                    desired = rule
            if desired is None:
                raise BenchmarkError(f"El perfil no cubre el validador LLM {validator_id}")
            resolved["validators"][validator_id] = self._resolve(desired, current)
        return resolved

    def apply(self, resolved: dict[str, Any], current_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        self.applied_targets = []
        for component, desired in resolved["components"].items():
            current = current_snapshot["components"][component]
            if self._same(current, desired):
                continue
            response = self.client.put(
                f"/admin/llm/components/{urllib.parse.quote(component, safe='')}", desired,
            )
            changes.append({"kind": "component", "id": component, "response": response})
            self.applied_targets.append(("component", component))
        for validator_id, desired in resolved["validators"].items():
            current = current_snapshot["validators"][validator_id]
            if self._same(current, desired):
                continue
            response = self.client.put(
                f"/admin/llm/validators/{urllib.parse.quote(validator_id, safe='')}", desired,
            )
            changes.append({"kind": "validator", "id": validator_id, "response": response})
            self.applied_targets.append(("validator", validator_id))
        effective = self.snapshot()
        self._assert_effective(resolved, effective)
        return changes

    def restore(
        self,
        snapshot: dict[str, Any],
        targets: list[tuple[str, str]] | None = None,
    ) -> list[str]:
        errors: list[str] = []
        selected = set(targets) if targets is not None else {
            *(("component", key) for key in snapshot["components"]),
            *(("validator", key) for key in snapshot["validators"]),
        }
        for component, config in snapshot["components"].items():
            if ("component", component) not in selected:
                continue
            try:
                self.client.put(
                    f"/admin/llm/components/{urllib.parse.quote(component, safe='')}",
                    self._restore_payload(config),
                )
            except Exception as exc:
                errors.append(f"component:{component}: {exc}")
        for validator_id, config in snapshot["validators"].items():
            if ("validator", validator_id) not in selected:
                continue
            try:
                self.client.put(
                    f"/admin/llm/validators/{urllib.parse.quote(validator_id, safe='')}",
                    self._restore_payload(config),
                )
            except Exception as exc:
                errors.append(f"validator:{validator_id}: {exc}")
        if not errors and selected:
            try:
                effective = self.snapshot()
                for kind, target in selected:
                    section = "components" if kind == "component" else "validators"
                    expected = self._restore_payload(snapshot[section][target])
                    actual = effective[section].get(target)
                    if not actual or not self._same(actual, expected):
                        errors.append(f"{kind}:{target}: restauración no verificada")
            except Exception as exc:
                errors.append(f"verification: {exc}")
        return errors

    @staticmethod
    def _restore_payload(config: dict[str, Any]) -> dict[str, Any]:
        payload = {"provider": config["provider"], "model": config["model"]}
        if config.get("temperature") is not None:
            payload["temperature"] = config["temperature"]
        return payload

    @staticmethod
    def _same(current: dict[str, Any], desired: dict[str, Any]) -> bool:
        keys = set(desired)
        return all(current.get(key) == desired.get(key) for key in keys)

    @staticmethod
    def _assert_effective(resolved: dict[str, Any], effective: dict[str, Any]) -> None:
        for section in ("components", "validators"):
            for target, desired in resolved[section].items():
                actual = effective[section].get(target)
                if not actual or not ConfigurationManager._same(actual, desired):
                    raise BenchmarkError(f"Configuración efectiva inesperada para {section}:{target}")


def validate_case(case: dict[str, Any]) -> None:
    if int(case.get("schema_version") or 0) != 1:
        raise BenchmarkError("schema_version del caso debe ser 1")
    if not str(case.get("id") or "").strip() or not str(case.get("news") or "").strip():
        raise BenchmarkError("El caso necesita id y news")
    assertions = case.get("assertions")
    if not isinstance(assertions, list) or not assertions:
        raise BenchmarkError("El caso necesita assertions[]")
    ids: set[str] = set()
    for item in assertions:
        assertion_id = str(item.get("id") or "")
        if not assertion_id or assertion_id in ids:
            raise BenchmarkError("Cada aserción esperada necesita un id único")
        ids.add(assertion_id)
        if normalize_verdict(item.get("expected_verdict")) == "UNKNOWN":
            raise BenchmarkError(f"{assertion_id}: expected_verdict debe ser TRUE o FALSE")
        if not item.get("required_terms"):
            raise BenchmarkError(f"{assertion_id}: required_terms no puede estar vacío")


def validate_profile(profile: dict[str, Any]) -> None:
    if int(profile.get("schema_version") or 0) != 1:
        raise BenchmarkError("schema_version del perfil debe ser 1")
    if not str(profile.get("id") or "").strip():
        raise BenchmarkError("El perfil necesita id")
    entries = list((profile.get("components") or {}).values()) + list(profile.get("validators") or [])
    if not entries:
        raise BenchmarkError("El perfil no contiene configuraciones")
    for entry in entries:
        if str(entry.get("provider") or "openrouter").lower() != "openrouter":
            raise BenchmarkError(f"El perfil {profile['id']} contiene un proveedor distinto de OpenRouter")
        model = entry.get("model")
        if not isinstance(model, str) or not model.strip():
            raise BenchmarkError(f"El perfil {profile['id']} contiene un modelo vacío")


def collect_assertions(order: dict[str, Any]) -> list[dict[str, Any]]:
    for candidate in (
        order.get("assertions"),
        (order.get("document") or {}).get("assertions"),
        (order.get("assertions_document") or {}).get("assertions"),
    ):
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    return []


def normalized_words(text: str) -> set[str]:
    normalized = text.lower()
    substitutions = str.maketrans("áéíóúüñ", "aeiouun")
    normalized = normalized.translate(substitutions)
    return set(re.findall(r"[a-z0-9]+", normalized))


def assertion_identifier(assertion: dict[str, Any], index: int) -> str:
    return str(
        assertion.get("idAssertion")
        or assertion.get("assertion_id")
        or assertion.get("id")
        or index + 1
    )


def match_assertions(case: dict[str, Any], generated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    threshold = float(case.get("match_threshold") or 0.5)
    candidates: list[tuple[float, int, int]] = []
    for expected_index, expected in enumerate(case["assertions"]):
        required = normalized_words(" ".join(expected["required_terms"]))
        for generated_index, actual in enumerate(generated):
            words = normalized_words(str(actual.get("text") or actual.get("assertion") or ""))
            score = len(required & words) / len(required) if required else 0.0
            candidates.append((score, expected_index, generated_index))
    used_expected: set[int] = set()
    used_generated: set[int] = set()
    matches: list[dict[str, Any]] = []
    for score, expected_index, generated_index in sorted(candidates, reverse=True):
        if score < threshold or expected_index in used_expected or generated_index in used_generated:
            continue
        used_expected.add(expected_index)
        used_generated.add(generated_index)
        expected = case["assertions"][expected_index]
        actual = generated[generated_index]
        expected_categories = {int(value) for value in expected.get("category_ids") or []}
        actual_category = actual.get("categoryId") or actual.get("category_id")
        matches.append({
            "expected_id": expected["id"],
            "expected_verdict": normalize_verdict(expected["expected_verdict"]),
            "expected_category_ids": sorted(expected_categories),
            "generated_index": generated_index,
            "generated_id": assertion_identifier(actual, generated_index),
            "generated_text": actual.get("text") or actual.get("assertion"),
            "generated_category_id": actual_category,
            "match_score": round(score, 6),
            "category_match": (
                int(actual_category) in expected_categories
                if actual_category is not None and expected_categories else None
            ),
        })
    return sorted(matches, key=lambda item: item["expected_id"])


def result_for_assertion(order: dict[str, Any], assertion_id: str) -> dict[str, Any] | None:
    results = order.get("assertion_results") or {}
    if isinstance(results, dict):
        value = results.get(assertion_id)
        if isinstance(value, dict):
            return value
    if isinstance(results, list):
        for value in results:
            if isinstance(value, dict) and str(value.get("assertion_id")) == assertion_id:
                return value
    return None


def validation_records(order: dict[str, Any], assertion_id: str) -> list[tuple[str, dict[str, Any]]]:
    validations = order.get("validations") or {}
    rows = validations.get(assertion_id) if isinstance(validations, dict) else None
    if isinstance(rows, dict):
        return [(str(key), value) for key, value in rows.items() if isinstance(value, dict)]
    if isinstance(rows, list):
        return [
            (str(value.get("idValidator") or value.get("validator_id") or index), value)
            for index, value in enumerate(rows) if isinstance(value, dict)
        ]
    return []


def score_order(case: dict[str, Any], order: dict[str, Any]) -> dict[str, Any]:
    generated = collect_assertions(order)
    matches = match_assertions(case, generated)
    expected_count = len(case["assertions"])
    generated_count = len(generated)
    coverage = len(matches) / expected_count
    precision = len(matches) / generated_count if generated_count else 0.0
    category_values = [item["category_match"] for item in matches if item["category_match"] is not None]
    category_accuracy = (
        sum(bool(value) for value in category_values) / len(category_values)
        if category_values else None
    )
    count_score = max(0.0, 1.0 - abs(generated_count - expected_count) / expected_count)
    extraction_parts = [coverage, precision, count_score]
    if category_accuracy is not None:
        extraction_parts.append(category_accuracy)
    extraction_score = statistics.fmean(extraction_parts)

    verdict_checks: list[bool] = []
    evidence_checks: list[bool] = []
    reliability_checks: list[bool] = []
    validator_scores: dict[str, list[bool]] = {}
    latencies: dict[str, list[float]] = {}
    assertion_rows: list[dict[str, Any]] = []

    for match in matches:
        aggregate = result_for_assertion(order, match["generated_id"])
        actual_verdict = normalize_verdict((aggregate or {}).get("verdict"))
        verdict_match = actual_verdict == match["expected_verdict"]
        verdict_checks.append(verdict_match)
        per_validator: list[dict[str, Any]] = []
        for validator_id, validation in validation_records(order, match["generated_id"]):
            completed = str(validation.get("execution_status") or "").upper() == "COMPLETED"
            reliability_checks.append(completed)
            validator_verdict = normalize_verdict(validation.get("approval"))
            validator_match = completed and validator_verdict == match["expected_verdict"]
            validator_scores.setdefault(validator_id, []).append(validator_match)
            latency = finite_number(validation.get("response_time_seconds"))
            if latency is not None:
                latencies.setdefault(validator_id, []).append(latency)
            validator_type = str(validation.get("validator_type") or "").upper()
            has_evidence_fields = any(
                validation.get(field) for field in ("evidence_used", "sources", "sources_declared")
            )
            if "RAG" in validator_type or has_evidence_fields:
                evidence_checks.append(bool(validation.get("evidence_used")))
            config = validation.get("validator_config") or {}
            per_validator.append({
                "validator_id": validator_id,
                "model": config.get("model"),
                "validator_type": validator_type or None,
                "verdict": validator_verdict,
                "expected_verdict": match["expected_verdict"],
                "correct": validator_match,
                "completed": completed,
                "response_time_seconds": latency,
                "evidence_used_count": len(validation.get("evidence_used") or []),
            })
        assertion_rows.append({
            **match,
            "aggregate_verdict": actual_verdict,
            "verdict_correct": verdict_match,
            "validators": per_validator,
        })

    verdict_accuracy = sum(verdict_checks) / expected_count
    reliability = (
        sum(reliability_checks) / len(reliability_checks) if reliability_checks else 0.0
    )
    evidence_score = (
        sum(evidence_checks) / len(evidence_checks) if evidence_checks else None
    )
    components = {
        "extraction": extraction_score,
        "verdict": verdict_accuracy,
        "evidence": evidence_score,
        "reliability": reliability,
    }
    available_weight = sum(
        QUALITY_WEIGHTS[key] for key, value in components.items() if value is not None
    )
    quality_score = sum(
        QUALITY_WEIGHTS[key] * float(value)
        for key, value in components.items() if value is not None
    ) / available_weight

    return {
        "quality_score": round(quality_score * 100, 4),
        "metrics": {
            "expected_assertions": expected_count,
            "generated_assertions": generated_count,
            "matched_assertions": len(matches),
            "assertion_coverage": round(coverage, 6),
            "assertion_precision": round(precision, 6),
            "assertion_count_score": round(count_score, 6),
            "category_accuracy": round(category_accuracy, 6) if category_accuracy is not None else None,
            "extraction_score": round(extraction_score, 6),
            "verdict_accuracy": round(verdict_accuracy, 6),
            "evidence_score": round(evidence_score, 6) if evidence_score is not None else None,
            "reliability": round(reliability, 6),
        },
        "assertions": assertion_rows,
        "validators": {
            validator_id: {
                "accuracy": round(sum(values) / len(values), 6),
                "evaluated_assertions": len(values),
                "mean_response_time_seconds": mean(latencies.get(validator_id, [])),
            }
            for validator_id, values in validator_scores.items()
        },
    }


def collect_costs(
    pricing: dict[str, Any],
    assertion_count: int,
    expected_targets: set[str] | None = None,
) -> dict[str, Any]:
    rows = pricing.get("deployment_recommendations") or []
    local_rag_count = sum(
        row.get("target_kind") == "validator" and row.get("workload_key") == "ragLocal"
        for row in rows
    )
    modules: list[dict[str, Any]] = []
    for row in rows:
        per_execution = finite_number(row.get("estimated_current_cost_usd"))
        if row.get("target_id") == "generate-asertions":
            sample_executions, normalized_executions = 1, 1
        elif row.get("target_id") == "source-router":
            sample_executions = assertion_count * local_rag_count
            normalized_executions = 5 * local_rag_count
        elif row.get("target_kind") == "validator":
            sample_executions, normalized_executions = assertion_count, 5
        else:
            sample_executions, normalized_executions = 0, 0
        modules.append({
            "target_id": row.get("target_id"),
            "target_kind": row.get("target_kind"),
            "provider": row.get("current_provider"),
            "model": row.get("current_model"),
            "input_tokens_sample": row.get("input_tokens"),
            "output_tokens_sample": row.get("output_tokens"),
            "estimated_cost_per_execution_usd": per_execution,
            "sample_executions": sample_executions,
            "normalized_5_assertions_executions": normalized_executions,
            "sample_estimated_cost_usd": (
                round(per_execution * sample_executions, 8) if per_execution is not None else None
            ),
            "normalized_5_assertions_cost_usd": (
                round(per_execution * normalized_executions, 8) if per_execution is not None else None
            ),
        })
    sample_total = (
        round(sum(item["sample_estimated_cost_usd"] for item in modules), 8)
        if modules and all(item["sample_estimated_cost_usd"] is not None for item in modules)
        else None
    )
    normalized_total = (pricing.get("estimated_news_costs_usd") or {}).get("current")
    returned_targets = {str(item.get("target_id")) for item in rows}
    missing_targets = sorted((expected_targets or set()) - returned_targets)
    return {
        "method": "estimated_from_openrouter_catalog_and_workload_token_samples",
        "catalog_generated_at": pricing.get("generated_at"),
        "sample_assertion_count": assertion_count,
        "sample_total_usd": sample_total,
        "normalized_5_assertions_total_usd": finite_number(normalized_total),
        "complete": (
            sample_total is not None and normalized_total is not None and not missing_targets
        ),
        "missing_targets": missing_targets,
        "modules": modules,
    }


def last_order_event(client: ApiClient, order_id: str) -> str:
    """Return a small, display-safe summary of the latest event, without affecting polling."""
    try:
        payload = client.get(f"/orders/{urllib.parse.quote(order_id, safe='')}/events")
    except Exception as exc:  # Event diagnostics must never alter benchmark control flow.
        return f"unavailable:{type(exc).__name__}"
    events = payload.get("events") if isinstance(payload, dict) else payload
    if not isinstance(events, list) or not events:
        return "none"
    event = next((item for item in reversed(events) if isinstance(item, dict)), None)
    if event is None:
        return "none"
    action = event.get("action") or event.get("event") or event.get("type") or "unknown"
    timestamp = event.get("created_at") or event.get("timestamp") or event.get("date") or "-"
    event_id = event.get("event_id") or event.get("id") or "-"
    return f"action:{action},at:{timestamp},id:{event_id}"


def wait_for_order(
    client: ApiClient,
    order_id: str,
    timeout_seconds: float,
    poll_seconds: float,
    progress: Callable[[dict[str, Any], str, str], None] | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last = client.get(f"/orders/{urllib.parse.quote(order_id, safe='')}")
        status = str(last.get("status") or "").upper()
        if progress is not None:
            progress(last, status, last_order_event(client, order_id))
        if status in TERMINAL_OK:
            return last
        if status in TERMINAL_FAIL:
            raise BenchmarkError(f"La orden {order_id} terminó en {status}")
        time.sleep(poll_seconds)
    raise BenchmarkError(f"Timeout esperando la orden {order_id}; último estado: {(last or {}).get('status')}")


SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
  batch_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
  status TEXT NOT NULL, case_id TEXT NOT NULL, git_commit TEXT, git_dirty INTEGER,
  artifacts_dir TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, profile_id TEXT NOT NULL,
  repetition INTEGER NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
  status TEXT NOT NULL, order_id TEXT, quality_score REAL,
  verdict_accuracy REAL, sample_cost_usd REAL, normalized_cost_usd REAL,
  duration_seconds REAL, error TEXT, profile_snapshot_json TEXT NOT NULL,
  FOREIGN KEY(batch_id) REFERENCES batches(batch_id)
);
CREATE TABLE IF NOT EXISTS module_costs (
  run_id TEXT NOT NULL, target_id TEXT NOT NULL, target_kind TEXT,
  model TEXT, cost_per_execution_usd REAL, sample_cost_usd REAL,
  normalized_cost_usd REAL, PRIMARY KEY(run_id, target_id)
);
CREATE TABLE IF NOT EXISTS assertion_scores (
  run_id TEXT NOT NULL, expected_id TEXT NOT NULL, generated_id TEXT,
  expected_verdict TEXT NOT NULL, actual_verdict TEXT, correct INTEGER NOT NULL,
  match_score REAL, PRIMARY KEY(run_id, expected_id)
);
CREATE TABLE IF NOT EXISTS metrics (
  run_id TEXT NOT NULL, name TEXT NOT NULL, value REAL,
  PRIMARY KEY(run_id, name)
);
"""


class History:
    def __init__(self, path: pathlib.Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def start_batch(self, manifest: dict[str, Any]) -> None:
        git = manifest["git"]
        self.connection.execute(
            "INSERT INTO batches VALUES (?, ?, NULL, ?, ?, ?, ?, ?)",
            (
                manifest["batch_id"], manifest["started_at"], "RUNNING", manifest["case"]["id"],
                git.get("commit"), int(git["dirty"]) if git.get("dirty") is not None else None,
                manifest["artifacts_dir"],
            ),
        )
        self.connection.commit()

    def finish_batch(self, batch_id: str, status: str, finished_at: str) -> None:
        self.connection.execute(
            "UPDATE batches SET finished_at=?, status=? WHERE batch_id=?",
            (finished_at, status, batch_id),
        )
        self.connection.commit()

    def save_run(self, run: dict[str, Any]) -> None:
        metrics = (run.get("score") or {}).get("metrics") or {}
        costs = run.get("costs") or {}
        self.connection.execute(
            """INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run["run_id"], run["batch_id"], run["profile_id"], run["repetition"],
                run["started_at"], run.get("finished_at"), run["status"], run.get("order_id"),
                (run.get("score") or {}).get("quality_score"), metrics.get("verdict_accuracy"),
                costs.get("sample_total_usd"), costs.get("normalized_5_assertions_total_usd"),
                run.get("duration_seconds"), run.get("error"),
                canonical_json(run.get("resolved_profile") or {}),
            ),
        )
        for item in costs.get("modules") or []:
            self.connection.execute(
                "INSERT INTO module_costs VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run["run_id"], item["target_id"], item.get("target_kind"), item.get("model"),
                    item.get("estimated_cost_per_execution_usd"),
                    item.get("sample_estimated_cost_usd"),
                    item.get("normalized_5_assertions_cost_usd"),
                ),
            )
        for item in (run.get("score") or {}).get("assertions") or []:
            self.connection.execute(
                "INSERT INTO assertion_scores VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run["run_id"], item["expected_id"], item.get("generated_id"),
                    item["expected_verdict"], item.get("aggregate_verdict"),
                    int(bool(item.get("verdict_correct"))), item.get("match_score"),
                ),
            )
        for name, value in metrics.items():
            if isinstance(value, (int, float)):
                self.connection.execute(
                    "INSERT INTO metrics VALUES (?, ?, ?)", (run["run_id"], name, value),
                )
        self.connection.commit()

    def list_runs(self, limit: int) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT run_id, profile_id, started_at, status, quality_score,
                      verdict_accuracy, sample_cost_usd, normalized_cost_usd
               FROM runs ORDER BY started_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        keys = [
            "run_id", "profile_id", "started_at", "status", "quality_score",
            "verdict_accuracy", "sample_cost_usd", "normalized_cost_usd",
        ]
        return [dict(zip(keys, row)) for row in rows]

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            """SELECT run_id, profile_id, started_at, status, quality_score,
                      verdict_accuracy, sample_cost_usd, normalized_cost_usd,
                      duration_seconds
               FROM runs WHERE run_id=?""",
            (run_id,),
        ).fetchone()
        if not row:
            raise BenchmarkError(f"No existe la ejecución {run_id}")
        keys = [
            "run_id", "profile_id", "started_at", "status", "quality_score",
            "verdict_accuracy", "sample_cost_usd", "normalized_cost_usd",
            "duration_seconds",
        ]
        return dict(zip(keys, row))


def comparison(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    def delta(key: str) -> float | None:
        left, right = finite_number(baseline.get(key)), finite_number(candidate.get(key))
        return round(right - left, 8) if left is not None and right is not None else None

    return {
        "baseline": baseline,
        "candidate": candidate,
        "delta": {
            "quality_score": delta("quality_score"),
            "verdict_accuracy": delta("verdict_accuracy"),
            "sample_cost_usd": delta("sample_cost_usd"),
            "normalized_cost_usd": delta("normalized_cost_usd"),
            "duration_seconds": delta("duration_seconds"),
        },
    }


def profile_summary(profile_id: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "profile_id": profile_id,
        "runs": len(runs),
        "passed": sum(run["status"] == "PASS" for run in runs),
        "quality_score_mean": mean([(run.get("score") or {}).get("quality_score") for run in runs]),
        "verdict_accuracy_mean": mean([
            ((run.get("score") or {}).get("metrics") or {}).get("verdict_accuracy") for run in runs
        ]),
        "sample_cost_usd_mean": mean([(run.get("costs") or {}).get("sample_total_usd") for run in runs]),
        "normalized_5_assertions_cost_usd_mean": mean([
            (run.get("costs") or {}).get("normalized_5_assertions_total_usd") for run in runs
        ]),
        "duration_seconds_mean": mean([run.get("duration_seconds") for run in runs]),
    }


def markdown_report(summary: dict[str, Any]) -> str:
    lines = [
        f"# LLM benchmark {summary['batch_id']}",
        "",
        f"- Estado: {summary['status']}",
        f"- Inicio: {summary['started_at']}",
        f"- Fin: {summary['finished_at']}",
        f"- Caso: {summary['case_id']}",
        "",
        "| Perfil | Runs | PASS | Calidad | Exactitud | Coste muestra | Coste 5 aserciones | Duración |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summary["profiles"]:
        def show(value: Any, digits: int = 6) -> str:
            return "—" if value is None else f"{value:.{digits}f}"
        lines.append(
            f"| {item['profile_id']} | {item['runs']} | {item['passed']} | "
            f"{show(item['quality_score_mean'], 2)} | {show(item['verdict_accuracy_mean'], 3)} | "
            f"{show(item['sample_cost_usd_mean'])} | "
            f"{show(item['normalized_5_assertions_cost_usd_mean'])} | "
            f"{show(item['duration_seconds_mean'], 2)} |"
        )
    return "\n".join(lines) + "\n"


@contextlib.contextmanager
def exclusive_lock(path: pathlib.Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BenchmarkError(f"Ya existe otro benchmark usando {path}") from exc
        handle.write(f"pid={os.getpid()} started_at={utc_now()}\n")
        handle.flush()
        yield


def pricing_snapshot(client: ApiClient, max_news_cost: float | None) -> dict[str, Any]:
    params = {"limit": "30", "min_quality_score": "1"}
    if max_news_cost is not None:
        params["max_news_cost_usd"] = str(max_news_cost)
    return client.get(f"/admin/llm/models/openrouter?{urllib.parse.urlencode(params)}")


def _profile_entry(model: str, temperature: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {"provider": "openrouter", "model": model}
    value = finite_number(temperature)
    if value is not None:
        entry["temperature"] = value
    return entry


def generated_profiles(
    snapshot: dict[str, Any],
    pricing: dict[str, Any],
    requested_max_usd: float,
    effective_max_usd: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build complete, exact-ID profiles from constrained deployment recommendations."""
    current_targets = {
        *(("component", target) for target in snapshot.get("components") or {}),
        *(("validator", target) for target in snapshot.get("validators") or {}),
    }
    rows = pricing.get("deployment_recommendations") or []
    response_targets = {
        (str(row.get("target_kind") or ""), str(row.get("target_id") or ""))
        for row in rows
    }
    recommendation_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("target_kind") or ""), str(row.get("target_id") or ""))
        if key in current_targets:
            recommendation_rows[key] = row

    returned_targets = set(recommendation_rows)
    missing = sorted(f"{kind}:{target}" for kind, target in current_targets - returned_targets)
    unknown = sorted(f"{kind}:{target}" for kind, target in response_targets - current_targets)
    incomplete_costs = sorted(
        f"{kind}:{target}" for (kind, target), row in recommendation_rows.items()
        if finite_number(row.get("estimated_current_cost_usd")) is None
    )
    non_openrouter = sorted(
        f"{kind}:{target}" for (kind, target), row in recommendation_rows.items()
        if str(row.get("current_provider") or "").lower() != "openrouter"
    )
    stale_targets = sorted(
        f"{kind}:{target}" for (kind, target), row in recommendation_rows.items()
        if (
            str(row.get("current_model") or "")
            != str(
                snapshot["components" if kind == "component" else "validators"][target]
                .get("model") or ""
            )
            or str(row.get("current_provider") or "").lower()
            != str(
                snapshot["components" if kind == "component" else "validators"][target]
                .get("provider") or ""
            ).lower()
        )
    )
    if missing or unknown or incomplete_costs or non_openrouter or stale_targets:
        details = []
        if missing:
            details.append("sin recomendación/coste: " + ", ".join(missing))
        if unknown:
            details.append("targets nuevos durante la captura: " + ", ".join(unknown))
        if incomplete_costs:
            details.append("coste actual ausente: " + ", ".join(incomplete_costs))
        if non_openrouter:
            details.append("proveedor no OpenRouter: " + ", ".join(non_openrouter))
        if stale_targets:
            details.append("snapshot inconsistente: " + ", ".join(stale_targets))
        raise BenchmarkError("No se pueden generar perfiles con costes incompletos (" + "; ".join(details) + ")")

    tier_specs = (
        ("premium", "premium-safe"),
        ("similar", "balanced-safe"),
        ("budget", "budget-safe"),
    )
    totals = pricing.get("estimated_news_costs_usd") or {}
    profiles: list[dict[str, Any]] = []
    discarded: list[dict[str, Any]] = []
    fingerprints: dict[str, str] = {}

    for tier, profile_id in tier_specs:
        total = finite_number(totals.get(tier))
        if total is None:
            discarded.append({"tier": tier, "profile_id": profile_id, "reason": "cost_not_verifiable"})
            continue
        if total > effective_max_usd + 1e-12:
            discarded.append({
                "tier": tier, "profile_id": profile_id, "reason": "over_effective_budget",
                "estimated_news_cost_usd": total,
            })
            continue

        components: dict[str, Any] = {}
        validators: list[dict[str, Any]] = []
        for kind, target in sorted(current_targets):
            current = snapshot["components" if kind == "component" else "validators"][target]
            row = recommendation_rows[(kind, target)]
            option = next(
                (item for item in row.get("options") or [] if item.get("tier") == tier), None,
            )
            model = str((option or {}).get("model") or current.get("model") or "").strip()
            if not model:
                raise BenchmarkError(f"Modelo vacío para {kind}:{target}")
            entry = _profile_entry(model, current.get("temperature"))
            if kind == "component":
                components[target] = entry
            else:
                validators.append({"selector": {"id": target}, **entry})

        resolved = {"components": components, "validators": validators}
        fingerprint = sha256_text(canonical_json(resolved))
        if fingerprint in fingerprints:
            discarded.append({
                "tier": tier, "profile_id": profile_id, "reason": "duplicate_configuration",
                "duplicate_of": fingerprints[fingerprint], "estimated_news_cost_usd": total,
            })
            continue
        fingerprints[fingerprint] = profile_id
        profiles.append({
            "schema_version": 1,
            "id": profile_id,
            "description": (
                f"Perfil OpenRouter generado para el nivel {tier}; coste estimado de noticia "
                f"{total:.8f} USD, máximo solicitado {requested_max_usd:.8f} USD."
            ),
            "components": components,
            "validators": validators,
            "generation": {
                "tier": tier,
                "estimated_news_cost_usd": total,
                "requested_max_news_cost_usd": requested_max_usd,
                "effective_max_news_cost_usd": effective_max_usd,
                "configuration_sha256": fingerprint,
            },
        })
    if not profiles:
        reasons = ", ".join(f"{item['tier']}={item['reason']}" for item in discarded)
        raise BenchmarkError(f"El presupuesto no produjo ningún perfil ejecutable ({reasons})")
    return profiles, discarded


def load_profile_plan(path: pathlib.Path) -> tuple[list[pathlib.Path], dict[str, Any]]:
    plan = read_json(path)
    if int(plan.get("schema_version") or 0) != 1 or not plan.get("plan_id"):
        raise BenchmarkError(f"Plan de perfiles inválido: {path}")
    entries = plan.get("profiles")
    if not isinstance(entries, list) or not entries:
        raise BenchmarkError(f"El plan no contiene perfiles: {path}")
    profile_paths: list[pathlib.Path] = []
    for entry in entries:
        raw_path = entry.get("path") if isinstance(entry, dict) else None
        if not raw_path:
            raise BenchmarkError(f"Entrada de perfil inválida en {path}")
        candidate = pathlib.Path(str(raw_path))
        resolved = (path.parent / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        profile = read_json(resolved)
        expected_hash = str(entry.get("sha256") or "")
        if not expected_hash or sha256_text(canonical_json(profile)) != expected_hash:
            raise BenchmarkError(f"El perfil no coincide con el hash registrado en el plan: {resolved}")
        profile_paths.append(resolved)
    effective_max = finite_number(plan.get("effective_max_news_cost_usd"))
    requested_max = finite_number(plan.get("requested_max_news_cost_usd"))
    if effective_max is None or requested_max is None or effective_max <= 0 or effective_max > requested_max:
        raise BenchmarkError(f"Presupuesto inválido en el plan {path}")
    return profile_paths, plan


def generate_profile_plan(args: argparse.Namespace) -> int:
    requested_max = float(args.max_news_cost_usd)
    effective_max = round(requested_max * (1 - args.budget_headroom_percent / 100), 12)
    if effective_max <= 0:
        raise BenchmarkError("El margen de presupuesto deja un máximo efectivo no positivo")

    base_url = args.base_url.rstrip("/")
    origin = base_url[:-8] if base_url.endswith("/backend") else base_url
    token_provider = TokenProvider(origin, args.verify_tls)
    client = ApiClient(base_url, token_provider, args.verify_tls, args.http_timeout)
    manager = ConfigurationManager(client)
    snapshot = manager.snapshot()
    pricing = pricing_snapshot(client, effective_max)
    profiles, discarded = generated_profiles(snapshot, pricing, requested_max, effective_max)

    plan_id = args.plan_id or f"openrouter-plan-{slug_timestamp()}-{uuid.uuid4().hex[:8]}"
    output_dir = pathlib.Path(args.output_root).resolve() / plan_id
    if output_dir.exists():
        raise BenchmarkError(f"El directorio del plan ya existe: {output_dir}")
    profiles_dir = output_dir / "profiles"
    profile_entries = []
    for profile in profiles:
        profile_path = profiles_dir / f"{profile['id']}.json"
        write_json(profile_path, profile)
        profile_entries.append({
            "id": profile["id"],
            "tier": profile["generation"]["tier"],
            "path": str(profile_path.relative_to(output_dir)),
            "sha256": sha256_text(canonical_json(profile)),
            "estimated_news_cost_usd": profile["generation"]["estimated_news_cost_usd"],
        })
    write_json(output_dir / "effective-configuration.json", snapshot)
    write_json(output_dir / "pricing-snapshot.json", pricing)
    plan = {
        "schema_version": 1,
        "plan_id": plan_id,
        "generated_at": utc_now(),
        "base_url": base_url,
        "provider": "openrouter",
        "requested_max_news_cost_usd": requested_max,
        "budget_headroom_percent": args.budget_headroom_percent,
        "effective_max_news_cost_usd": effective_max,
        "catalog_generated_at": pricing.get("generated_at"),
        "effective_configuration_sha256": sha256_text(canonical_json(snapshot)),
        "profiles": profile_entries,
        "discarded": discarded,
    }
    plan_path = output_dir / "plan.json"
    write_json(plan_path, plan)
    print(f"LLM_PROFILE_PLAN {plan_path}")
    for entry in profile_entries:
        print(
            f"LLM_PROFILE_GENERATED id={entry['id']} tier={entry['tier']} "
            f"cost_usd={entry['estimated_news_cost_usd']}"
        )
    return 0


def run_benchmark(args: argparse.Namespace) -> int:
    case_path = pathlib.Path(args.case).resolve()
    plan: dict[str, Any] | None = None
    if args.profile_plan:
        if args.profile:
            raise BenchmarkError("--profile y --profile-plan no se pueden combinar")
        plan_path = pathlib.Path(args.profile_plan).resolve()
        profile_paths, plan = load_profile_plan(plan_path)
        plan_max = float(plan["effective_max_news_cost_usd"])
        if args.max_news_cost_usd is not None and args.max_news_cost_usd > plan_max:
            raise BenchmarkError(
                "--max-news-cost-usd no puede relajar el máximo efectivo del plan "
                f"({plan_max})"
            )
        args.max_news_cost_usd = (
            min(args.max_news_cost_usd, plan_max) if args.max_news_cost_usd else plan_max
        )
    else:
        profile_paths = [pathlib.Path(value).resolve() for value in args.profile]
    case = read_json(case_path)
    validate_case(case)
    profiles = [read_json(path) for path in profile_paths]
    for profile in profiles:
        validate_profile(profile)
    profile_ids = [str(profile["id"]) for profile in profiles]
    if len(profile_ids) != len(set(profile_ids)):
        raise BenchmarkError("Los profile.id deben ser únicos en el batch")

    base_url = args.base_url.rstrip("/")
    origin = base_url[:-8] if base_url.endswith("/backend") else base_url
    verify_tls = args.verify_tls
    token_provider = TokenProvider(origin, verify_tls)
    client = ApiClient(base_url, token_provider, verify_tls, args.http_timeout)
    manager = ConfigurationManager(client)

    batch_id = args.batch_id or f"llmbench-{slug_timestamp()}-{uuid.uuid4().hex[:8]}"
    artifacts_root = pathlib.Path(args.artifacts_root).resolve()
    batch_dir = artifacts_root / batch_id
    if batch_dir.exists():
        raise BenchmarkError(f"El directorio de ejecución ya existe: {batch_dir}")
    batch_dir.mkdir(parents=True)
    history = History(pathlib.Path(args.database).resolve())
    started_at = utc_now()
    manifest = {
        "schema_version": 1,
        "batch_id": batch_id,
        "started_at": started_at,
        "artifacts_dir": str(batch_dir),
        "case": {"id": case["id"], "path": str(case_path), "sha256": sha256_text(canonical_json(case))},
        "profiles": [
            {"id": profile["id"], "path": str(path), "sha256": sha256_text(canonical_json(profile))}
            for profile, path in zip(profiles, profile_paths)
        ],
        "repetitions": args.repetitions,
        "base_url": base_url,
        "git": git_metadata(),
        "cost_method": "estimated; no se persiste usage real en las órdenes actuales",
        "evidence_cache": {
            "clear_before_each_repetition": args.clear_evidence_cache,
            "url": args.evidence_search_url if args.clear_evidence_cache else None,
        },
        "profile_plan": ({
            "plan_id": plan["plan_id"],
            "path": str(pathlib.Path(args.profile_plan).resolve()),
            "requested_max_news_cost_usd": plan["requested_max_news_cost_usd"],
            "effective_max_news_cost_usd": plan["effective_max_news_cost_usd"],
        } if plan else None),
    }
    write_json(batch_dir / "manifest.json", manifest)
    trace("batch.prepared", batch_id=batch_id, case_id=case["id"], profiles=len(profiles), repetitions=args.repetitions, artifacts=batch_dir)
    history.start_batch(manifest)
    all_runs: list[dict[str, Any]] = []
    batch_status = "FAIL"
    initial_snapshot: dict[str, Any] | None = None
    restore_errors: list[str] = []

    try:
        trace("lock.wait", path=args.lock_file)
        with exclusive_lock(pathlib.Path(args.lock_file)):
            trace("lock.acquired", path=args.lock_file)
            trace("configuration.snapshot.start")
            initial_snapshot = manager.snapshot()
            trace("configuration.snapshot.complete", components=len(initial_snapshot["components"]), validators=len(initial_snapshot["validators"]))
            write_json(batch_dir / "initial-configuration.json", initial_snapshot)
            for profile in profiles:
                profile_runs: list[dict[str, Any]] = []
                trace("profile.start", profile_id=profile["id"])
                resolved = manager.resolve_profile(profile, initial_snapshot)
                profile_dir = batch_dir / str(profile["id"])
                write_json(profile_dir / "resolved-profile.json", resolved)
                try:
                    trace("configuration.apply.start", profile_id=profile["id"])
                    changes = manager.apply(resolved, initial_snapshot)
                    trace("configuration.apply.complete", profile_id=profile["id"], changes=len(changes))
                    write_json(profile_dir / "configuration-changes.json", changes)
                    trace("pricing.snapshot.start", profile_id=profile["id"])
                    pricing = pricing_snapshot(client, args.max_news_cost_usd)
                    trace("pricing.snapshot.complete", profile_id=profile["id"])
                    write_json(profile_dir / "pricing-snapshot.json", pricing)
                    expected_targets = {
                        *resolved["components"].keys(), *resolved["validators"].keys(),
                    }
                    preflight_costs = collect_costs(
                        pricing, len(case["assertions"]), expected_targets,
                    )
                    write_json(profile_dir / "preflight-costs.json", preflight_costs)
                    normalized_cost = preflight_costs["normalized_5_assertions_total_usd"]
                    trace("pricing.preflight", profile_id=profile["id"], complete=preflight_costs["complete"], normalized_5_assertions_cost_usd=normalized_cost)
                    if (
                        args.max_news_cost_usd is not None
                        and (
                            not preflight_costs["complete"]
                            or normalized_cost is None
                            or normalized_cost > args.max_news_cost_usd
                        )
                    ):
                        raise BenchmarkError(
                            "La configuración actual no tiene coste verificable bajo "
                            f"max_news_cost_usd={args.max_news_cost_usd}"
                        )
                    for repetition in range(1, args.repetitions + 1):
                        run_id = f"{batch_id}-{profile['id']}-r{repetition:02d}"
                        run_dir = profile_dir / f"repetition-{repetition:02d}"
                        run_started = utc_now()
                        monotonic_start = time.monotonic()
                        run: dict[str, Any] = {
                            "schema_version": 1,
                            "run_id": run_id,
                            "batch_id": batch_id,
                            "profile_id": profile["id"],
                            "repetition": repetition,
                            "started_at": run_started,
                            "status": "RUNNING",
                            "resolved_profile": resolved,
                        }
                        try:
                            trace("repetition.start", run_id=run_id, profile_id=profile["id"], repetition=repetition)
                            if args.clear_evidence_cache:
                                trace("evidence_cache.clear.start", run_id=run_id)
                                run["evidence_cache_clear"] = clear_evidence_cache(
                                    args.evidence_search_url, verify_tls, args.http_timeout,
                                )
                                trace("evidence_cache.clear.complete", run_id=run_id, deleted_count=run["evidence_cache_clear"].get("deleted_count"))
                                monotonic_start = time.monotonic()
                            trace("order.publish.start", run_id=run_id)
                            published = client.post(
                                "/orders/publishNew",
                                {"text": case["news"], "validation_mode": "LIGHT"},
                            )
                            order_id = str(published.get("order_id") or "")
                            if not order_id:
                                raise BenchmarkError("publishNew no devolvió order_id")
                            run["order_id"] = order_id
                            trace("order.publish.complete", run_id=run_id, order_id=order_id)
                            trace("order.poll.start", run_id=run_id, order_id=order_id, timeout_seconds=args.result_timeout, interval_seconds=args.poll_interval)
                            order = wait_for_order(
                                client, order_id, args.result_timeout, args.poll_interval,
                                progress=lambda current, status, event: trace(
                                    "order.poll", run_id=run_id, order_id=order_id,
                                    status=status or "UNKNOWN", last_event=event,
                                ),
                            )
                            trace("order.terminal", run_id=run_id, order_id=order_id, status=order.get("status"))
                            write_json(run_dir / "order.json", order)
                            trace("score.start", run_id=run_id, order_id=order_id)
                            score = score_order(case, order)
                            costs = collect_costs(
                                pricing, len(collect_assertions(order)), expected_targets,
                            )
                            if args.require_costs and not costs["complete"]:
                                raise BenchmarkError("No se pudo calcular el coste completo")
                            run.update({"status": "PASS", "score": score, "costs": costs})
                            trace("score.complete", run_id=run_id, quality_score=score["quality_score"], generated_assertions=score["metrics"]["generated_assertions"])
                            write_json(run_dir / "score.json", score)
                            write_json(run_dir / "costs.json", costs)
                        except Exception as exc:
                            trace("repetition.failed", run_id=run_id, error=type(exc).__name__)
                            run.update({"status": "FAIL", "error": str(exc)})
                        run["finished_at"] = utc_now()
                        run["duration_seconds"] = round(time.monotonic() - monotonic_start, 6)
                        write_json(run_dir / "run.json", run)
                        history.save_run(run)
                        all_runs.append(run)
                        profile_runs.append(run)
                        print(
                            f"LLM_BENCHMARK_RUN {run['status']} run_id={run_id} "
                            f"order_id={run.get('order_id') or '-'}"
                        )
                        if run["status"] != "PASS" and args.stop_on_failure:
                            raise BenchmarkError(run.get("error") or f"Falló {run_id}")
                finally:
                    trace("configuration.restore.start", profile_id=profile["id"])
                    errors = manager.restore(initial_snapshot, manager.applied_targets)
                    trace("configuration.restore.complete", profile_id=profile["id"], errors=len(errors))
                    restore_errors.extend(errors)
                    write_json(profile_dir / "restore.json", {
                        "finished_at": utc_now(), "status": "PASS" if not errors else "FAIL",
                        "errors": errors,
                    })
                    if errors:
                        raise BenchmarkError("Falló la restauración: " + "; ".join(errors))
            batch_status = "PASS" if all_runs and all(run["status"] == "PASS" for run in all_runs) else "FAIL"
            trace("batch.complete", batch_id=batch_id, status=batch_status, runs=len(all_runs))
    except Exception as exc:
        manifest["runner_error"] = str(exc)
        trace("batch.failed", batch_id=batch_id, error=type(exc).__name__)
        print(f"LLM_BENCHMARK_ERROR {exc}", file=sys.stderr)
    finally:
        if initial_snapshot and restore_errors:
            manifest["restore_errors"] = restore_errors
        finished_at = utc_now()
        summaries = [
            profile_summary(profile_id, [run for run in all_runs if run["profile_id"] == profile_id])
            for profile_id in profile_ids
        ]
        summary = {
            "schema_version": 1,
            "batch_id": batch_id,
            "case_id": case["id"],
            "started_at": started_at,
            "finished_at": finished_at,
            "status": batch_status,
            "profiles": summaries,
            "runs": [
                {
                    "run_id": run["run_id"], "profile_id": run["profile_id"],
                    "repetition": run["repetition"], "status": run["status"],
                    "order_id": run.get("order_id"),
                }
                for run in all_runs
            ],
            "runner_error": manifest.get("runner_error"),
            "restore_errors": restore_errors,
        }
        manifest["finished_at"] = finished_at
        manifest["status"] = batch_status
        write_json(batch_dir / "manifest.json", manifest)
        write_json(batch_dir / "summary.json", summary)
        (batch_dir / "report.md").write_text(markdown_report(summary), encoding="utf-8")
        history.finish_batch(batch_id, batch_status, finished_at)
        history.close()
        print(f"LLM_BENCHMARK_REPORT {batch_dir / 'summary.json'}")
        print(f"LLM_BENCHMARK_RESULT {batch_status}")
    return 0 if batch_status == "PASS" else 1


def validate_profiles(args: argparse.Namespace) -> int:
    case = read_json(pathlib.Path(args.case).resolve())
    validate_case(case)
    for value in args.profile:
        profile = read_json(pathlib.Path(value).resolve())
        validate_profile(profile)
        print(f"VALID profile={profile['id']} path={pathlib.Path(value).resolve()}")
    print(f"VALID case={case['id']} assertions={len(case['assertions'])}")
    return 0


def list_runs(args: argparse.Namespace) -> int:
    history = History(pathlib.Path(args.database).resolve())
    try:
        rows = history.list_runs(args.limit)
    finally:
        history.close()
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def compare_runs(args: argparse.Namespace) -> int:
    history = History(pathlib.Path(args.database).resolve())
    try:
        result = comparison(history.get_run(args.baseline), history.get_run(args.candidate))
    finally:
        history.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Benchmark histórico de configuraciones LLM OpenRouter")
    commands = root.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate-profiles", help="Valida caso y perfiles sin acceder a la red")
    validate.add_argument("--case", default=str(DEFAULT_CASE))
    validate.add_argument("--profile", action="append", default=[])
    validate.set_defaults(func=validate_profiles)

    run = commands.add_parser("run", help="Ejecuta perfiles secuencialmente en modo LIGHT")
    run.add_argument("--case", default=str(DEFAULT_CASE))
    run.add_argument("--profile", action="append", default=[])
    run.add_argument("--profile-plan", help="plan.json creado por generate-profiles")
    run.add_argument("--repetitions", type=int, default=3)
    run.add_argument("--base-url", default=os.getenv("ASSERMETRY_API_URL", "https://localhost:7443/backend"))
    run.add_argument("--artifacts-root", default=str(DEFAULT_ARTIFACTS))
    run.add_argument("--database", default=str(DEFAULT_DATABASE))
    run.add_argument("--batch-id")
    run.add_argument("--result-timeout", type=float, default=600)
    run.add_argument("--poll-interval", type=float, default=2)
    run.add_argument("--http-timeout", type=float, default=30)
    run.add_argument("--max-news-cost-usd", type=float)
    run.add_argument("--require-costs", action="store_true")
    run.add_argument("--stop-on-failure", action="store_true")
    run.add_argument("--lock-file", default="/tmp/assermetry-llm-benchmark.lock")
    run.add_argument(
        "--clear-evidence-cache", action="store_true",
        help=(
            "Vacía evidence_search_cache_v2 antes de cada repetición para medir en frío; "
            "no modifica rutas ni perfiles de dominio"
        ),
    )
    run.add_argument(
        "--evidence-search-url",
        default=os.getenv("ASSERMETRY_EVIDENCE_SEARCH_URL", "http://localhost:8074"),
        help=(
            "URL directa de Evidence Search usada por --clear-evidence-cache "
            "(por defecto ASSERMETRY_EVIDENCE_SEARCH_URL o http://localhost:8074)"
        ),
    )
    run.add_argument(
        "--verify-tls", action=argparse.BooleanOptionalAction,
        default=os.getenv("ASSERMETRY_TLS_VERIFY", "false").lower() in {"1", "true", "yes"},
    )
    run.set_defaults(func=run_benchmark)

    generate = commands.add_parser(
        "generate-profiles",
        help="Genera perfiles OpenRouter completos bajo un coste máximo por noticia",
    )
    generate.add_argument("--max-news-cost-usd", type=float, required=True)
    generate.add_argument("--budget-headroom-percent", type=float, default=5.0)
    generate.add_argument("--output-root", default=str(DEFAULT_GENERATED_PLANS))
    generate.add_argument("--plan-id")
    generate.add_argument(
        "--base-url",
        default=os.getenv("ASSERMETRY_API_URL", "https://localhost:7443/backend"),
    )
    generate.add_argument("--http-timeout", type=float, default=30)
    generate.add_argument(
        "--verify-tls", action=argparse.BooleanOptionalAction,
        default=os.getenv("ASSERMETRY_TLS_VERIFY", "false").lower() in {"1", "true", "yes"},
    )
    generate.set_defaults(func=generate_profile_plan)

    listing = commands.add_parser("list-runs", help="Lista el histórico")
    listing.add_argument("--database", default=str(DEFAULT_DATABASE))
    listing.add_argument("--limit", type=int, default=20)
    listing.set_defaults(func=list_runs)

    compare_cmd = commands.add_parser("compare", help="Compara dos ejecuciones históricas")
    compare_cmd.add_argument("--database", default=str(DEFAULT_DATABASE))
    compare_cmd.add_argument("--baseline", required=True)
    compare_cmd.add_argument("--candidate", required=True)
    compare_cmd.set_defaults(func=compare_runs)
    return root


def main() -> int:
    args = parser().parse_args()
    if hasattr(args, "profile") and not args.profile and not getattr(args, "profile_plan", None):
        args.profile = [str(DEFAULT_PROFILE)]
    if getattr(args, "repetitions", 1) <= 0:
        raise BenchmarkError("--repetitions debe ser mayor que cero")
    if getattr(args, "max_news_cost_usd", None) is not None and args.max_news_cost_usd <= 0:
        raise BenchmarkError("--max-news-cost-usd debe ser mayor que cero")
    headroom = getattr(args, "budget_headroom_percent", 0)
    if headroom < 0 or headroom >= 100:
        raise BenchmarkError("--budget-headroom-percent debe estar entre 0 (incluido) y 100 (excluido)")
    return int(args.func(args))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BenchmarkError as exc:
        print(f"LLM_BENCHMARK_ERROR {exc}", file=sys.stderr)
        raise SystemExit(2)
