"""Validated fill-action sequences used by the CLI and GUI."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class Action(StrEnum):
    """An operation in a user-configurable autofill sequence."""

    USERNAME = "1"
    PASSWORD = "2"
    TOTP = "3"
    TYPE = "4"
    COPY = "5"
    ENTER = "6"
    TAB = "7"
    NEXT = "A"
    PREVIOUS = "B"
    FIRST = "C"
    LAST = "D"


@dataclass(frozen=True, slots=True)
class AccountActionGroup:
    """Actions to run against one selected account summary."""

    account_index: int
    actions: tuple[Action, ...]


def parse_action_sequence(value: str) -> tuple[Action, ...]:
    """Parse a legacy-compatible action string and reject invalid commands."""
    actions: list[Action] = []
    for character in value.upper():
        if character.isspace():
            continue
        try:
            actions.append(Action(character))
        except ValueError as error:
            raise ValueError(f"Unknown fill action: {character!r}") from error

    if not actions:
        raise ValueError("Fill action sequence cannot be empty")
    return tuple(actions)


DEFAULT_ACTIONS = parse_action_sequence("C14724635")


def group_account_actions(
    actions: Sequence[Action], account_count: int
) -> tuple[AccountActionGroup, ...]:
    """Partition an action sequence around account navigation commands.

    Selection begins at the first matching login. A/B move cyclically through
    the matches, while C/D select the first/last one. Navigation closes the
    pending action group, so later actions can be applied to another login.
    """
    if account_count < 0:
        raise ValueError("Account count cannot be negative")
    if account_count == 0:
        return ()

    selected = 0
    pending: list[Action] = []
    groups: list[AccountActionGroup] = []
    for action in actions:
        if action not in {
            Action.NEXT,
            Action.PREVIOUS,
            Action.FIRST,
            Action.LAST,
        }:
            pending.append(action)
            continue

        if pending:
            groups.append(AccountActionGroup(selected, tuple(pending)))
            pending.clear()

        if action is Action.NEXT:
            selected = (selected + 1) % account_count
        elif action is Action.PREVIOUS:
            selected = (selected - 1) % account_count
        elif action is Action.FIRST:
            selected = 0
        else:
            selected = account_count - 1

    if pending:
        groups.append(AccountActionGroup(selected, tuple(pending)))
    return tuple(groups)
