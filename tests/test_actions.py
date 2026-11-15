from bitwarden_autofiller.filling.actions import (
    Action,
    group_account_actions,
    parse_action_sequence,
)


def test_documented_fill_sequence_has_stable_meaning() -> None:
    assert parse_action_sequence("C14724635") == (
        Action.FIRST,
        Action.USERNAME,
        Action.TYPE,
        Action.TAB,
        Action.PASSWORD,
        Action.TYPE,
        Action.ENTER,
        Action.TOTP,
        Action.COPY,
    )


def test_fill_sequence_is_case_insensitive_and_ignores_spacing() -> None:
    assert parse_action_sequence(" c 1 a ") == (
        Action.FIRST,
        Action.USERNAME,
        Action.NEXT,
    )


def test_fill_sequence_rejects_unknown_actions() -> None:
    try:
        parse_action_sequence("1?")
    except ValueError as error:
        assert "?" in str(error)
    else:
        raise AssertionError("Unknown fill actions must be rejected")


def test_default_sequence_selects_the_first_account_and_keeps_fill_order() -> None:
    groups = group_account_actions(parse_action_sequence("C14724635"), 3)

    assert len(groups) == 1
    assert groups[0].account_index == 0
    assert groups[0].actions == (
        Action.USERNAME,
        Action.TYPE,
        Action.TAB,
        Action.PASSWORD,
        Action.TYPE,
        Action.ENTER,
        Action.TOTP,
        Action.COPY,
    )


def test_navigation_splits_fill_actions_between_selected_accounts() -> None:
    groups = group_account_actions(parse_action_sequence("1A2D3"), 3)

    assert [(group.account_index, group.actions) for group in groups] == [
        (0, (Action.USERNAME,)),
        (1, (Action.PASSWORD,)),
        (2, (Action.TOTP,)),
    ]


def test_navigation_wraps_and_empty_vault_has_no_groups() -> None:
    assert group_account_actions(parse_action_sequence("B1"), 3)[0].account_index == 2
    assert group_account_actions(parse_action_sequence("1"), 0) == ()
