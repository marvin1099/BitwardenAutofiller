"""Authenticated local daemon with mandatory TLS for non-loopback clients."""

from __future__ import annotations

import hmac
import ipaddress
import json
import socket
import socketserver
import ssl
import threading
from contextlib import suppress
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from bitwarden_autofiller.transport import ProtocolError, receive_json, send_json

PROTOCOL_VERSION = 1
SUPPORTED_COMMANDS = frozenset({"list_matches", "get_login", "get_totp", "sync"})


class DaemonRequestError(RuntimeError):
    """A daemon rejected a request or returned a sanitized failure."""


class AutofillDaemon:
    """Serve vault operations over loopback, or TLS-protected TCP."""

    def __init__(
        self,
        service: Any,
        auth_token: str,
        *,
        host: str = "127.0.0.1",
        port: int = 64756,
        tls_certificate: Path | None = None,
        tls_private_key: Path | None = None,
    ) -> None:
        if len(auth_token) < 32:
            raise ValueError("Daemon auth token must contain at least 32 characters")
        if (tls_certificate is None) != (tls_private_key is None):
            raise ValueError("TLS certificate and private key must be set together")
        if not _is_loopback_host(host) and tls_certificate is None:
            raise ValueError(
                "TLS is required when the daemon binds a non-loopback host"
            )

        self.service = service
        self.auth_token = auth_token
        self.host = host
        self.port = port
        self._shutdown_requested = threading.Event()
        self._tls_context: ssl.SSLContext | None = None
        if tls_certificate is not None and tls_private_key is not None:
            self._tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self._tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
            self._tls_context.load_cert_chain(
                certfile=str(tls_certificate), keyfile=str(tls_private_key)
            )

        daemon = self

        class RequestHandler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                daemon._handle_connection(self.request)

        class ThreadedTCPServer(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True
            block_on_close = True

            def get_request(self) -> tuple[socket.socket, Any]:
                connection, address = super().get_request()
                if daemon._tls_context is None:
                    return connection, address
                try:
                    secured = daemon._tls_context.wrap_socket(
                        connection, server_side=True
                    )
                except (OSError, ssl.SSLError):
                    connection.close()
                    raise
                return secured, address

        self._server = ThreadedTCPServer((host, port), RequestHandler)
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        """Return the actual bound address (including an ephemeral test port)."""
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def serve_forever(self) -> None:
        """Run the daemon synchronously until stopped."""
        self._server.serve_forever(poll_interval=0.1)

    def shutdown(self) -> None:
        """Stop accepting requests and release the server socket."""
        self._shutdown_requested.set()
        if self._thread is None:
            self._server.server_close()
        else:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=5)

    def __enter__(self) -> AutofillDaemon:
        self._thread = threading.Thread(
            target=self.serve_forever,
            name="bitwarden-autofill-daemon",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.shutdown()

    def _handle_connection(self, connection: socket.socket) -> None:
        connection.settimeout(15)
        should_stop = False
        try:
            request = receive_json(connection)
            if request.get("version") != PROTOCOL_VERSION:
                raise DaemonRequestError("Unsupported daemon protocol version")
            supplied_token = request.get("token")
            if not isinstance(supplied_token, str) or not hmac.compare_digest(
                supplied_token, self.auth_token
            ):
                raise DaemonRequestError("Daemon authentication failed")

            command = request.get("command")
            arguments = request.get("arguments", {})
            if command == "close":
                result: Any = True
                should_stop = True
            elif command not in SUPPORTED_COMMANDS:
                raise DaemonRequestError("Unsupported daemon command")
            elif not isinstance(arguments, dict):
                raise DaemonRequestError("Daemon command arguments must be an object")
            else:
                result = getattr(self.service, command)(**arguments)

            send_json(connection, {"ok": True, "result": _json_safe(result)})
        except DaemonRequestError as error:
            self._send_error(connection, str(error))
        except (ProtocolError, OSError, TypeError, ValueError, KeyError):
            self._send_error(connection, "Invalid daemon request")
        except Exception:
            # Never serialize exception text: CLI and platform errors may contain
            # sensitive account data or subprocess output.
            self._send_error(connection, "Daemon operation failed")
        finally:
            connection.close()

        if should_stop:
            threading.Thread(target=self._server.shutdown, daemon=True).start()

    @staticmethod
    def _send_error(connection: socket.socket, message: str) -> None:
        with suppress(OSError, ProtocolError):
            send_json(connection, {"ok": False, "error": message})


class DaemonClient:
    """Call the authenticated daemon; remote hosts require a trusted CA file."""

    def __init__(
        self,
        host: str,
        port: int,
        auth_token: str,
        *,
        ca_certificate: Path | None = None,
        timeout: float = 10.0,
    ) -> None:
        if len(auth_token) < 32:
            raise ValueError("Daemon auth token must contain at least 32 characters")
        if not _is_loopback_host(host) and ca_certificate is None:
            raise ValueError(
                "A trusted TLS CA certificate is required for remote hosts"
            )
        self.host = host
        self.port = port
        self.auth_token = auth_token
        self.timeout = timeout
        self._tls_context = (
            ssl.create_default_context(cafile=str(ca_certificate))
            if ca_certificate is not None
            else None
        )

    def request(self, command: str, **arguments: Any) -> Any:
        """Make one bounded command request and return its result."""
        request = {
            "version": PROTOCOL_VERSION,
            "token": self.auth_token,
            "command": command,
            "arguments": arguments,
        }
        try:
            with socket.create_connection(
                (self.host, self.port), timeout=self.timeout
            ) as connection:
                connection.settimeout(self.timeout)
                if self._tls_context is not None:
                    connection = self._tls_context.wrap_socket(
                        connection, server_hostname=self.host
                    )
                send_json(connection, request)
                response = receive_json(connection)
        except (OSError, ssl.SSLError, ProtocolError) as error:
            raise DaemonRequestError(
                "Unable to communicate with autofill daemon"
            ) from error

        if response.get("ok") is not True:
            message = response.get("error")
            if not isinstance(message, str):
                message = "Daemon request failed"
            raise DaemonRequestError(message)
        return response.get("result")


def _is_loopback_host(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    try:
        json.dumps(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Daemon service returned non-JSON data") from error
    return value
