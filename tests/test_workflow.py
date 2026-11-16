import pytest

from bitwarden_autofiller.filling.actions import parse_action_sequence
from bitwarden_autofiller.filling.workflow import fill_for_app, fill_selected_login
from bitwarden_autofiller.vault.items import LoginCredentials, LoginSummary


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.logins: tuple[LoginSummary, ...] = (
            LoginSummary("first", "First", "alice", ("pcprocess://app",)),
            LoginSummary("second", "Second", "bob", ("pcprocess://app",)),
        )

    def list_matches(self, app_id: str) -> tuple[LoginSummary, ...]:
        self.calls.append(("list", app_id))
        return self.logins

    def get_login(self, app_id: str, item_id: str) -> LoginCredentials:
        self.calls.append(("get", item_id))
        return LoginCredentials(
            item_id, username=f"user-{item_id}", password=f"password-{item_id}"
        )

    def get_totp(self, app_id: str, item_id: str) -> str:
        self.calls.append(("totp", item_id))
        return "123456"


class FakeInput:
    def __init__(self) -> None:
        self.operations: list[tuple[str, str]] = []

    def type_text(self, text: str) -> None:
        self.operations.append(("type", text))

    def press_key(self, key: str) -> None:
        self.operations.append(("key", key))

    def copy_text(self, text: str) -> None:
        self.operations.append(("copy", text))


def test_workflow_fetches_only_the_items_selected_by_action_groups() -> None:
    service = FakeService()
    input_adapter = FakeInput()

    result = fill_for_app(
        service,
        "app",
        parse_action_sequence("14A24"),
        input_adapter,
    )

    assert result.matched_items == 2
    assert result.selected_items == 2
    assert result.input_operations == 2
    assert service.calls == [("list", "app"), ("get", "second")]
    assert input_adapter.operations == [
        ("type", "alice"),
        ("type", "password-second"),
    ]


def test_workflow_uses_summary_username_without_fetching_full_item() -> None:
    service = FakeService()
    input_adapter = FakeInput()

    result = fill_for_app(service, "app", parse_action_sequence("14"), input_adapter)

    assert result.input_operations == 1
    assert service.calls == [("list", "app")]
    assert input_adapter.operations == [("type", "alice")]


def test_selected_login_workflow_fills_only_the_requested_match() -> None:
    service = FakeService()
    input_adapter = FakeInput()

    result = fill_selected_login(
        service,
        "app",
        "second",
        parse_action_sequence("24"),
        input_adapter,
    )

    assert result.matched_items == 2
    assert result.selected_items == 1
    assert service.calls == [("list", "app"), ("get", "second")]
    assert input_adapter.operations == [("type", "password-second")]


def test_selected_login_workflow_rejects_a_stale_or_unmapped_item() -> None:
    service = FakeService()

    with pytest.raises(ValueError, match="no longer mapped"):
        fill_selected_login(
            service,
            "app",
            "missing",
            parse_action_sequence("14"),
            FakeInput(),
        )


def test_workflow_has_no_side_effects_when_no_items_match() -> None:
    service = FakeService()
    service.logins = ()
    input_adapter = FakeInput()

    result = fill_for_app(service, "app", parse_action_sequence("147"), input_adapter)

    assert result.matched_items == 0
    assert result.selected_items == 0
    assert input_adapter.operations == []
