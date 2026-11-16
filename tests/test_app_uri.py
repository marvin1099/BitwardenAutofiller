import pytest

from bitwarden_autofiller.app_uri import (
    AppUriError,
    application_id_from_uri,
    build_app_uri,
    normalize_app_id,
    parse_app_uri,
    profile_actions_for_uris,
)
from bitwarden_autofiller.filling.actions import parse_action_sequence


def test_profile_uri_round_trips_app_id_and_actions() -> None:
    uri = build_app_uri("Steam", "147")

    assert uri == "pcprocess://steam?actions=147"
    assert parse_app_uri(uri).app_id == "steam"
    assert parse_app_uri(uri).actions == parse_action_sequence("147")


def test_plain_legacy_uri_has_no_profile() -> None:
    profile = parse_app_uri("pcprocess://steam/")

    assert profile.app_id == "steam"
    assert profile.actions is None


def test_full_mapping_uri_normalizes_to_its_application_id() -> None:
    uri = "pcprocess://Steam?actions=147"

    assert application_id_from_uri(uri) == "steam"
    assert normalize_app_id(uri) == "steam"


@pytest.mark.parametrize(
    "uri",
    (
        "https://example.test?actions=147",
        "pcprocess://steam?unknown=value",
        "pcprocess://steam?actions=14&actions=24",
        "pcprocess://steam?actions=not-an-action",
        "pcprocess://steam?actions=",
        "pcprocess://steam?missing-equals",
    ),
)
def test_invalid_profile_uris_are_rejected(uri: str) -> None:
    with pytest.raises(AppUriError):
        parse_app_uri(uri)


def test_profile_lookup_uses_only_uris_for_the_requested_app() -> None:
    uris = (
        "pcprocess://mail?actions=14",
        "pcprocess://steam?actions=147",
    )

    assert profile_actions_for_uris(uris, "steam") == parse_action_sequence("147")
    assert profile_actions_for_uris(uris, "unknown") is None


def test_conflicting_profiles_for_the_same_app_are_rejected() -> None:
    with pytest.raises(AppUriError, match="Conflicting"):
        profile_actions_for_uris(
            ("pcprocess://steam?actions=14", "pcprocess://steam?actions=24"),
            "steam",
        )
