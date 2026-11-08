import asyncio
import ssl
import socket
import subprocess
import zlib
from types import SimpleNamespace

import pytest

from common.utils import public_fetch


@pytest.mark.asyncio
async def test_rejects_private_literals_and_ambiguous_ports():
    policy = public_fetch.FetchPolicy(timeout_seconds=0.1)
    for url in ("http://127.0.0.1/", "https://[::1]/", "http://169.254.169.254/",
                "http://10.0.0.1/", "http://public.example:443/"):
        with pytest.raises(public_fetch.FetchError):
            await public_fetch.fetch(url, policy)


@pytest.mark.asyncio
async def test_resolver_rejects_mixed_dns(monkeypatch):
    async def records(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 80))]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", records)
    with pytest.raises(public_fetch.FetchError, match="UNSAFE_TARGET"):
        await public_fetch._PolicyResolver(public_fetch.FetchPolicy()).resolve("public.example", 80)


@pytest.mark.asyncio
async def test_connector_rechecks_each_dns_answer_without_cache(monkeypatch):
    answers = ["93.184.216.34", "127.0.0.1"]

    async def records(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (answers.pop(0), 443))]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", records)
    connector = public_fetch.aiohttp.TCPConnector(
        resolver=public_fetch._PolicyResolver(public_fetch.FetchPolicy()),
        use_dns_cache=False,
    )
    try:
        first = await connector._resolve_host("public.example", 443)
        assert first[0]["host"] == "93.184.216.34"
        with pytest.raises(public_fetch.FetchError, match="UNSAFE_TARGET"):
            await connector._resolve_host("public.example", 443)
    finally:
        await connector.close()


@pytest.mark.asyncio
async def test_connector_receives_policy_resolver_and_disables_dns_cache(monkeypatch):
    recorded = {}

    class StopBeforeNetwork(Exception):
        pass

    def connector(**kwargs):
        recorded.update(kwargs)
        raise StopBeforeNetwork

    monkeypatch.setattr(public_fetch.aiohttp, "TCPConnector", connector)
    with pytest.raises(StopBeforeNetwork):
        await public_fetch.fetch("https://public.example/report", public_fetch.FetchPolicy())
    assert isinstance(recorded["resolver"], public_fetch._PolicyResolver)
    assert recorded["use_dns_cache"] is False
    assert recorded["force_close"] is True


@pytest.mark.asyncio
async def test_decompressed_body_is_bounded():
    payload = zlib.compress(b"x" * 2000)

    class Stream:
        async def iter_chunked(self, size):
            yield payload

    response = SimpleNamespace(
        headers={"Content-Encoding": "deflate", "Content-Type": "text/plain"},
        status=200, content=Stream(),
    )
    with pytest.raises(public_fetch.FetchError, match="TOO_LARGE"):
        await public_fetch._read_body(response, public_fetch.FetchPolicy(max_bytes=1000))


@pytest.mark.asyncio
async def test_pdf_signature_gets_pdf_limit_without_content_type():
    class Stream:
        async def iter_chunked(self, size):
            yield b"%PDF-" + b"x" * 1500

    response = SimpleNamespace(headers={"Content-Type": "application/octet-stream"},
                               status=200, content=Stream())
    body = await public_fetch._read_body(response, public_fetch.FetchPolicy(max_bytes=1000, pdf_max_bytes=2000))
    assert len(body) == 1505


@pytest.mark.asyncio
async def test_redirect_to_private_address_is_rejected_before_second_request(monkeypatch):
    requested = []

    class Response:
        status = 302
        headers = {"Location": "http://127.0.0.1/private"}
        url = "http://public.example/start"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Session:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def get(self, url, **kwargs):
            requested.append(url)
            return Response()

    monkeypatch.setattr(public_fetch.aiohttp, "TCPConnector", lambda **kwargs: object())
    monkeypatch.setattr(public_fetch.aiohttp, "ClientSession", Session)
    with pytest.raises(public_fetch.FetchError, match="UNSAFE_TARGET"):
        await public_fetch.fetch("http://public.example/start", public_fetch.FetchPolicy())
    assert requested == ["http://public.example/start"]


@pytest.mark.asyncio
async def test_total_budget_covers_request_and_prevents_late_retry(monkeypatch):
    requests = []

    class Response:
        status = 204
        headers = {}
        url = "http://public.example/slow"

        async def __aenter__(self):
            await asyncio.sleep(0.2)
            return self

        async def __aexit__(self, *args):
            pass

    class Session:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def get(self, url, **kwargs):
            requests.append(url)
            return Response()

    monkeypatch.setattr(public_fetch.aiohttp, "TCPConnector", lambda **kwargs: object())
    monkeypatch.setattr(public_fetch.aiohttp, "ClientSession", Session)
    with pytest.raises(public_fetch.FetchError, match="TIME_BUDGET"):
        await public_fetch.fetch(
            "http://public.example/slow",
            public_fetch.FetchPolicy(max_attempts=3, timeout_seconds=0.03),
        )
    assert requests == ["http://public.example/slow"]


@pytest.mark.asyncio
async def test_tls_uses_url_hostname_for_sni_and_certificate_verification(monkeypatch, tmp_path):
    cert = tmp_path / "server.pem"
    key = tmp_path / "server.key"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
         "-out", str(cert), "-days", "1", "-subj", "/CN=sni.example.test",
         "-addext", "subjectAltName=DNS:sni.example.test"],
        check=True, capture_output=True,
    )
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certfile=str(cert), keyfile=str(key))
    observed_sni = []
    server_context.set_servername_callback(lambda _ssl, name, _ctx: observed_sni.append(name))
    client_context = ssl.create_default_context(cafile=str(cert))
    assert client_context.check_hostname is True

    async def handler(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handler, "127.0.0.1", 0, ssl=server_context)
    port = server.sockets[0].getsockname()[1]
    original_getaddrinfo = asyncio.BaseEventLoop.getaddrinfo

    async def local_resolution(_loop, host, requested_port, **kwargs):
        assert host == "sni.example.test"
        assert requested_port == port
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", local_resolution)
    monkeypatch.setattr(public_fetch, "_address_allowed", lambda _value, _policy: True)
    monkeypatch.setattr(public_fetch.ssl, "create_default_context", lambda: client_context)
    try:
        result = await public_fetch.fetch(
            f"https://sni.example.test:{port}/resource",
            public_fetch.FetchPolicy(ports=(port,), timeout_seconds=2),
        )
        assert result.body == b"ok"
        assert observed_sni == ["sni.example.test"]
    finally:
        server.close()
        await server.wait_closed()
        monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", original_getaddrinfo)
