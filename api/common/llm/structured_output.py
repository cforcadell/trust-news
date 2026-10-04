import json
from typing import Any, TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError

from common.utils.llm_json import strip_json_markdown

from .errors import LLMResponseError

T = TypeVar("T")


def parse_structured_json(content: str, schema: type[T] | TypeAdapter[T] | None = None) -> T | Any:
    try:
        value = json.loads(strip_json_markdown(content))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise LLMResponseError(f"Invalid structured LLM response: {exc}") from exc
    if schema is None:
        return value
    adapter = schema if isinstance(schema, TypeAdapter) else TypeAdapter(schema)
    try:
        return adapter.validate_python(value)
    except ValidationError as exc:
        details = []
        for error in exc.errors(include_url=False, include_context=False, include_input=False):
            location = ".".join(str(part) for part in error.get("loc") or ()) or "response"
            details.append(f"{location}: {error.get('msg', 'Schema validation failed')}")
        raise LLMResponseError(
            f"Invalid structured LLM response ({len(details)} validation errors): " + "; ".join(details)
        ) from exc
