"""Small, secret-minimizing models for Bitwarden login items."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bitwarden_autofiller.app_uri import (
    application_id_from_uri,
    normalize_app_id,
)


@dataclass(frozen=True, slots=True)
class LoginSummary:
    """Non-secret fields needed to present and match a login."""

    id: str
    name: str
    username: str = field(repr=False)
    uris: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LoginCredentials:
    """Credentials for one selected item; secrets are excluded from repr."""

    id: str
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)
    totp: str | None = field(default=None, repr=False)
    uris: tuple[str, ...] = ()


def matching_logins(
    entries: tuple[LoginSummary, ...] | list[LoginSummary], app_id: str | None
) -> tuple[LoginSummary, ...]:
    """Return logins explicitly mapped to ``app_id`` in vault order."""
    target = normalize_app_id(app_id)
    if not target:
        return ()

    return tuple(
        entry
        for entry in entries
        if any(application_id_from_uri(uri) == target for uri in entry.uris)
    )


def summaries_from_response(response: Any) -> tuple[LoginSummary, ...]:
    """Convert a Bitwarden CLI list response without retaining password fields."""
    payload = response
    if isinstance(payload, dict) and payload.get("success") is False:
        raise ValueError("Bitwarden CLI failed to list items")

    while isinstance(payload, dict) and "data" in payload:
        payload = payload["data"]
    if not isinstance(payload, list):
        raise ValueError("Bitwarden CLI returned an unexpected items response")

    summaries: list[LoginSummary] = []
    for item in payload:
        if not isinstance(item, dict) or item.get("type") not in (None, 1):
            continue
        login = item.get("login")
        if not isinstance(login, dict):
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            continue
        raw_uris = login.get("uris") or ()
        uris = tuple(
            uri["uri"]
            for uri in raw_uris
            if isinstance(uri, dict) and isinstance(uri.get("uri"), str)
        )
        summaries.append(
            LoginSummary(
                id=item_id,
                name=str(item.get("name") or "Unnamed login"),
                username=str(login.get("username") or ""),
                uris=uris,
            )
        )
    return tuple(summaries)


def credentials_from_response(response: Any) -> LoginCredentials:
    """Convert a single Bitwarden item response to one credential record."""
    payload = response
    if isinstance(payload, dict) and payload.get("success") is False:
        raise ValueError("Bitwarden CLI failed to read item")
    while isinstance(payload, dict) and "data" in payload:
        payload = payload["data"]
    if not isinstance(payload, dict):
        raise ValueError("Bitwarden CLI returned an unexpected item response")

    login = payload.get("login")
    if not isinstance(login, dict):
        raise ValueError("The selected Bitwarden item is not a login")
    item_id = payload.get("id")
    if not isinstance(item_id, str) or not item_id:
        raise ValueError("Bitwarden item response has no valid id")
    return LoginCredentials(
        id=item_id,
        username=_optional_string(login.get("username")),
        password=_optional_string(login.get("password")),
        totp=_optional_string(login.get("totp")),
        uris=_uri_values(login.get("uris")),
    )


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    return str(value)


def _uri_values(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        uri["uri"]
        for uri in value
        if isinstance(uri, dict) and isinstance(uri.get("uri"), str)
    )
