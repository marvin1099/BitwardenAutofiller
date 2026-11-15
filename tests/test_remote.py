from typing import Any

import pytest

from bitwarden_autofiller.daemon import DaemonRequestError
from bitwarden_autofiller.remote import RemoteVaultService
from bitwarden_autofiller.vault import LoginCredentials, LoginSummary


class FakeDaemonClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def request(self, command: str, **arguments: Any) -> Any:
        self.calls.append((command, arguments))
        if command == "list_matches":
            return [
                {
                    "id": "steam-login",
                    "name": "Steam",
                    "username": "alice",
                    "uris": ["pcprocess://steam"],
                }
            ]
        if command == "get_login":
            return {
                "id": "steam-login",
                "username": "alice",
                "password": "selected-only",
                "uris": ["pcprocess://steam"],
            }
        if command == "get_totp":
            return "123456"
        return True


def test_remote_service_adapts_daemon_models_and_operations() -> None:
    client = FakeDaemonClient()
    service = RemoteVaultService(client)

    assert service.list_matches("steam") == (
        LoginSummary("steam-login", "Steam", "alice", ("pcprocess://steam",)),
    )
    assert service.get_login("steam", "steam-login") == LoginCredentials(
        "steam-login",
        username="alice",
        password="selected-only",
        uris=("pcprocess://steam",),
    )
    assert service.get_totp("steam", "steam-login") == "123456"
    service.sync()
    service.close()

    assert [command for command, _ in client.calls] == [
        "list_matches",
        "get_login",
        "get_totp",
        "sync",
    ]


@pytest.mark.parametrize(
    "response",
    [None, {"id": 3}, {"id": "steam-login", "uris": [4]}],
)
def test_remote_service_rejects_malformed_match_records(response: Any) -> None:
    class MalformedClient:
        def request(self, command: str, **arguments: Any) -> Any:
            return [response]

    with pytest.raises(DaemonRequestError, match="invalid match"):
        RemoteVaultService(MalformedClient()).list_matches("steam")


def test_remote_service_rejects_wrong_item_and_non_string_totp() -> None:
    class MalformedClient:
        def request(self, command: str, **arguments: Any) -> Any:
            return {"id": "other"} if command == "get_login" else 123

    service = RemoteVaultService(MalformedClient())
    with pytest.raises(DaemonRequestError, match="different login"):
        service.get_login("steam", "steam-login")
    with pytest.raises(DaemonRequestError, match="no TOTP"):
        service.get_totp("steam", "steam-login")
