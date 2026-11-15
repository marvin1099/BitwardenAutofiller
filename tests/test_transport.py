import socket

import pytest

from bitwarden_autofiller.daemon.transport import (
    ProtocolError,
    receive_json,
    send_json,
)


def test_framed_transport_round_trips_large_unicode_payload() -> None:
    sender, receiver = socket.socketpair()
    try:
        payload = {"message": "Schlüssel 🔐" * 2_000}
        send_json(sender, payload)

        assert receive_json(receiver) == payload
    finally:
        sender.close()
        receiver.close()


def test_framed_transport_rejects_oversized_payload() -> None:
    sender, receiver = socket.socketpair()
    try:
        send_json(sender, {"message": "too large"})

        with pytest.raises(ProtocolError, match="maximum"):
            receive_json(receiver, max_size=4)
    finally:
        sender.close()
        receiver.close()


def test_framed_transport_rejects_truncated_payload() -> None:
    sender, receiver = socket.socketpair()
    sender.sendall(b"\x00\x00\x00\x08abc")
    sender.close()
    try:
        with pytest.raises(ProtocolError, match="truncated"):
            receive_json(receiver)
    finally:
        receiver.close()


def test_framed_transport_rejects_non_object_json() -> None:
    sender, receiver = socket.socketpair()
    try:
        sender.sendall(b"\x00\x00\x00\x02[]")

        with pytest.raises(ProtocolError, match="JSON object"):
            receive_json(receiver)
    finally:
        sender.close()
        receiver.close()
