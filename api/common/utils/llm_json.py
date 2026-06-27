import json
import re
from typing import Any, List, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import BaseModel


def strip_json_markdown(text: str) -> str:
    value = (text or "").strip()
    value = re.sub(r"^```(?:json)?", "", value, flags=re.IGNORECASE).strip()
    if value.endswith("```"):
        value = value[:-3].strip()
    return value


def _extract_balanced_json(text: str) -> str:
    value = strip_json_markdown(text)
    start_positions = [idx for idx, char in enumerate(value) if char in "[{"]
    if not start_positions:
        return value

    for start in start_positions:
        stack: list[str] = []
        in_string = False
        escape = False
        for idx in range(start, len(value)):
            char = value[idx]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char in "[{":
                stack.append("}" if char == "{" else "]")
            elif char in "}]":
                if not stack or stack[-1] != char:
                    break
                stack.pop()
                if not stack:
                    return value[start:idx + 1].strip()
    return value


def _remove_trailing_commas(text: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", text)


def _load_json_lenient(content: str) -> Any:
    candidate = _extract_balanced_json(content)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        repaired = _remove_trailing_commas(candidate)
        if repaired != candidate:
            return json.loads(repaired)
        raise


def parse_json_content(content: Any) -> Any:
    if isinstance(content, (list, dict)):
        return content
    if not isinstance(content, str):
        raise ValueError(f"Tipo de contenido inesperado: {type(content)}")
    try:
        return json.loads(strip_json_markdown(content))
    except json.JSONDecodeError:
        return _load_json_lenient(content)


def extract_chat_content(data: dict) -> str:
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Estructura de respuesta chat inesperada.") from exc


def _find_list_by_key(value: Any, list_key: str) -> list | None:
    if not isinstance(value, dict):
        return None
    if list_key in value and isinstance(value[list_key], list):
        return value[list_key]

    normalized_key = list_key.casefold()
    for key, item in value.items():
        if str(key).casefold() == normalized_key and isinstance(item, list):
            return item

    for item in value.values():
        found = _find_list_by_key(item, list_key)
        if found is not None:
            return found
    return None


def _looks_like_model_item(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    keys = {str(key) for key in value}
    text_keys = {"text", "texto", "claim", "assertion", "assertion_text"}
    category_keys = {"categoryId", "category_id", "category"}
    return bool(keys & text_keys) and bool(keys & category_keys)


def _list_from_object_map(value: dict) -> list | None:
    object_values = [item for item in value.values() if isinstance(item, dict)]
    if object_values and len(object_values) == len(value) and all(_looks_like_model_item(item) for item in object_values):
        return object_values
    return None


def summarize_json_shape(raw: Any) -> str:
    try:
        parsed = parse_json_content(raw)
    except Exception as exc:
        return f"unparseable:{exc.__class__.__name__}"
    if isinstance(parsed, list):
        return f"list(len={len(parsed)})"
    if isinstance(parsed, dict):
        keys = list(parsed.keys())[:12]
        types = {str(key): type(value).__name__ for key, value in list(parsed.items())[:8]}
        return f"object(keys={keys}, types={types})"
    return type(parsed).__name__


def coerce_list(raw: Any, list_key: str | None = None) -> list:
    parsed = parse_json_content(raw)
    if isinstance(parsed, dict):
        if list_key:
            found = _find_list_by_key(parsed, list_key)
            if found is not None:
                return found

        list_aliases = ("assertions", "assertion", "aserciones", "asercion", "claims", "items", "results", "data", "output")
        for alias in list_aliases:
            found = _find_list_by_key(parsed, alias)
            if found is not None:
                return found

        for alias in list_aliases:
            value = parsed.get(alias)
            if isinstance(value, dict) and _looks_like_model_item(value):
                return [value]

        list_values = [item for item in parsed.values() if isinstance(item, list)]
        if len(list_values) == 1:
            return list_values[0]

        mapped_values = _list_from_object_map(parsed)
        if mapped_values is not None:
            return mapped_values

        if _looks_like_model_item(parsed):
            return [parsed]

    if not isinstance(parsed, list):
        raise ValueError("El resultado no es una lista JSON.")
    return parsed


def assign_sequential_ids(items: list, field: str = "idAssertion") -> list:
    normalized = []
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError("La lista contiene elementos que no son objetos JSON.")
        copied = dict(item)
        copied[field] = str(idx)
        normalized.append(copied)
    return normalized


def parse_model_list(raw: Any, model: Type["BaseModel"], list_key: str | None = None, id_field: str | None = None) -> List["BaseModel"]:
    items = coerce_list(raw, list_key=list_key)
    if id_field:
        items = assign_sequential_ids(items, field=id_field)
    return [model(**item) for item in items]
