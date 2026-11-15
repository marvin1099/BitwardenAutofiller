"""Validated client-side facade for the authenticated daemon protocol."""

from __future__ import annotations

from typing import Any, Protocol

from bitwarden_autofiller.daemon import DaemonClient, DaemonRequestError
from bitwarden_autofiller.vault import LoginCredentials, LoginSummary


class RequestClient(Protocol):
    def request(self, command: str, **arguments: Any) -> Any: ...


class RemoteVaultService:
    """Adapt daemon requests to the same interface used by local filling."""

    def __init__(self, client: RequestClient | DaemonClient) -> None:
        self._client = client

    def list_matches(self, app_id: str) -> tuple[LoginSummary, ...]:
        response = self._client.request("list_matches", app_id=app_id)
        if not isinstance(response, list):
            raise DaemonRequestError("Daemon returned an invalid match list")

        summaries: list[LoginSummary] = []
        for item in response:
            if not isinstance(item, dict):
                raise DaemonRequestError("Daemon returned an invalid match record")
            item_id = item.get("id")
            name = item.get("name")
            username = item.get("username", "")
            uris = item.get("uris", ())
            if (
                not isinstance(item_id, str)
                or not isinstance(name, str)
                or not isinstance(username, str)
                or not isinstance(uris, (tuple, list))
                or not all(isinstance(uri, str) for uri in uris)
            ):
                raise DaemonRequestError("Daemon returned an invalid match record")
            summaries.append(LoginSummary(item_id, name, username, tuple(uris)))
        return tuple(summaries)

    def get_login(self, app_id: str, item_id: str) -> LoginCredentials:
        response = self._client.request("get_login", app_id=app_id, item_id=item_id)
        if not isinstance(response, dict):
            raise DaemonRequestError("Daemon returned an invalid login record")
        if response.get("id") != item_id:
            raise DaemonRequestError("Daemon returned a different login than requested")
        return LoginCredentials(
            id=item_id,
            username=_optional_string(response.get("username")),
            password=_optional_string(response.get("password")),
            totp=_optional_string(response.get("totp")),
            uris=_uri_values(response.get("uris", ())),
        )

    def get_totp(self, app_id: str, item_id: str) -> str:
        response = self._client.request("get_totp", app_id=app_id, item_id=item_id)
        if not isinstance(response, str) or not response:
            raise DaemonRequestError("Daemon returned no TOTP for the selected login")
        return response

    def sync(self) -> None:
        self._client.request("sync")

    def close(self) -> None:
        """Drop no local vault state; credentials stay on the daemon host."""


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    raise DaemonRequestError("Daemon returned an invalid login record")


def _uri_values(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(uri, str) for uri in value
    ):
        raise DaemonRequestError("Daemon returned an invalid login record")
    return tuple(value)
