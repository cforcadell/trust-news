import json
from typing import Any, TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError

from common.utils.llm_json import strip_json_markdown

from .errors import LLMResponseError

T = TypeVar("T")


def parse_structured_json(content: str, schema: type[T] | TypeAdapter[T] | None = None) -> T | Any:
    try:
        value = json.loads(strip_json_markdown(content))
        if schema is None:
            return value
        adapter = schema if isinstance(schema, TypeAdapter) else TypeAdapter(schema)
        return adapter.validate_python(value)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        raise LLMResponseError(f"Invalid structured LLM response: {exc}") from exc
