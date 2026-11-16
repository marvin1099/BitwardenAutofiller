from collections.abc import Sequence

import pytest

from bitwarden_autofiller.desktop.platforms import LazyInputAdapter
from bitwarden_autofiller.filling.actions import Action, parse_action_sequence
from bitwarden_autofiller.filling.execution import (
    PartialFillError,
    execute_fill_actions,
)
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


def test_active_app_check_runs_immediately_before_each_input_operation() -> None:
    events: list[str] = []

    class OrderedInput(RecordingInput):
        def type_text(self, text: str) -> None:
            events.append("type")
            super().type_text(text)

        def press_key(self, key: str) -> None:
            events.append("key")
            super().press_key(key)

    def verify_focus() -> None:
        events.append("verify")

    execute_fill_actions(
        LoginCredentials("login-1", username="alice"),
        parse_action_sequence("147"),
        OrderedInput(),
        before_input=verify_focus,
    )

    assert events == ["verify", "type", "verify", "key"]


def test_clipboard_copy_does_not_require_active_window_verification() -> None:
    input_adapter = RecordingInput()

    def unexpected_verification() -> None:
        raise AssertionError("Clipboard copies do not target the focused app")

    execute_fill_actions(
        LoginCredentials("login-1", username="alice"),
        parse_action_sequence("15"),
        input_adapter,
        before_input=unexpected_verification,
    )

    assert input_adapter.operations == [("copy", "alice")]


def test_lazy_input_backend_is_prepared_before_focus_verification() -> None:
    events: list[str] = []

    class PreparedInput:
        def type_text(self, _text: str) -> None:
            events.append("type")

        def press_key(self, _key: str) -> None:
            events.append("key")

        def copy_text(self, _text: str) -> None:
            events.append("copy")

    def create_input() -> PreparedInput:
        events.append("prepare")
        return PreparedInput()

    execute_fill_actions(
        LoginCredentials("login-1", username="alice"),
        parse_action_sequence("14"),
        LazyInputAdapter(create_input),
        before_input=lambda: events.append("verify"),
    )

    assert events == ["prepare", "verify", "type"]


def test_focus_change_after_input_reports_that_fill_may_be_partial() -> None:
    input_adapter = RecordingInput()
    checks = 0

    def verify_focus() -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise RuntimeError("focus changed")

    with pytest.raises(PartialFillError) as raised:
        execute_fill_actions(
            LoginCredentials("login-1", username="alice"),
            parse_action_sequence("147"),
            input_adapter,
            before_input=verify_focus,
        )

    assert raised.value.completed_operations == 1
    assert raised.value.attempted_operations == 1
    assert "Earlier fields" in str(raised.value)
    assert "Check the target before retrying" in str(raised.value)
    assert input_adapter.operations == [("type", "alice")]


def test_first_focus_check_failure_does_not_claim_input_was_sent() -> None:
    input_adapter = RecordingInput()

    def unavailable() -> None:
        raise RuntimeError("active app unavailable")

    with pytest.raises(RuntimeError, match="active app unavailable"):
        execute_fill_actions(
            LoginCredentials("login-1", username="alice"),
            parse_action_sequence("14"),
            input_adapter,
            before_input=unavailable,
        )

    assert input_adapter.operations == []
