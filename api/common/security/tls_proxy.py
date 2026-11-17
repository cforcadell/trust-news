"""Small TLS listener forwarding bytes to an HTTP server in the same pod.

The application keeps its existing localhost HTTP port for probes and legacy
workers while sensitive service-to-service calls use the TLS Service port.
"""

from __future__ import annotations

import asyncio
import os
import ssl


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while chunk := await reader.read(65536):
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, OSError):
        pass


async def forward(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        target_reader, target_writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", int(os.environ["S03_PROXY_TARGET_PORT"])), timeout=5,
        )
        tasks = [asyncio.create_task(pipe(reader, target_writer)), asyncio.create_task(pipe(target_reader, writer))]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()
        target_writer.close()
        await target_writer.wait_closed()
    except (ConnectionError, OSError, asyncio.TimeoutError):
        pass
    finally:
        writer.close()
        await writer.wait_closed()


async def main() -> None:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(os.environ["S03_TLS_CERT_FILE"], os.environ["S03_TLS_KEY_FILE"])
    server = await asyncio.start_server(forward, "0.0.0.0", int(os.getenv("S03_PROXY_LISTEN_PORT", "9443")), ssl=context)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
