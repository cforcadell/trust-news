"""Canonical serialization and secret-free evaluation artifacts (stdlib only)."""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


class BenchmarkError(RuntimeError):
    pass


# Keep the historical exception name in benchmark diagnostic traces.
EvaluationError = BenchmarkError


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
