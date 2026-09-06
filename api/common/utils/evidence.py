from typing import Any, Dict
from urllib.parse import urlparse

from pydantic import BeforeValidator, HttpUrl, TypeAdapter, ValidationError
from typing_extensions import Annotated


_http_url = TypeAdapter(HttpUrl)


def is_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    value = value.strip()
    # Reject characters that URL parsers may silently remove or reinterpret.
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 or char == "\\" for char in value):
        return False
    try:
        parsed = urlparse(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return False
        _http_url.validate_python(value)
    except (ValueError, ValidationError):
        return False
    return True


def sanitize_evidence_item(value: Any) -> Any:
    if not isinstance(value, dict):
        return value

    item = dict(value)
    for key in ("url", "source_url"):
        if key in item and item[key] not in (None, "") and not is_http_url(item[key]):
            # Preserve the original for display without making it navigable.
            if isinstance(item[key], str):
                item[f"{key}_text"] = item[key]
            item.pop(key)
    return item


EvidenceItem = Annotated[Dict[str, Any], BeforeValidator(sanitize_evidence_item)]
