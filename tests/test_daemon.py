import pytest

from bitwarden_autofiller.daemon import (
    AutofillDaemon,
    DaemonClient,
    DaemonRequestError,
)


class FakeVaultService:
    def list_matches(self, app_id: str) -> list[dict[str, str]]:
        return [{"id": "vault-id", "name": f"For {app_id}"}]


def test_local_daemon_serves_authorized_requests() -> None:
    token = "test-token-with-enough-entropy-123456789"
    daemon = AutofillDaemon(FakeVaultService(), token, port=0)

    with daemon:
        client = DaemonClient(*daemon.address, token)

        assert client.request("list_matches", app_id="steam") == [
            {"id": "vault-id", "name": "For steam"}
        ]


def test_local_daemon_rejects_wrong_authentication_token() -> None:
    daemon = AutofillDaemon(
        FakeVaultService(), "test-token-with-enough-entropy-123456789", port=0
    )

    with daemon:
        client = DaemonClient(*daemon.address, "wrong-token-with-enough-entropy-123")

        with pytest.raises(DaemonRequestError, match="authentication"):
            client.request("list_matches", app_id="steam")


def test_non_loopback_daemon_requires_tls() -> None:
    with pytest.raises(ValueError, match="TLS"):
        AutofillDaemon(
            FakeVaultService(),
            "test-token-with-enough-entropy-123456789",
            host="0.0.0.0",
            port=0,
        )


def test_unknown_daemon_commands_are_rejected() -> None:
    daemon = AutofillDaemon(
        FakeVaultService(), "test-token-with-enough-entropy-123456789", port=0
    )

    with daemon:
        client = DaemonClient(
            *daemon.address, "test-token-with-enough-entropy-123456789"
        )

        with pytest.raises(DaemonRequestError, match="Unsupported"):
            client.request("shell")
