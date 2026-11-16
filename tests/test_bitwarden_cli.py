import json
import os
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
        "os.environ.get('BW_SESSION'), 'node_options': "
        "os.environ.get('NODE_OPTIONS'), 'extra_ca': "
        "os.environ.get('NODE_EXTRA_CA_CERTS')}, log)\n"
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


@pytest.mark.parametrize(
    ("initial_options", "use_system_ca", "expected_options"),
    (
        ("--trace-warnings", True, "--trace-warnings --use-system-ca"),
        ("--trace-warnings --use-system-ca", True, "--trace-warnings --use-system-ca"),
        ("--trace-warnings", False, "--trace-warnings"),
        ("", True, "--use-system-ca"),
    ),
)
def test_system_ca_option_preserves_existing_node_options(
    fake_bw: tuple[list[str], Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    initial_options: str,
    use_system_ca: bool,
    expected_options: str,
) -> None:
    command, log_path, _ = fake_bw
    monkeypatch.setenv("BW_TEST_LOG", str(log_path))
    if initial_options:
        monkeypatch.setenv("NODE_OPTIONS", initial_options)
    else:
        monkeypatch.delenv("NODE_OPTIONS", raising=False)

    BitwardenCLI(command, use_system_ca=use_system_ca).command(["status"])

    recorded = json.loads(log_path.read_text(encoding="utf-8"))
    assert recorded["node_options"] == expected_options
    assert os.environ.get("NODE_OPTIONS") == (initial_options or None)


def test_additional_ca_certificate_is_passed_to_bw_without_replacing_node_options(
    fake_bw: tuple[list[str], Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    command, log_path, _ = fake_bw
    certificate = tmp_path / "local-ca.pem"
    certificate.write_text("test certificate", encoding="utf-8")
    monkeypatch.setenv("BW_TEST_LOG", str(log_path))
    monkeypatch.setenv("NODE_OPTIONS", "--trace-warnings")
    monkeypatch.setenv("NODE_EXTRA_CA_CERTS", "/path/from/user/environment.pem")

    BitwardenCLI(command, ca_certificate=certificate).command(["status"])

    recorded = json.loads(log_path.read_text(encoding="utf-8"))
    assert recorded["node_options"] == "--trace-warnings --use-system-ca"
    assert recorded["extra_ca"] == str(certificate.resolve())


def test_nonexistent_additional_ca_certificate_is_rejected_safely(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="CA certificate file was not found"):
        BitwardenCLI(ca_certificate=tmp_path / "missing.pem")


def test_cli_errors_do_not_echo_subprocess_output_or_secrets(
    fake_bw: tuple[list[str], Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    command, log_path, _ = fake_bw
    monkeypatch.setenv("BW_TEST_LOG", str(log_path))
    monkeypatch.setenv("BW_TEST_FAIL", "1")
    client = BitwardenCLI(command)

    with (
        caplog.at_level("DEBUG", logger="bitwarden_autofiller"),
        pytest.raises(BitwardenCLIError) as raised,
    ):
        client.command(["status"])

    assert "sensitive-looking" not in str(raised.value)
    assert "sensitive-looking" not in caplog.text


def test_cli_debug_logs_omit_email_and_master_password(
    fake_bw: tuple[list[str], Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    command, log_path, _ = fake_bw
    monkeypatch.setenv("BW_TEST_LOG", str(log_path))

    with caplog.at_level("DEBUG", logger="bitwarden_autofiller"):
        BitwardenCLI(command).login(
            "private-account@example.test", "private-master-password"
        )

    assert "operation login" in caplog.text
    assert "private-account@example.test" not in caplog.text
    assert "private-master-password" not in caplog.text
