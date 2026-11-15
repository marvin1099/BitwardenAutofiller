from bitwarden_autofiller.actions import Action, parse_action_sequence


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
