import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send


SECURITY_RELEVANT_STATUSES = {401, 403, 405, 413, 429}


class RequestSecurityMiddleware:
    """Limit HTTP request bodies and emit one structured access event per response."""

    def __init__(
        self,
        app: Callable[[Scope, Receive, Send], Awaitable[None]],
        *,
        max_request_body_bytes: int,
        logger: logging.Logger,
    ) -> None:
        if max_request_body_bytes <= 0:
            raise ValueError("max_request_body_bytes must be greater than zero")
        self.app = app
        self.max_request_body_bytes = max_request_body_bytes
        self.logger = logger

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started_at = time.monotonic()
        method = scope.get("method", "")
        path = scope.get("path", "")
        request_id = self._request_id(scope)
        content_length = self._content_length(scope)

        if content_length is not None and content_length > self.max_request_body_bytes:
            await self._reject_too_large(
                scope, receive, send, method, path, request_id, content_length, started_at
            )
            return

        buffered_messages: list[Message] = []
        body_bytes = 0
        while True:
            message = await receive()
            buffered_messages.append(message)
            if message["type"] != "http.request":
                break
            body_bytes += len(message.get("body", b""))
            if body_bytes > self.max_request_body_bytes:
                await self._reject_too_large(
                    scope, receive, send, method, path, request_id, body_bytes, started_at
                )
                return
            if not message.get("more_body", False):
                break

        message_index = 0

        async def replay_receive() -> Message:
            nonlocal message_index
            if message_index < len(buffered_messages):
                message = buffered_messages[message_index]
                message_index += 1
                return message
            return {"type": "http.request", "body": b"", "more_body": False}

        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                if not any(name.lower() == b"x-request-id" for name, _ in headers):
                    headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, replay_receive, send_with_request_id)
        except Exception:
            self._log_request(method, path, 500, request_id, body_bytes, started_at)
            raise

        self._log_request(method, path, status_code, request_id, body_bytes, started_at)

    async def _reject_too_large(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        method: str,
        path: str,
        request_id: str,
        body_bytes: int,
        started_at: float,
    ) -> None:
        response = JSONResponse(
            status_code=413,
            content={"detail": "Request body too large"},
            headers={"x-request-id": request_id},
        )
        await response(scope, receive, send)
        self._log_request(method, path, 413, request_id, body_bytes, started_at)

    @staticmethod
    def _content_length(scope: Scope) -> int | None:
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    parsed = int(value)
                    return parsed if parsed >= 0 else None
                except ValueError:
                    return None
        return None

    @staticmethod
    def _request_id(scope: Scope) -> str:
        for name, value in scope.get("headers", []):
            if name.lower() == b"x-request-id":
                candidate = value.decode("ascii", errors="ignore")[:128]
                if candidate and all(char.isalnum() or char in "-_." for char in candidate):
                    return candidate
        return str(uuid.uuid4())

    def _log_request(
        self,
        method: str,
        path: str,
        status_code: int,
        request_id: str,
        body_bytes: int,
        started_at: float,
    ) -> None:
        event: dict[str, Any] = {
            "event": "gateway_access",
            "request_id": request_id,
            "method": method,
            "path": path,
            "status": status_code,
            "body_bytes": body_bytes,
            "duration_ms": round((time.monotonic() - started_at) * 1000, 2),
        }
        serialized = json.dumps(event, separators=(",", ":"), sort_keys=True)
        if status_code >= 500:
            self.logger.error(serialized)
        elif status_code in SECURITY_RELEVANT_STATUSES:
            self.logger.warning(serialized)
        else:
            self.logger.info(serialized)
