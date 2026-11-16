"""Orchestrate app matching, selected-item retrieval, and fill execution."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from bitwarden_autofiller.filling.actions import Action, group_account_actions
from bitwarden_autofiller.filling.execution import InputAdapter, execute_fill_actions
from bitwarden_autofiller.vault.items import (
    LoginCredentials,
    LoginSummary,
)

_LOGGER = logging.getLogger(__name__)


class FillService(Protocol):
    """The vault operations required by one fill workflow."""

    def list_matches(self, app_id: str) -> Sequence[LoginSummary]: ...

    def get_login(self, app_id: str, item_id: str) -> LoginCredentials: ...

    def get_totp(self, app_id: str, item_id: str) -> str: ...


@dataclass(frozen=True, slots=True)
class FillResult:
    """Secret-free summary of a fill attempt."""

    matched_items: int
    selected_items: int
    input_operations: int


def fill_for_app(
    service: FillService,
    app_id: str,
    actions: Sequence[Action],
    input_adapter: InputAdapter,
) -> FillResult:
    """Fill only explicitly mapped items, retrieving one item's secrets at a time."""
    matches = tuple(service.list_matches(app_id))
    return _fill_matches(
        service,
        app_id,
        matches,
        actions,
        input_adapter,
        matched_items=len(matches),
    )


def fill_selected_login(
    service: FillService,
    app_id: str,
    item_id: str,
    actions: Sequence[Action],
    input_adapter: InputAdapter,
) -> FillResult:
    """Fill one login only if it still matches the active application."""
    matches = tuple(service.list_matches(app_id))
    summary = next((item for item in matches if item.id == item_id), None)
    if summary is None:
        raise ValueError("The selected login is no longer mapped to this application")
    return _fill_matches(
        service,
        app_id,
        (summary,),
        actions,
        input_adapter,
        matched_items=len(matches),
    )


def _fill_matches(
    service: FillService,
    app_id: str,
    matches: tuple[LoginSummary, ...],
    actions: Sequence[Action],
    input_adapter: InputAdapter,
    *,
    matched_items: int,
) -> FillResult:
    groups = group_account_actions(actions, len(matches))
    selected_items = 0
    input_operations = 0

    for group in groups:
        summary = matches[group.account_index]
        credentials = (
            service.get_login(app_id, summary.id)
            if _needs_password(group.actions)
            else LoginCredentials(summary.id, username=summary.username)
        )

        def get_totp(item_id: str = summary.id) -> str:
            return service.get_totp(app_id, item_id)

        try:
            input_operations += execute_fill_actions(
                credentials,
                group.actions,
                input_adapter,
                totp_provider=get_totp,
            )
            selected_items += 1
        finally:
            del credentials

    result = FillResult(
        matched_items=matched_items,
        selected_items=selected_items,
        input_operations=input_operations,
    )
    _LOGGER.info(
        "Autofill completed for %d selected login(s) with %d input operation(s)",
        result.selected_items,
        result.input_operations,
    )
    return result


def _needs_password(actions: Sequence[Action]) -> bool:
    """Fetch a full item only if a selected password will be emitted."""
    selected_password = False
    for action in actions:
        if action is Action.PASSWORD:
            selected_password = True
        elif action in (Action.USERNAME, Action.TOTP):
            selected_password = False
        elif action in (Action.TYPE, Action.COPY) and selected_password:
            return True
    return False
