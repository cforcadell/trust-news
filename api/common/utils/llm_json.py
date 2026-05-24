import json
import re
from typing import Any, List, Type

from pydantic import BaseModel


def strip_json_markdown(text: str) -> str:
    value = (text or "").strip()
    value = re.sub(r"^```(?:json)?", "", value, flags=re.IGNORECASE).strip()
    if value.endswith("```"):
        value = value[:-3].strip()
    return value


def parse_json_content(content: Any) -> Any:
    if isinstance(content, (list, dict)):
        return content
    if not isinstance(content, str):
        raise ValueError(f"Tipo de contenido inesperado: {type(content)}")
    return json.loads(strip_json_markdown(content))


def extract_chat_content(data: dict) -> str:
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Estructura de respuesta chat inesperada.") from exc


def coerce_list(raw: Any, list_key: str | None = None) -> list:
    parsed = parse_json_content(raw)
    if isinstance(parsed, dict) and list_key and list_key in parsed:
        parsed = parsed[list_key]
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


def parse_model_list(raw: Any, model: Type[BaseModel], list_key: str | None = None, id_field: str | None = None) -> List[BaseModel]:
    items = coerce_list(raw, list_key=list_key)
    if id_field:
        items = assign_sequential_ids(items, field=id_field)
    return [model(**item) for item in items]
