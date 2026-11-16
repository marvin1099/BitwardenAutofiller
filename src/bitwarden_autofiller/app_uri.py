"""Parse and generate application mapping URIs and fill profiles."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

from bitwarden_autofiller.filling.actions import (
    DEFAULT_ACTIONS,
    Action,
    parse_action_sequence,
)

APP_URI_SCHEME = "pcprocess://"
_PROFILE_PARAMETER = "actions"


class AppUriError(ValueError):
    """An app mapping or its optional fill profile is invalid."""


@dataclass(frozen=True, slots=True)
class AppUriProfile:
    """Parsed app ID and optional per-login action sequence."""

    app_id: str
    actions: tuple[Action, ...] | None = None


def normalize_app_id(value: str | None) -> str:
    """Normalize a plain app ID or full ``pcprocess://`` mapping URI."""
    if not value:
        return ""
    value = value.strip()
    if value.casefold().startswith(APP_URI_SCHEME):
        return application_id_from_uri(value) or ""
    return value.casefold().strip("/")


def application_id_from_uri(uri: str) -> str | None:
    """Extract the app ID while ignoring profile query parameters."""
    try:
        parsed = urlsplit(uri.strip())
    except ValueError:
        return None
    if parsed.scheme.casefold() != "pcprocess" or "@" in parsed.netloc:
        return None
    app_id = unquote(f"{parsed.netloc}{parsed.path}").strip().casefold().strip("/")
    return app_id or None


def parse_app_uri(uri: str) -> AppUriProfile:
    """Parse a mapping URI, rejecting unknown or duplicate profile parameters."""
    app_id = application_id_from_uri(uri)
    if app_id is None:
        raise AppUriError("Expected a pcprocess:// application URI")

    parsed = urlsplit(uri.strip())
    try:
        parameters = parse_qsl(
            parsed.query, keep_blank_values=True, strict_parsing=True
        )
    except ValueError as error:
        raise AppUriError("Malformed application URI parameters") from error

    actions: tuple[Action, ...] | None = None
    seen: set[str] = set()
    for name, value in parameters:
        if name != _PROFILE_PARAMETER:
            raise AppUriError(f"Unsupported application URI parameter: {name}")
        if name in seen:
            raise AppUriError("Application URI may contain only one actions parameter")
        seen.add(name)
        try:
            actions = parse_action_sequence(value)
        except ValueError as error:
            raise AppUriError(f"Invalid actions profile: {error}") from error

    return AppUriProfile(app_id, actions)


def profile_actions_for_uris(
    uris: Sequence[str], app_id: str
) -> tuple[Action, ...] | None:
    """Return the unique explicit profile mapped to an app, if one exists."""
    target = normalize_app_id(app_id)
    profiles = {
        profile.actions
        for uri in uris
        if application_id_from_uri(uri) == target
        if (profile := parse_app_uri(uri)).actions is not None
    }
    if len(profiles) > 1:
        raise AppUriError("Conflicting autofill profiles are mapped to this app")
    return next(iter(profiles), None)


def build_app_uri(
    app_id: str,
    actions: str | Sequence[Action] = DEFAULT_ACTIONS,
) -> str:
    """Build a Bitwarden-compatible mapping URI with a fill-action profile."""
    normalized_id = normalize_app_id(app_id)
    if not normalized_id:
        raise AppUriError("An application ID is required to generate a URI")
    try:
        sequence = (
            parse_action_sequence(actions)
            if isinstance(actions, str)
            else tuple(actions)
        )
        # Re-parse the serialized sequence so empty or non-action values fail
        # through the same validation path as user-entered action strings.
        action_text = "".join(action.value for action in sequence)
        sequence = parse_action_sequence(action_text)
    except (AttributeError, TypeError, ValueError) as error:
        raise AppUriError(f"Invalid actions profile: {error}") from error

    encoded_id = quote(normalized_id, safe="._-")
    query = urlencode(
        {_PROFILE_PARAMETER: "".join(action.value for action in sequence)}
    )
    return f"{APP_URI_SCHEME}{encoded_id}?{query}"
