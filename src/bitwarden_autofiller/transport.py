"""Length-prefixed JSON transport for the optional client/daemon mode."""

from __future__ import annotations

import json
import socket
import struct
from typing import Any

MAX_FRAME_SIZE = 4 * 1024 * 1024
_HEADER = struct.Struct("!I")


class ProtocolError(ValueError):
    """Malformed or unsafe daemon protocol message."""


def send_json(
    connection: socket.socket,
    payload: dict[str, Any],
    *,
    max_size: int = MAX_FRAME_SIZE,
) -> None:
    """Send one UTF-8 JSON object with a fixed-width network-order length."""
    try:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as error:
        raise ProtocolError("Message is not JSON serializable") from error
    if len(body) > max_size:
        raise ProtocolError(f"Message exceeds the {max_size}-byte maximum")
    connection.sendall(_HEADER.pack(len(body)) + body)


def receive_json(
    connection: socket.socket,
    *,
    max_size: int = MAX_FRAME_SIZE,
) -> dict[str, Any]:
    """Read one complete JSON object, regardless of TCP packet boundaries."""
    header = _receive_exact(connection, _HEADER.size)
    (size,) = _HEADER.unpack(header)
    if size == 0:
        raise ProtocolError("Empty messages are not valid")
    if size > max_size:
        raise ProtocolError(f"Message exceeds the {max_size}-byte maximum")
    body = _receive_exact(connection, size)
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError("Message is not valid UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise ProtocolError("Message must be a JSON object")
    return payload


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise ProtocolError("Connection closed with a truncated message")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
