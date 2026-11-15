"""Application service for matching and retrieving selected vault logins."""

from __future__ import annotations

from typing import Any, Protocol

from bitwarden_autofiller.vault.items import (
    LoginCredentials,
    LoginSummary,
    credentials_from_response,
    matching_logins,
    summaries_from_response,
)


class BitwardenCommandClient(Protocol):
    """The small subset of the CLI adapter used by the vault service."""

    def command(self, arguments: list[str], *, session_key: str) -> dict[str, Any]: ...


class ItemNotMatchedError(LookupError):
    """The requested item is not explicitly mapped to the active app."""


class VaultService:
    """Query the vault on demand and retain only the current session key.

    The CLI's complete item response exists only for the duration of a method
    call. Listing and matching returns summary objects, while a full login is
    fetched only after its ID has been checked against the active app mapping.
    """

    def __init__(self, cli: BitwardenCommandClient, session_key: str) -> None:
        if not session_key:
            raise ValueError("A Bitwarden session key is required")
        self._cli = cli
        self._session_key: str | None = session_key

    def list_matches(self, app_id: str) -> tuple[LoginSummary, ...]:
        """Return non-secret login summaries mapped to ``app_id``."""
        session_key = self._require_session()
        response = self._cli.command(["list", "items"], session_key=session_key)
        return matching_logins(summaries_from_response(response), app_id)

    def get_login(self, app_id: str, item_id: str) -> LoginCredentials:
        """Retrieve a single login after verifying its app mapping."""
        if not any(summary.id == item_id for summary in self.list_matches(app_id)):
            raise ItemNotMatchedError(
                "The selected login is not mapped to the active application"
            )

        response = self._cli.command(
            ["get", "item", item_id], session_key=self._require_session()
        )
        credentials = credentials_from_response(response)
        if credentials.id != item_id:
            raise ValueError("Bitwarden CLI returned a different item than requested")
        verified_mapping = LoginSummary(
            credentials.id,
            "",
            credentials.username or "",
            credentials.uris,
        )
        if not matching_logins((verified_mapping,), app_id):
            raise ItemNotMatchedError(
                "The selected login no longer matches the active application"
            )
        return credentials

    def get_totp(self, app_id: str, item_id: str) -> str:
        """Retrieve a TOTP only on explicit request for a mapped login."""
        if not any(summary.id == item_id for summary in self.list_matches(app_id)):
            raise ItemNotMatchedError(
                "The selected login is not mapped to the active application"
            )

        response = self._cli.command(
            ["get", "totp", item_id], session_key=self._require_session()
        )
        value = _response_value(response)
        if not isinstance(value, str) or not value:
            raise ValueError("Bitwarden CLI returned no TOTP for the selected item")
        return value

    def sync(self) -> None:
        """Synchronize the vault using the active CLI session."""
        self._cli.command(["sync"], session_key=self._require_session())

    def close(self) -> None:
        """Drop the in-process reference to the session key."""
        self._session_key = None

    def _require_session(self) -> str:
        if self._session_key is None:
            raise RuntimeError("Vault service is closed")
        return self._session_key


def _response_value(response: Any) -> Any:
    """Unwrap Bitwarden's response envelope while preserving scalar values."""
    value = response
    if isinstance(value, dict) and value.get("success") is False:
        raise ValueError("Bitwarden CLI failed to retrieve the requested value")
    while isinstance(value, dict) and "data" in value:
        value = value["data"]
    return value
