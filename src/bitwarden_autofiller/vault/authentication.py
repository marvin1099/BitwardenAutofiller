"""Interactive authentication orchestration for the official Bitwarden CLI."""

from __future__ import annotations

import getpass
import os
from collections.abc import Callable
from typing import Any, Protocol

from bitwarden_autofiller.vault.bitwarden import BitwardenCLIError
from bitwarden_autofiller.vault.service import BitwardenCommandClient, VaultService


class AuthenticationClient(BitwardenCommandClient, Protocol):
    """CLI operations required to determine and establish vault state."""

    def status(self) -> dict[str, Any]: ...

    def login(self, email: str, password: str) -> str: ...

    def unlock(self, password: str) -> str: ...


class AuthenticationError(RuntimeError):
    """The vault could not be placed into an authenticated state."""


def authenticate_vault(
    cli: AuthenticationClient,
    *,
    email: str | None = None,
    password: str | None = None,
    session_key: str | None = None,
    prompt_email: Callable[[str], str] = input,
    password_prompt: Callable[[str], str] = getpass.getpass,
) -> VaultService:
    """Inspect CLI state, then login or unlock with prompted credentials.

    A session key already supplied by the caller or ``BW_SESSION`` is reused
    only when the CLI reports an unlocked vault. Otherwise the CLI's official
    password-environment mechanism establishes a fresh session.
    """
    status = _vault_status(cli.status())
    if status == "unlocked":
        existing_key = session_key or os.environ.get("BW_SESSION")
        if existing_key:
            return VaultService(cli, existing_key)
        # The CLI can report an unlocked local state while this process does
        # not possess BW_SESSION. Unlocking returns an explicit key scoped to
        # this application process rather than relying on shell state.
        session_key = cli.unlock(_password(password, password_prompt))
    elif status == "locked":
        session_key = cli.unlock(_password(password, password_prompt))
    elif status == "unauthenticated":
        account_email = email or prompt_email("Bitwarden email address: ").strip()
        if not account_email:
            raise AuthenticationError("A Bitwarden email address is required")
        session_key = cli.login(account_email, _password(password, password_prompt))
    else:
        raise AuthenticationError("Bitwarden CLI returned an unknown vault status")

    if not session_key:
        raise AuthenticationError("Bitwarden CLI did not provide a session key")
    return VaultService(cli, session_key)


def _password(password: str | None, password_prompt: Callable[[str], str]) -> str:
    value = password if password is not None else password_prompt("Master password: ")
    if not value:
        raise AuthenticationError("A Bitwarden master password is required")
    return value


def _vault_status(response: Any) -> str:
    """Read the documented ``status.template.status`` response field."""
    value = response
    if isinstance(value, dict) and value.get("success") is False:
        # Do not bubble up CLI messages: they may disclose account details.
        raise BitwardenCLIError("Bitwarden CLI could not determine vault status")
    while isinstance(value, dict) and "data" in value:
        value = value["data"]
    if not isinstance(value, dict):
        raise AuthenticationError("Bitwarden CLI returned an invalid status response")
    template = value.get("template")
    state = (
        template.get("status") if isinstance(template, dict) else value.get("status")
    )
    if not isinstance(state, str):
        raise AuthenticationError("Bitwarden CLI status did not include vault state")
    return state.strip().casefold()
