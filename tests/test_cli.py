from collections.abc import Sequence

import pytest

from bitwarden_autofiller import cli
from bitwarden_autofiller.desktop import app_identity
from bitwarden_autofiller.desktop.app_identity import ActiveApplicationUnavailable
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
        self.requested_app_ids: list[str] = []

    def sync(self) -> None:
        self.synced = True

    def list_matches(self, app_id: str) -> tuple[LoginSummary, ...]:
        self.requested_app_ids.append(app_id)
        return self.matches

    def close(self) -> None:
        self.closed = True


class FakeInput:
    def __init__(self) -> None:
        self.closed = False
        self.operations: list[tuple[str, str]] = []

    def close(self) -> None:
        self.closed = True

    def type_text(self, text: str) -> None:
        self.operations.append(("type", text))

    def press_key(self, key: str) -> None:
        self.operations.append(("key", key))

    def copy_text(self, text: str) -> None:
        self.operations.append(("copy", text))


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

    def resolve(explicit_app_id: str | None = None, **_: object) -> str:
        return explicit_app_id or "steam"

    monkeypatch.setattr(cli, "resolve_app_id", resolve)
    monkeypatch.setattr(app_identity, "resolve_app_id", resolve)

    def fake_fill(
        _service: object,
        _app_id: str,
        _actions: Sequence[Action],
        input_adapter: InputAdapter,
        *,
        before_input: object = None,
    ) -> FillResult:
        if callable(before_input):
            before_input()
        input_adapter.type_text("test")
        return FillResult(matched_items=1, selected_items=1, input_operations=3)

    monkeypatch.setattr(cli, "fill_for_app", fake_fill)
    return fake_service, fake_input


def test_cli_exposes_only_nonsecret_authentication_options() -> None:
    parser = cli.build_parser()

    with pytest.raises(SystemExit) as raised:
        parser.parse_args(["--password", "must-not-be-accepted"])

    assert raised.value.code == 2


def test_cli_can_generate_a_profile_uri_without_vault_access(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = cli.main(["--generate-uri", "--app-id", "steam", "--actions", "147"])

    assert result == 0
    assert capsys.readouterr().out.strip() == "pcprocess://steam?actions=147"


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


def test_cli_detects_active_app_after_the_focus_countdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = setup_cli(monkeypatch)
    events: list[str] = []
    monkeypatch.setattr(
        "bitwarden_autofiller.cli.time.sleep", lambda _: events.append("countdown")
    )

    def detect(*_args: str | None, active_app_command: str | None = None) -> str:
        events.append(f"detect:{active_app_command}")
        return "steam"

    monkeypatch.setattr(cli, "resolve_app_id", detect)
    monkeypatch.setattr(app_identity, "resolve_app_id", detect)

    assert (
        cli.main(["--delay", "3", "--active-app-command", "get-active-window-pid"]) == 0
    )

    assert events == [
        "countdown",
        "detect:get-active-window-pid",
        "detect:get-active-window-pid",
    ]
    assert service.requested_app_ids == ["steam"]


def test_cli_uses_the_first_match_uri_profile_when_actions_are_not_overridden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeService(
        (LoginSummary("one", "First", "alice", ("pcprocess://steam?actions=14",)),)
    )
    input_adapter = FakeInput()
    monkeypatch.setattr(cli, "BitwardenCLI", lambda _: object())
    monkeypatch.setattr(
        cli, "authenticate_vault", lambda _client, *, email=None: service
    )

    def resolve(explicit_app_id: str | None = None, **_: object) -> str:
        return explicit_app_id or "steam"

    monkeypatch.setattr(cli, "resolve_app_id", resolve)
    monkeypatch.setattr(app_identity, "resolve_app_id", resolve)
    monkeypatch.setattr(cli, "create_input_adapter", lambda: input_adapter)

    assert cli.main(["--app-id", "steam", "--delay", "0"]) == 0

    assert input_adapter.closed


def test_cli_reports_unmapped_app_without_opening_input_backend(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    service, input_adapter = setup_cli(monkeypatch, service=FakeService(matches=()))

    assert cli.main(["--app-id", "unknown", "--delay", "0"]) == 1

    assert service.closed
    assert not input_adapter.closed
    assert "No Bitwarden login" in capsys.readouterr().err


def test_cli_aborts_when_focused_app_does_not_match_selected_app(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    service, input_adapter = setup_cli(monkeypatch)
    monkeypatch.setattr(
        cli,
        "resolve_app_id",
        lambda explicit_app_id=None, **_: explicit_app_id or "browser",
    )
    monkeypatch.setattr(
        app_identity,
        "resolve_app_id",
        lambda explicit_app_id=None, **_: explicit_app_id or "browser",
    )

    assert cli.main(["--app-id", "steam", "--delay", "0"]) == 1

    assert input_adapter.operations == []
    assert service.closed
    assert "focused application does not match" in capsys.readouterr().err


def test_cli_requires_explicit_opt_in_for_an_unverified_target(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    service, input_adapter = setup_cli(monkeypatch)

    def unavailable(explicit_app_id: str | None = None, **_: object) -> str:
        if explicit_app_id:
            return explicit_app_id
        raise ActiveApplicationUnavailable("detector unavailable")

    monkeypatch.setattr(cli, "resolve_app_id", unavailable)
    monkeypatch.setattr(app_identity, "resolve_app_id", unavailable)

    assert cli.main(["--app-id", "steam", "--delay", "0"]) == 1

    assert input_adapter.operations == []
    assert service.closed
    assert "explicitly allow an unverified target" in capsys.readouterr().err


def test_cli_warns_when_unverified_target_is_explicitly_allowed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _service, input_adapter = setup_cli(monkeypatch)

    def unavailable(explicit_app_id: str | None = None, **_: object) -> str:
        if explicit_app_id:
            return explicit_app_id
        raise ActiveApplicationUnavailable("detector unavailable")

    monkeypatch.setattr(cli, "resolve_app_id", unavailable)
    monkeypatch.setattr(app_identity, "resolve_app_id", unavailable)

    assert (
        cli.main(
            [
                "--app-id",
                "steam",
                "--delay",
                "0",
                "--allow-unverified-target",
            ]
        )
        == 0
    )

    assert input_adapter.operations == [("type", "test")]
    assert "could not be verified" in capsys.readouterr().err


def test_cli_handles_unsafe_or_unavailable_input_without_echoing_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    service = FakeService()
    monkeypatch.setattr(cli, "BitwardenCLI", lambda _: object())
    monkeypatch.setattr(
        cli, "authenticate_vault", lambda _client, *, email=None: service
    )

    def resolve(explicit_app_id: str | None = None, **_: object) -> str:
        return explicit_app_id or "steam"

    monkeypatch.setattr(cli, "resolve_app_id", resolve)
    monkeypatch.setattr(app_identity, "resolve_app_id", resolve)
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
        *,
        before_input: object = None,
    ) -> FillResult:
        if callable(before_input):
            before_input()
        adapter.type_text("trigger")
        raise AssertionError("Input adapter should have raised an error")

    monkeypatch.setattr(cli, "fill_for_app", fail_input)

    assert cli.main(["--app-id", "steam", "--delay", "0"]) == 1

    assert service.closed
    assert "Wayland permission denied" in capsys.readouterr().err


def test_cli_sanitizes_cli_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_resolve(_: str, **_kwargs: object) -> str:
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
