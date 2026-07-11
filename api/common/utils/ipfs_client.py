import ast
import json
from typing import Any, Dict, Optional

import httpx
import requests


def _join(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


async def upload_bytes_to_ipfs(ipfs_api_url: str, filename: str, content: bytes, timeout: float = 30.0) -> str:
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            _join(ipfs_api_url, "/ipfs/upload"),
            data={"filename": filename, "content_bytes": content},
        )
    response.raise_for_status()
    return response.json()["cid"]


async def upload_json_to_ipfs(ipfs_api_url: str, filename: str, payload: Dict[str, Any], timeout: float = 30.0) -> str:
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return await upload_bytes_to_ipfs(ipfs_api_url, filename, content, timeout=timeout)


def get_ipfs_text(ipfs_api_url: str, cid: str, timeout: float = 10.0) -> Optional[str]:
    response = requests.get(_join(ipfs_api_url, f"/ipfs/{cid}"), timeout=timeout)
    response.raise_for_status()
    return response.text


def unwrap_ipfs_content(raw: str) -> Any:
    parsed = json.loads(raw)
    content = parsed.get("content") if isinstance(parsed, dict) else None
    if isinstance(content, str):
        if content.startswith("b'") or content.startswith('b"'):
            content = ast.literal_eval(content).decode("utf-8")
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return content
    return parsed


def get_ipfs_json(ipfs_api_url: str, cid: str, timeout: float = 10.0) -> Optional[Any]:
    raw = get_ipfs_text(ipfs_api_url, cid, timeout=timeout)
    if not raw:
        return None
    return unwrap_ipfs_content(raw)
