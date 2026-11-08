"""Bounded HTTP retrieval of untrusted public URLs.

The resolver is part of the connector, so a validated DNS answer is the
answer used by the socket. This module must not be used for internal APIs.
"""

import asyncio
import ipaddress
import socket
import ssl
import zlib
from dataclasses import dataclass, field
from typing import Mapping, Optional
from urllib.parse import urljoin, urlsplit

import aiohttp


REDIRECTS = {301, 302, 303, 307, 308}
FORBIDDEN_HEADERS = {"host", "connection", "transfer-encoding", "proxy-authorization"}


class FetchError(Exception):
    def __init__(self, code: str, *, status: Optional[int] = None, received: int = 0):
        super().__init__(code)
        self.code = code
        self.status = status
        self.received = received


@dataclass(frozen=True)
class FetchPolicy:
    ports: tuple[int, ...] = (80, 443)
    deny_cidrs: tuple[str, ...] = ()
    max_redirects: int = 5
    max_attempts: int = 1
    timeout_seconds: float = 15.0
    connect_timeout_seconds: float = 10.0
    max_bytes: int = 4 * 1024 * 1024
    pdf_max_bytes: Optional[int] = None
    retry_delay_seconds: float = 0.0

    def __post_init__(self):
        if (not self.ports or any(not 1 <= port <= 65535 for port in self.ports)
                or self.max_redirects < 0 or self.max_attempts < 1
                or self.timeout_seconds <= 0 or self.connect_timeout_seconds <= 0
                or self.max_bytes < 1 or (self.pdf_max_bytes is not None and self.pdf_max_bytes < 1)
                or self.retry_delay_seconds < 0):
            raise ValueError("invalid public fetch policy")
        object.__setattr__(self, "deny_cidrs", tuple(ipaddress.ip_network(value) for value in self.deny_cidrs))


@dataclass(frozen=True)
class FetchResponse:
    url: str
    status: int
    headers: Mapping[str, str]
    body: bytes
    attempted_urls: tuple[str, ...] = field(default_factory=tuple)
    redirects: tuple[dict, ...] = field(default_factory=tuple)


def _address_allowed(value: str, policy: FetchPolicy) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return (address.is_global and not address.is_reserved and not address.is_multicast
            and not any(address in network for network in policy.deny_cidrs))


def _destination(url: str, policy: FetchPolicy) -> tuple[str, int, str]:
    try:
        parsed = urlsplit(url)
        if (parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.fragment or "\\" in url or any(ord(char) < 32 for char in url)):
            raise ValueError("invalid URL")
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        host = parsed.hostname.encode("idna").decode("ascii").rstrip(".").lower()
        default_port = 443 if parsed.scheme.lower() == "https" else 80
        if not host or port not in policy.ports or (port in (80, 443) and port != default_port):
            raise FetchError("UNSAFE_PORT" if port not in policy.ports else "UNSAFE_TARGET")
        # aiohttp can identify IP literals itself and skip its resolver.
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if host.replace(".", "").isdigit() or ":" in host or "%" in host:
                raise FetchError("UNSAFE_TARGET")
        else:
            if not _address_allowed(host, policy):
                raise FetchError("UNSAFE_TARGET")
        return host, port, parsed.scheme.lower()
    except FetchError:
        raise
    except (ValueError, UnicodeError):
        raise FetchError("INVALID_URL") from None


class _PolicyResolver(aiohttp.abc.AbstractResolver):
    def __init__(self, policy: FetchPolicy):
        self.policy = policy

    async def resolve(self, host: str, port: int, family: int = socket.AF_UNSPEC):
        loop = asyncio.get_running_loop()
        try:
            records = await loop.getaddrinfo(host, port, family=family, type=socket.SOCK_STREAM)
        except OSError:
            raise FetchError("DNS_FAILURE") from None
        addresses = {record[4][0] for record in records}
        if not addresses or any(not _address_allowed(value, self.policy) for value in addresses):
            raise FetchError("UNSAFE_TARGET")
        return [{"hostname": host, "host": record[4][0], "port": port,
                 "family": record[0], "proto": record[2], "flags": 0} for record in records]

    async def close(self):
        pass


def _decode_chunk(decoder, chunk: bytes, limit: int) -> bytes:
    if decoder is None:
        return chunk
    try:
        part = decoder.decompress(chunk, limit + 1)
        if decoder.unconsumed_tail:
            raise FetchError("TOO_LARGE")
        return part
    except zlib.error:
        raise FetchError("INVALID_ENCODING") from None


