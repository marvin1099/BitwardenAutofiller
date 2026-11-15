from pathlib import Path
from typing import Any

import pytest

from bitwarden_autofiller.daemon import cli as daemon_cli


class FakeService:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeDaemon:
    def __init__(self, *_: Any, **__: Any) -> None:
        self.address = ("127.0.0.1", 64756)
        self.served = False
        self.stopped = False

    def serve_forever(self) -> None:
        self.served = True

    def shutdown(self) -> None:
        self.stopped = True


def test_daemon_start_authenticates_and_closes_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    service = FakeService()
    daemon = FakeDaemon()
    monkeypatch.setattr(daemon_cli, "BitwardenCLI", lambda _: object())
    monkeypatch.setattr(
        daemon_cli, "authenticate_vault", lambda *_args, **_kwargs: service
    )
    monkeypatch.setattr(daemon_cli, "load_or_create_auth_token", lambda _: "a" * 40)
    monkeypatch.setattr(daemon_cli, "AutofillDaemon", lambda *_args, **_kwargs: daemon)

    result = daemon_cli.main(["start", "--token-file", str(tmp_path / "token")])

    assert result == 0
    assert daemon.served and daemon.stopped
    assert service.closed
    assert "127.0.0.1:64756" in capsys.readouterr().out


def test_daemon_stop_sends_authenticated_close_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, Any]] = []

    class Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            calls.append(("client", (args, kwargs)))

        def request(self, command: str) -> bool:
            calls.append(("request", command))
            return True

    monkeypatch.setattr(daemon_cli, "read_auth_token", lambda _: "private-token")
    monkeypatch.setattr(daemon_cli, "DaemonClient", Client)

    assert daemon_cli.main(["stop", "--token-file", str(tmp_path / "token")]) == 0
    assert calls[-1] == ("request", "close")


def test_daemon_cli_rejects_out_of_range_ports() -> None:
    with pytest.raises(SystemExit) as raised:
        daemon_cli.build_parser().parse_args(["start", "--port", "65536"])

    assert raised.value.code == 2
