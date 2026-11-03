"""Canonical serialization and secret-free evaluation artifacts (stdlib only)."""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


class BenchmarkError(RuntimeError):
    pass


# Keep the historical exception name in benchmark diagnostic traces.
EvaluationError = BenchmarkError


_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|apikey|password|secret|authorization|access[_-]?token|refresh[_-]?token)"
    r"(\s*[=:]\s*)([^\s,;]+)"
)
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_JWT_TOKEN = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")


def safe_error_text(value: Any, *, limit: int = 500) -> str:
    """Return a concise diagnostic suitable for traces and persisted artifacts."""
    text = " ".join(str(value).replace("\r", " ").replace("\n", " ").split())
    text = _BEARER_TOKEN.sub("Bearer [REDACTED]", text)
    text = _JWT_TOKEN.sub("[REDACTED_JWT]", text)
    text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)
    if len(text) > limit:
        text = text[:limit - 1].rstrip() + "…"
    return text


def order_failure_details(exc: Exception, order_id: str | None = None, *, timeout_seconds=None) -> dict:
    """Classify a publish/poll failure without retaining response bodies or secrets."""
    reason = safe_error_text(exc)
    lowered = reason.lower()
    status_code = getattr(exc, "status", None)
    if "token de keycloak" in lowered or "keycloak no devolvió access_token" in lowered:
        stage, diagnostic_code = "AUTHENTICATION", "AUTHENTICATION_ERROR"
    elif "define assermetry_access_token" in lowered:
        stage, diagnostic_code = "AUTHENTICATION", "AUTHENTICATION_CONFIGURATION_ERROR"
    elif order_id and lowered.startswith("timeout esperando la orden"):
        stage, diagnostic_code = "ORDER_POLL", "ORDER_TIMEOUT"
    elif order_id and "terminó en" in lowered:
        stage, diagnostic_code = "ORDER_POLL", "ORDER_TERMINAL_FAILURE"
    elif order_id:
        stage, diagnostic_code = "ORDER_POLL", "ORDER_POLL_ERROR"
    elif "publishnew did not return order_id" in lowered:
        stage, diagnostic_code = "ORDER_PUBLISH", "INVALID_PUBLISH_RESPONSE"
    elif status_code is not None:
        stage, diagnostic_code = "ORDER_PUBLISH", "PUBLISH_HTTP_ERROR"
        # ApiError may contain an upstream response body. The status is enough to act on.
        reason = f"HTTP {status_code} al publicar la orden"
    elif "error de red" in lowered:
        stage, diagnostic_code = "ORDER_PUBLISH", "PUBLISH_NETWORK_ERROR"
    else:
        stage, diagnostic_code = "ORDER_PUBLISH", "ORDER_PUBLISH_ERROR"
    detail = {"stage": stage, "code": "TECHNICAL_ERROR", "diagnostic_code": diagnostic_code,
              "exception_type": type(exc).__name__, "reason": reason}
    if status_code is not None:
        detail["status_code"] = status_code
    if diagnostic_code == "ORDER_TIMEOUT" and timeout_seconds is not None:
        detail["timeout_seconds"] = timeout_seconds
    return detail


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvaluationError(f"Cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise EvaluationError(f"Expected JSON object: {path}")
    return value


def redact(value: Any) -> Any:
    """Strip credential fields; never export provider responses or exception bodies."""
    if isinstance(value, dict):
        return {
            key: redact(item) for key, item in value.items()
            if not any(word in str(key).lower() for word in
                       ("api_key", "apikey", "password", "secret", "authorization", "private_key", "access_token", "refresh_token"))
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def write_json(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(redact(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(text)
            handle.flush()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
