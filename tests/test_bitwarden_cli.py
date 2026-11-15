import json
import sys
from pathlib import Path

import pytest

from bitwarden_autofiller.vault.bitwarden import BitwardenCLI, BitwardenCLIError


@pytest.fixture
def fake_bw(tmp_path: Path) -> tuple[list[str], Path, Path]:
    executable = tmp_path / "fake_bw.py"
    log_path = tmp_path / "invocation.json"
    executable.write_text(
        "import json, os, sys\n"
        "with open(os.environ['BW_TEST_LOG'], 'w') as log:\n"
        "    json.dump({'argv': sys.argv[1:], 'password': "
        "os.environ.get('BW_AUTOFILLER_MASTER_PASSWORD'), 'session': "
        "os.environ.get('BW_SESSION')}, log)\n"
        "if os.environ.get('BW_TEST_FAIL'):\n"
        "    print('sensitive-looking CLI output')\n"
        "    raise SystemExit(3)\n"
        "print(json.dumps({'success': True, 'data': {'raw': 'test-session'}}))\n",
        encoding="utf-8",
    )
    return [sys.executable, str(executable)], log_path, executable


def test_login_uses_passwordenv_not_a_password_argument(
    fake_bw: tuple[list[str], Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    command, log_path, _ = fake_bw
    monkeypatch.setenv("BW_TEST_LOG", str(log_path))
    monkeypatch.setenv("BW_SESSION", "parent-session-must-not-be-used")
    client = BitwardenCLI(command)

    assert client.login("user@example.test", "correct horse battery staple") == (
        "test-session"
    )
    recorded = json.loads(log_path.read_text(encoding="utf-8"))
    assert "correct horse battery staple" not in recorded["argv"]
    assert recorded["password"] == "correct horse battery staple"
    assert recorded["session"] is None
    assert "--passwordenv" in recorded["argv"]


def test_session_key_is_passed_through_environment(
    fake_bw: tuple[list[str], Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    command, log_path, _ = fake_bw
    monkeypatch.setenv("BW_TEST_LOG", str(log_path))
    monkeypatch.setenv("BW_AUTOFILLER_MASTER_PASSWORD", "parent-secret-must-not-leak")
    client = BitwardenCLI(command)

    client.command(["list", "items"], session_key="session-never-in-argv")
    recorded = json.loads(log_path.read_text(encoding="utf-8"))
    assert recorded["session"] == "session-never-in-argv"
    assert recorded["password"] is None
    assert "session-never-in-argv" not in recorded["argv"]


def test_cli_errors_do_not_echo_subprocess_output_or_secrets(
    fake_bw: tuple[list[str], Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    command, log_path, _ = fake_bw
    monkeypatch.setenv("BW_TEST_LOG", str(log_path))
    monkeypatch.setenv("BW_TEST_FAIL", "1")
    client = BitwardenCLI(command)

    with pytest.raises(BitwardenCLIError) as raised:
        client.command(["status"])

    assert "sensitive-looking" not in str(raised.value)
