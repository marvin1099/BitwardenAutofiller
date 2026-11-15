"""Validated fill-action sequences used by the CLI and GUI."""

from __future__ import annotations

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
