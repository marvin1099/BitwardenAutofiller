from collections.abc import Sequence

import pytest

from bitwarden_autofiller import cli
from bitwarden_autofiller.desktop.platforms import InputBackendError
from bitwarden_autofiller.filling.actions import Action
from bitwarden_autofiller.filling.execution import InputAdapter
from bitwarden_autofiller.filling.workflow import FillResult
from bitwarden_autofiller.vault.bitwarden import BitwardenCLIError
from bitwarden_autofiller.vault.items import LoginSummary


class FakeService:
    def __init__(self, matches: tuple[LoginSummary, ...] | None = None) -> None:
        self.matches = (
            matches
            if matches is not None
            else (LoginSummary("one", "First", "alice", ("pcprocess://steam",)),)
        )
        self.synced = False
        self.closed = False

    def sync(self) -> None:
        self.synced = True

    def list_matches(self, app_id: str) -> tuple[LoginSummary, ...]:
        return self.matches

    def close(self) -> None:
        self.closed = True


class FakeInput:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def type_text(self, text: str) -> None:
        pass

    def press_key(self, key: str) -> None:
        pass

    def copy_text(self, text: str) -> None:
        pass


def setup_cli(
    monkeypatch: pytest.MonkeyPatch,
    *,
    service: FakeService | None = None,
    input_adapter: FakeInput | None = None,
) -> tuple[FakeService, FakeInput]:
    fake_service = service or FakeService()
    fake_input = input_adapter or FakeInput()
    monkeypatch.setattr(cli, "BitwardenCLI", lambda _: object())
    monkeypatch.setattr(
        cli, "authenticate_vault", lambda _client, *, email=None: fake_service
    )
    monkeypatch.setattr(cli, "create_input_adapter", lambda: fake_input)

    def fake_fill(
        _service: object,
        _app_id: str,
        _actions: Sequence[Action],
        input_adapter: InputAdapter,
    ) -> FillResult:
        input_adapter.type_text("test")
        return FillResult(matched_items=1, selected_items=1, input_operations=3)

    monkeypatch.setattr(cli, "fill_for_app", fake_fill)
    return fake_service, fake_input


def test_cli_exposes_only_nonsecret_authentication_options() -> None:
    parser = cli.build_parser()

    with pytest.raises(SystemExit) as raised:
        parser.parse_args(["--password", "must-not-be-accepted"])

    assert raised.value.code == 2


def test_cli_fills_and_closes_service_and_input_adapter(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    service, input_adapter = setup_cli(monkeypatch)

    result = cli.main(
        [
            "--app-id",
            "steam",
            "--delay",
            "0",
            "--sync",
            "--email",
            "alice@example.test",
        ]
    )

    assert result == 0
    assert service.synced
    assert service.closed
    assert input_adapter.closed
    assert "3 input operation(s)" in capsys.readouterr().out


def test_cli_reports_unmapped_app_without_opening_input_backend(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    service, input_adapter = setup_cli(monkeypatch, service=FakeService(matches=()))

    assert cli.main(["--app-id", "unknown", "--delay", "0"]) == 1

    assert service.closed
    assert not input_adapter.closed
    assert "No Bitwarden login" in capsys.readouterr().err


def test_cli_handles_unsafe_or_unavailable_input_without_echoing_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    service = FakeService()
    monkeypatch.setattr(cli, "BitwardenCLI", lambda _: object())
    monkeypatch.setattr(
        cli, "authenticate_vault", lambda _client, *, email=None: service
    )
    monkeypatch.setattr(
        cli,
        "create_input_adapter",
        lambda: (_ for _ in ()).throw(InputBackendError("Wayland permission denied")),
    )

    def fail_input(
        _service: object,
        _app_id: str,
        _actions: Sequence[Action],
        adapter: InputAdapter,
    ) -> FillResult:
        adapter.type_text("trigger")
        raise AssertionError("Input adapter should have raised an error")

    monkeypatch.setattr(cli, "fill_for_app", fail_input)

    assert cli.main(["--app-id", "steam", "--delay", "0"]) == 1

    assert service.closed
    assert "Wayland permission denied" in capsys.readouterr().err


def test_cli_sanitizes_cli_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_resolve(_: str) -> str:
        raise BitwardenCLIError("safe failure")

    monkeypatch.setattr(
        cli,
        "resolve_app_id",
        fail_resolve,
    )

    assert cli.main(["--app-id", "steam"]) == 1
    assert "safe failure" in capsys.readouterr().err


def test_cli_can_use_authenticated_remote_daemon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, input_adapter = setup_cli(monkeypatch)
    daemon_client = object()
    monkeypatch.setattr(cli, "read_auth_token", lambda _: "private-token")
    monkeypatch.setattr(
        cli,
        "DaemonClient",
        lambda host, port, token, *, ca_certificate=None: daemon_client,
    )
    monkeypatch.setattr(cli, "RemoteVaultService", lambda client: service)

    result = cli.main(
        [
            "--app-id",
            "steam",
            "--delay",
            "0",
            "--daemon-host",
            "127.0.0.1",
            "--token-file",
            "/tmp/fake-token",
        ]
    )

    assert result == 0
    assert service.closed
    assert input_adapter.closed
