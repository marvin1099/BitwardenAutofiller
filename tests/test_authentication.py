from typing import Any

from bitwarden_autofiller.authentication import authenticate_vault
from bitwarden_autofiller.service import VaultService


class FakeBitwardenCLI:
    def __init__(self, status: str) -> None:
        self.current_status = status
        self.unlock_password: str | None = None
        self.login_credentials: tuple[str, str] | None = None

    def status(self) -> dict[str, Any]:
        return {
            "success": True,
            "data": {"template": {"status": self.current_status}},
        }

    def command(self, arguments: list[str], *, session_key: str) -> dict[str, Any]:
        raise AssertionError(f"Unexpected vault command: {arguments!r}")

    def unlock(self, password: str) -> str:
        self.unlock_password = password
        return "session-from-unlock"

    def login(self, email: str, password: str) -> str:
        self.login_credentials = (email, password)
        return "session-from-login"


def test_locked_vault_is_unlocked_without_prompting_for_email() -> None:
    cli = FakeBitwardenCLI("locked")

    service = authenticate_vault(
        cli,
        email="alice@example.test",
        password=None,
        password_prompt=lambda _: "user-entered-password",
    )

    assert isinstance(service, VaultService)
    assert cli.unlock_password == "user-entered-password"
    assert cli.login_credentials is None


def test_unauthenticated_vault_prompts_for_both_credentials() -> None:
    cli = FakeBitwardenCLI("unauthenticated")
    prompts: list[str] = []

    def prompt_email(message: str) -> str:
        prompts.append(message)
        return "alice@example.test"

    def prompt_password(message: str) -> str:
        prompts.append(message)
        return "user-entered-password"

    service = authenticate_vault(
        cli,
        prompt_email=prompt_email,
        password_prompt=prompt_password,
    )

    assert isinstance(service, VaultService)
    assert cli.login_credentials == (
        "alice@example.test",
        "user-entered-password",
    )
    assert len(prompts) == 2
