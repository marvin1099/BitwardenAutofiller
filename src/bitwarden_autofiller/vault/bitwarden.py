"""Least-privilege adapter around Bitwarden's supported password-manager CLI."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

PASSWORD_ENVIRONMENT_VARIABLE = "BW_AUTOFILLER_MASTER_PASSWORD"
_LOGGER = logging.getLogger(__name__)


class BitwardenCLIError(RuntimeError):
    """Sanitized Bitwarden CLI failure; never contains raw CLI output."""


class BitwardenCLI:
    """Call the official ``bw`` CLI without placing secrets in argv.

    The official Python ``bitwarden-sdk`` package is for Secrets Manager, not
    the personal Password Manager vault. This adapter deliberately uses the
    supported Password Manager CLI protocol instead.
    """

    def __init__(
        self,
        executable: str | Path | Sequence[str] = "bw",
        *,
        timeout: float = 30.0,
    ) -> None:
        self.executable = (
            (str(executable),)
            if isinstance(executable, (str, Path))
            else tuple(str(part) for part in executable)
        )
        if not self.executable:
            raise ValueError("Bitwarden CLI executable cannot be empty")
        self.timeout = timeout

    def status(self) -> dict[str, Any]:
        """Return a parsed, response-mode status object."""
        return self.command(["status"])

    def login(self, email: str, password: str) -> str:
        """Authenticate, supplying the master password via a child env var."""
        response = self._invoke(
            ["login", email, "--passwordenv", PASSWORD_ENVIRONMENT_VARIABLE],
            password=password,
            clear_session=True,
        )
        return _session_key(response)

    def unlock(self, password: str) -> str:
        """Unlock the existing account without exposing its password in argv."""
        response = self._invoke(
            ["unlock", "--passwordenv", PASSWORD_ENVIRONMENT_VARIABLE],
            password=password,
            clear_session=True,
        )
        return _session_key(response)

    def command(
        self,
        arguments: Sequence[str],
        *,
        session_key: str | None = None,
    ) -> dict[str, Any]:
        """Execute a non-interactive CLI command using ``BW_SESSION``."""
        if not arguments:
            raise ValueError("Bitwarden CLI command cannot be empty")
        return self._invoke(list(arguments), session_key=session_key)

    def _invoke(
        self,
        arguments: list[str],
        *,
        password: str | None = None,
        session_key: str | None = None,
        clear_session: bool = False,
    ) -> dict[str, Any]:
        argv = [*self.executable, *arguments]
        operation = _safe_operation(arguments)
        _LOGGER.debug("Executing Bitwarden CLI operation %s", operation)
        if "--response" not in argv:
            argv.append("--response")

        environment = os.environ.copy()
        environment["BW_NOINTERACTION"] = "true"
        environment.pop(PASSWORD_ENVIRONMENT_VARIABLE, None)
        if clear_session:
            environment.pop("BW_SESSION", None)
        if password is not None:
            environment[PASSWORD_ENVIRONMENT_VARIABLE] = password
        if session_key is not None:
            environment["BW_SESSION"] = session_key

        try:
            result = subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
                env=environment,
            )
        except FileNotFoundError as error:
            _LOGGER.error("Bitwarden CLI executable was not found")
            raise BitwardenCLIError("Bitwarden CLI executable was not found") from error
        except subprocess.TimeoutExpired as error:
            _LOGGER.warning("Bitwarden CLI operation %s timed out", operation)
            raise BitwardenCLIError("Bitwarden CLI command timed out") from error
        finally:
            environment.pop(PASSWORD_ENVIRONMENT_VARIABLE, None)
            environment.pop("BW_SESSION", None)

        if result.returncode != 0:
            _LOGGER.warning("Bitwarden CLI operation %s failed", operation)
            raise BitwardenCLIError(
                "Bitwarden CLI command failed; inspect `bw` directly for details"
            )
        try:
            response = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            _LOGGER.warning(
                "Bitwarden CLI operation %s returned invalid JSON", operation
            )
            raise BitwardenCLIError(
                "Bitwarden CLI returned an invalid JSON response"
            ) from error
        if not isinstance(response, dict):
            _LOGGER.warning(
                "Bitwarden CLI operation %s returned an invalid response", operation
            )
            raise BitwardenCLIError("Bitwarden CLI returned an unexpected response")
        if response.get("success") is False:
            _LOGGER.warning("Bitwarden CLI operation %s was rejected", operation)
            raise BitwardenCLIError("Bitwarden CLI rejected the requested operation")
        _LOGGER.debug("Bitwarden CLI operation %s completed", operation)
        return response


def _session_key(response: dict[str, Any]) -> str:
    data = response.get("data")
    raw_key = data.get("raw") if isinstance(data, dict) else None
    if not isinstance(raw_key, str) or not raw_key:
        raise BitwardenCLIError("Bitwarden CLI response did not include a session key")
    return raw_key


def _safe_operation(arguments: Sequence[str]) -> str:
    """Return only an allowlisted operation name for use in log messages."""
    if arguments and arguments[0] in {
        "status",
        "login",
        "unlock",
        "list",
        "get",
        "sync",
    }:
        return arguments[0]
    return "other"
