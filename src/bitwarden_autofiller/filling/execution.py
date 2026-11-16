"""Execute validated fill actions through an injected desktop input adapter."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from bitwarden_autofiller.filling.actions import Action
from bitwarden_autofiller.vault.items import LoginCredentials


class InputAdapter(Protocol):
    """Small interface implemented by desktop-specific input backends."""

    def type_text(self, text: str) -> None: ...

    def press_key(self, key: str) -> None: ...

    def copy_text(self, text: str) -> None: ...


TotpProvider = Callable[[], str]


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
    for action in actions:
        if action is Action.USERNAME:
            selected_value = credentials.username
        elif action is Action.PASSWORD:
            selected_value = credentials.password
        elif action is Action.TOTP:
            selected_value = totp_provider() if totp_provider is not None else None
        elif action is Action.TYPE:
            if selected_value:
                _verify_before_input(input_adapter, before_input)
                input_adapter.type_text(selected_value)
                performed += 1
        elif action is Action.COPY:
            if selected_value:
                input_adapter.copy_text(selected_value)
                performed += 1
        elif action is Action.ENTER:
            _verify_before_input(input_adapter, before_input)
            input_adapter.press_key("Return")
            performed += 1
        elif action is Action.TAB:
            _verify_before_input(input_adapter, before_input)
            input_adapter.press_key("Tab")
            performed += 1
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
