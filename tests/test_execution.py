from collections.abc import Sequence

from bitwarden_autofiller.filling.actions import Action, parse_action_sequence
from bitwarden_autofiller.filling.execution import execute_fill_actions
from bitwarden_autofiller.vault.items import LoginCredentials


class RecordingInput:
    def __init__(self) -> None:
        self.operations: list[tuple[str, str]] = []

    def type_text(self, text: str) -> None:
        self.operations.append(("type", text))

    def press_key(self, key: str) -> None:
        self.operations.append(("key", key))

    def copy_text(self, text: str) -> None:
        self.operations.append(("copy", text))


def test_fill_sequence_types_selected_fields_and_copies_requested_totp() -> None:
    input_adapter = RecordingInput()
    totp_calls: list[str] = []

    def get_totp() -> str:
        totp_calls.append("requested")
        return "123456"

    operations = execute_fill_actions(
        LoginCredentials(
            "login-1",
            username="alice",
            password="secret",
            totp="otpauth://secret-not-a-current-code",
        ),
        parse_action_sequence("14724635"),
        input_adapter,
        totp_provider=get_totp,
    )

    assert operations == 5
    assert input_adapter.operations == [
        ("type", "alice"),
        ("key", "Tab"),
        ("type", "secret"),
        ("key", "Return"),
        ("copy", "123456"),
    ]
    assert totp_calls == ["requested"]


def test_totp_is_not_retrieved_unless_the_action_requests_it() -> None:
    input_adapter = RecordingInput()
    totp_calls: list[str] = []

    def get_totp() -> str:
        totp_calls.append("called")
        return "654321"

    execute_fill_actions(
        LoginCredentials("login-1", username="alice", totp="otpauth://secret"),
        (Action.USERNAME, Action.TYPE),
        input_adapter,
        totp_provider=get_totp,
    )

    assert totp_calls == []
    assert input_adapter.operations == [("type", "alice")]


def test_missing_fields_do_not_emit_input_events() -> None:
    input_adapter = RecordingInput()
    actions: Sequence[Action] = (
        Action.USERNAME,
        Action.TYPE,
        Action.PASSWORD,
        Action.COPY,
    )

    assert (
        execute_fill_actions(LoginCredentials("login-1"), actions, input_adapter) == 0
    )
    assert input_adapter.operations == []
