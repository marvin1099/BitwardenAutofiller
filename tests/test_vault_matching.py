from bitwarden_autofiller.vault.items import (
    LoginSummary,
    credentials_from_response,
    matching_logins,
    summaries_from_response,
)


def test_matching_is_exact_case_insensitive_and_keeps_vault_order() -> None:
    entries = [
        LoginSummary("1", "Steam personal", "alice", ("pcprocess://steam",)),
        LoginSummary("2", "Browser", "bob", ("https://steamcommunity.com",)),
        LoginSummary("3", "Steam work", "carol", ("PCPROCESS://STEAM",)),
    ]

    assert matching_logins(entries, "steam") == (entries[0], entries[2])


def test_matching_does_not_treat_substrings_as_app_matches() -> None:
    entry = LoginSummary("1", "Steam", "alice", ("pcprocess://steam",))

    assert matching_logins((entry,), "steam-beta") == ()


def test_login_summary_repr_does_not_disclose_username() -> None:
    summary = LoginSummary("1", "Private entry", "alice", ("pcprocess://app",))

    assert "alice" not in repr(summary)


def test_items_response_exposes_only_login_summaries() -> None:
    response = {
        "success": True,
        "data": {
            "data": [
                {
                    "id": "1",
                    "type": 1,
                    "name": "Private entry",
                    "login": {
                        "username": "alice",
                        "password": "never-retain-this",
                        "uris": [{"uri": "pcprocess://app"}],
                    },
                },
                {"id": "2", "type": 2, "name": "Secure note"},
            ]
        },
    }

    summaries = summaries_from_response(response)

    assert summaries == (
        LoginSummary("1", "Private entry", "alice", ("pcprocess://app",)),
    )
    assert "never-retain-this" not in repr(summaries)


def test_selected_item_response_returns_one_secret_record() -> None:
    credentials = credentials_from_response(
        {
            "success": True,
            "data": {
                "data": {
                    "id": "1",
                    "login": {
                        "username": "alice",
                        "password": "secret-value",
                        "totp": "otpauth://totp/example",
                    },
                }
            },
        }
    )

    assert credentials.id == "1"
    assert credentials.password == "secret-value"
    assert "secret-value" not in repr(credentials)