async def _read_body(response: aiohttp.ClientResponse, policy: FetchPolicy) -> bytes:
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower().strip()
    unknown_format = content_type in {"", "application/octet-stream"}
    limit = policy.pdf_max_bytes if content_type in {"application/pdf", "application/x-pdf"} and policy.pdf_max_bytes else policy.max_bytes
    declared = response.headers.get("Content-Length", "")
    if declared.isdecimal() and int(declared) > (policy.pdf_max_bytes or limit if unknown_format else limit):
        raise FetchError("TOO_LARGE", status=response.status)
    encoding = response.headers.get("Content-Encoding", "identity").lower().strip()
    if encoding in {"", "identity"}:
        decoder = None
    elif encoding == "gzip":
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    elif encoding == "deflate":
        decoder = zlib.decompressobj()
    else:
        raise FetchError("UNSUPPORTED_ENCODING", status=response.status)
    chunks = []
    wire_bytes = decoded_bytes = 0
    async for chunk in response.content.iter_chunked(65536):
        wire_bytes += len(chunk)
        # Unknown content types may be PDFs. Inspect the first decoded bytes
        # before selecting the larger PDF allowance.
        provisional_limit = policy.pdf_max_bytes or limit if unknown_format and not chunks else limit
        part = _decode_chunk(decoder, chunk, provisional_limit - decoded_bytes)
        if unknown_format and not chunks and part.lstrip().startswith(b"%PDF-") and policy.pdf_max_bytes:
            limit = policy.pdf_max_bytes
        if declared.isdecimal() and int(declared) > limit:
            raise FetchError("TOO_LARGE", status=response.status)
        if wire_bytes > limit:
            raise FetchError("TOO_LARGE", status=response.status, received=wire_bytes)
        decoded_bytes += len(part)
        if decoded_bytes > limit:
            raise FetchError("TOO_LARGE", status=response.status, received=decoded_bytes)
        chunks.append(part)
    if decoder is not None:
        try:
            tail = decoder.flush(limit - decoded_bytes + 1)
        except zlib.error:
            raise FetchError("INVALID_ENCODING", status=response.status) from None
        if not decoder.eof or decoded_bytes + len(tail) > limit:
            raise FetchError("INVALID_ENCODING" if not decoder.eof else "TOO_LARGE", status=response.status)
        chunks.append(tail)
    return b"".join(chunks)


async def fetch(url: str, policy: FetchPolicy, headers: Optional[Mapping[str, str]] = None) -> FetchResponse:
    headers = dict(headers or {})
    if any(key.lower() in FORBIDDEN_HEADERS or key.lower().startswith("proxy-") for key in headers):
        raise FetchError("INVALID_HEADERS")
    headers.setdefault("Accept-Encoding", "gzip, deflate")
    deadline = asyncio.get_running_loop().time() + policy.timeout_seconds
    attempted = []
    redirects_seen = []
    current = url
    try:
        async with asyncio.timeout_at(deadline):
            for attempt in range(policy.max_attempts):
                current = url
                visited = set()
                for redirect_count in range(policy.max_redirects + 1):
                    _, _, scheme = _destination(current, policy)
                    if current in visited:
                        raise FetchError("REDIRECT_LOOP")
                    visited.add(current)
                    attempted.append(current)
                    remaining = max(0.001, deadline - asyncio.get_running_loop().time())
                    timeout = aiohttp.ClientTimeout(total=remaining, connect=min(policy.connect_timeout_seconds, remaining))
                    connector = aiohttp.TCPConnector(resolver=_PolicyResolver(policy), use_dns_cache=False,
                                                     force_close=True, ssl=ssl.create_default_context())
                    try:
                        async with aiohttp.ClientSession(connector=connector, trust_env=False,
                                                         auto_decompress=False, timeout=timeout) as session:
                            async with session.get(current, headers=headers, allow_redirects=False) as response:
                                if response.status in REDIRECTS:
                                    location = response.headers.get("Location")
                                    if not location:
                                        raise FetchError("REDIRECT_MISSING_LOCATION", status=response.status)
                                    if redirect_count >= policy.max_redirects:
                                        raise FetchError("REDIRECT_LIMIT_EXCEEDED", status=response.status)
                                    target = urljoin(current, location)
                                    _destination(target, policy)
                                    if scheme == "https" and urlsplit(target).scheme.lower() != "https":
                                        raise FetchError("REDIRECT_HTTPS_DOWNGRADE", status=response.status)
                                    redirects_seen.append({"url": current, "http_status": response.status,
                                                           "redirect_to": target, "outcome": "HTTP_REDIRECT"})
                                    current = target
                                    continue
                                body = b"" if response.status >= 400 else await _read_body(response, policy)
                                return FetchResponse(str(response.url), response.status, response.headers, body,
                                                     tuple(attempted), tuple(redirects_seen))
                    except (aiohttp.ClientConnectorCertificateError, aiohttp.ClientSSLError) as exc:
                        message = str(exc).lower()
                        code = "TLS_HOSTNAME_MISMATCH" if ("hostname mismatch" in message or "not valid for" in message) else "TLS_INVALID"
                        raise FetchError(code) from exc
                    except asyncio.TimeoutError:
                        if attempt + 1 >= policy.max_attempts:
                            raise FetchError("TIME_BUDGET") from None
                        break
                    except (aiohttp.ClientError, OSError) as exc:
                        if attempt + 1 >= policy.max_attempts:
                            raise FetchError("NETWORK_ERROR") from exc
                        break
                if policy.retry_delay_seconds:
                    await asyncio.sleep(policy.retry_delay_seconds)
    except TimeoutError:
        raise FetchError("TIME_BUDGET") from None
    raise FetchError("NETWORK_ERROR")


def fetch_sync(url: str, policy: FetchPolicy, headers: Optional[Mapping[str, str]] = None) -> FetchResponse:
    """For synchronous FastAPI endpoints, which run in a worker thread."""
    return asyncio.run(fetch(url, policy, headers))
