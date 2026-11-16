"""Execute validated fill actions through an injected desktop input adapter."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import partial
from typing import Protocol

from bitwarden_autofiller.filling.actions import Action
from bitwarden_autofiller.vault.items import LoginCredentials


class InputAdapter(Protocol):
    """Small interface implemented by desktop-specific input backends."""

    def type_text(self, text: str) -> None: ...

    def press_key(self, key: str) -> None: ...

    def copy_text(self, text: str) -> None: ...


TotpProvider = Callable[[], str]


class PartialFillError(RuntimeError):
    """An input sequence stopped after some fill actions may have completed."""

    def __init__(self, completed_operations: int, attempted_operations: int) -> None:
        self.completed_operations = completed_operations
        self.attempted_operations = attempted_operations
        if completed_operations == 0 and attempted_operations == 0:
            message = "Autofill was cancelled before input was sent."
        else:
            message = (
                "Autofill stopped after "
                f"{completed_operations} completed input operation(s)."
            )
            if attempted_operations > completed_operations:
                message += " The current operation may be partially applied."
            if completed_operations:
                message += " Earlier fields or clipboard contents may have changed."
            message += " Check the target before retrying."
        super().__init__(message)


def execute_fill_actions(
    credentials: LoginCredentials,
    actions: Sequence[Action],
    input_adapter: InputAdapter,
    *,
    totp_provider: TotpProvider | None = None,
    before_input: Callable[[], None] | None = None,
) -> int:
    """Apply actions in order, fetching TOTP only when explicitly requested.

    Returns the number of actual type/copy/key operations performed. Account
    navigation must be resolved by :func:`group_account_actions` first.
    """
    selected_value: str | None = None
    performed = 0
    attempted = 0

    def perform_input(
        operation: Callable[[], None], *, verify_focus: bool = True
    ) -> None:
        nonlocal attempted, performed
        if verify_focus:
            try:
                _verify_before_input(input_adapter, before_input)
            except Exception as error:
                if performed:
                    raise PartialFillError(performed, attempted) from error
                raise
        attempted += 1
        try:
            operation()
        except Exception as error:
            raise PartialFillError(performed, attempted) from error
        performed += 1

    for action in actions:
        if action is Action.USERNAME:
            selected_value = credentials.username
        elif action is Action.PASSWORD:
            selected_value = credentials.password
        elif action is Action.TOTP:
            selected_value = totp_provider() if totp_provider is not None else None
        elif action is Action.TYPE:
            if selected_value:
                perform_input(partial(input_adapter.type_text, selected_value))
        elif action is Action.COPY:
            if selected_value:
                perform_input(
                    partial(input_adapter.copy_text, selected_value),
                    verify_focus=False,
                )
        elif action is Action.ENTER:
            perform_input(lambda: input_adapter.press_key("Return"))
        elif action is Action.TAB:
            perform_input(lambda: input_adapter.press_key("Tab"))
        else:
            raise ValueError(
                "Account navigation actions must be resolved before execution"
            )
    return performed


def _verify_before_input(
    input_adapter: InputAdapter, before_input: Callable[[], None] | None
) -> None:
    if before_input is None:
        return
    # Lazy desktop adapters may open a portal permission prompt while being
    # initialized. Prepare first so focus is checked after that interaction.
    prepare = getattr(input_adapter, "prepare", None)
    if callable(prepare):
        prepare()
    before_input()
