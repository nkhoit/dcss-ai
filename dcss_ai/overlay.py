#!/usr/bin/env python3
"""SSE server for streaming game state and monologue to the overlay.

Replaces file-based IPC (stats.json, monologue.jsonl) with a push model.
The overlay connects once via EventSource and receives live updates.

Events:
  stats   — full game state (JSON), sent on every update_overlay() call
  thought — single monologue entry (JSON {ts, text}), sent on write_monologue()
  reset   — session reset, overlay should clear feed
"""

import asyncio
import json
import logging
import os
import time
from asyncio import Queue
from typing import Set

logger = logging.getLogger("dcss_ai.overlay")

# Global event bus — overlay server reads, game/provider write
_clients: Set[Queue] = set()


def broadcast(event: str, data: dict) -> None:
    """Send an SSE event to all connected clients. Non-blocking."""
    msg = f"event: {event}\ndata: {json.dumps(data)}\n\n"
    dead = []
    for q in _clients:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _clients.discard(q)


def send_stats(stats: dict) -> None:
    """Push a stats update to all connected overlays."""
    broadcast("stats", stats)


def send_thought(text: str) -> None:
    """Push a monologue thought to all connected overlays."""
    text = text.strip()
    if not text:
        return
    broadcast("thought", {"ts": time.time(), "text": text})


def send_reset() -> None:
    """Tell overlays to clear their feed (new session)."""
    broadcast("reset", {})


async def _handle_sse(reader, writer):
    """Handle a single SSE client connection."""
    # Read HTTP request
    request_line = await reader.readline()
    # Read remaining headers
    while True:
        line = await reader.readline()
        if line == b"\r\n" or line == b"\n" or not line:
            break

    path = request_line.decode().split(" ")[1] if request_line else "/"

    if path == "/events":
        # SSE response
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/event-stream\r\n"
            b"Cache-Control: no-cache\r\n"
            b"Access-Control-Allow-Origin: *\r\n"
            b"Connection: keep-alive\r\n"
            b"\r\n"
        )
        await writer.drain()

        q: Queue = Queue(maxsize=100)
        _clients.add(q)
        logger.info(f"SSE client connected ({len(_clients)} total)")
        try:
            # Send keepalive comment every 15s to prevent timeout
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    writer.write(msg.encode())
                    await writer.drain()
                except asyncio.TimeoutError:
                    writer.write(b": keepalive\n\n")
                    await writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass
        finally:
            _clients.discard(q)
            logger.info(f"SSE client disconnected ({len(_clients)} total)")
            writer.close()
    elif path == "/" or path.startswith("/stream") or path.startswith("/overlay"):
        # Serve static files from dcss-stream directory
        static_dir = os.environ.get("DCSS_STREAM_DIR", os.path.expanduser("~/code/dcss-stream"))
        filename = "stream.html" if path in ("/", "/stream") else path.lstrip("/")
        filepath = os.path.join(static_dir, filename)
        try:
            with open(filepath, "rb") as f:
                body = f.read()
            ct = "text/html" if filepath.endswith(".html") else "application/octet-stream"
            writer.write(f"HTTP/1.1 200 OK\r\nContent-Type: {ct}\r\nContent-Length: {len(body)}\r\nAccess-Control-Allow-Origin: *\r\n\r\n".encode())
            writer.write(body)
        except FileNotFoundError:
            writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        writer.close()
    else:
        writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        writer.close()


async def start_server(port: int = 8889) -> asyncio.AbstractServer:
    """Start the SSE server. Returns the server handle."""
    server = await asyncio.start_server(_handle_sse, "0.0.0.0", port)
    logger.info(f"Overlay SSE server listening on :{port}")
    return server
