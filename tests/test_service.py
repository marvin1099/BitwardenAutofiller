from typing import Any

import pytest

from bitwarden_autofiller.vault.items import LoginCredentials, LoginSummary
from bitwarden_autofiller.vault.service import ItemNotMatchedError, VaultService


class FakeBitwardenCLI:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []
        self.detail_uris = [{"uri": "pcprocess://steam"}]
        self.items = [
            {
                "id": "steam-login",
                "type": 1,
                "name": "Steam personal",
                "login": {
                    "username": "alice",
                    "password": "do-not-cache-all-items",
                    "uris": [{"uri": "pcprocess://steam"}],
                },
            },
            {
                "id": "mail-login",
                "type": 1,
                "name": "Mail",
                "login": {
                    "username": "alice@example.test",
                    "password": "unrelated-secret",
                    "uris": [{"uri": "pcprocess://mail"}],
                },
            },
        ]

    def command(self, arguments: list[str], *, session_key: str) -> dict[str, Any]:
        self.calls.append((arguments, session_key))
        if arguments == ["list", "items"]:
            return {"success": True, "data": {"data": self.items}}
        if arguments == ["get", "item", "steam-login"]:
            return {
                "success": True,
                "data": {
                    "data": {
                        "id": "steam-login",
                        "login": {
                            "username": "alice",
                            "password": "selected-only",
                            "uris": self.detail_uris,
                        },
                    }
                },
            }
        if arguments == ["get", "totp", "steam-login"]:
            return {"success": True, "data": {"data": "123456"}}
        if arguments == ["sync"]:
            return {"success": True}
        raise AssertionError(f"Unexpected CLI call: {arguments!r}")


def test_listing_logins_keeps_only_safe_summaries() -> None:
    cli = FakeBitwardenCLI()
    service = VaultService(cli, "session-key-for-tests")

    assert service.list_matches("steam") == (
        LoginSummary("steam-login", "Steam personal", "alice", ("pcprocess://steam",)),
    )
    assert "unrelated-secret" not in repr(service.list_matches("steam"))


def test_service_fetches_only_the_selected_matching_login() -> None:
    cli = FakeBitwardenCLI()
    service = VaultService(cli, "session-key-for-tests")

    credentials = service.get_login("steam", "steam-login")

    assert credentials == LoginCredentials(
        "steam-login",
        username="alice",
        password="selected-only",
        uris=("pcprocess://steam",),
    )
    assert [call[0] for call in cli.calls].count(["get", "item", "steam-login"]) == 1
    assert all(session == "session-key-for-tests" for _, session in cli.calls)


def test_vault_logs_include_match_counts_but_not_account_data(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cli = FakeBitwardenCLI()
    service = VaultService(cli, "session-key-for-tests")

    with caplog.at_level("DEBUG", logger="bitwarden_autofiller"):
        service.list_matches("steam")

    assert "1 matching login(s)" in caplog.text
    assert "steam-login" not in caplog.text
    assert "alice" not in caplog.text
    assert "steam" not in caplog.text


def test_service_refuses_to_fetch_an_item_mapped_to_another_app() -> None:
    cli = FakeBitwardenCLI()
    service = VaultService(cli, "session-key-for-tests")

    with pytest.raises(ItemNotMatchedError):
        service.get_login("steam", "mail-login")

    assert not any(arguments[:2] == ["get", "item"] for arguments, _ in cli.calls)


def test_service_rechecks_mapping_in_the_fetched_item() -> None:
    cli = FakeBitwardenCLI()
    cli.detail_uris = [{"uri": "pcprocess://mail"}]
    service = VaultService(cli, "session-key-for-tests")

    with pytest.raises(ItemNotMatchedError, match="no longer matches"):
        service.get_login("steam", "steam-login")


def test_totp_is_retrieved_only_when_requested() -> None:
    cli = FakeBitwardenCLI()
    service = VaultService(cli, "session-key-for-tests")

    assert service.get_totp("steam", "steam-login") == "123456"

    assert [call[0] for call in cli.calls].count(["get", "totp", "steam-login"]) == 1


def test_close_clears_the_held_session_key() -> None:
    service = VaultService(FakeBitwardenCLI(), "session-key-for-tests")

    service.close()

    with pytest.raises(RuntimeError, match="closed"):
        service.list_matches("steam")
