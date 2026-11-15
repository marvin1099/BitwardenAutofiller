import os
import stat
from pathlib import Path

import pytest

from bitwarden_autofiller.security import (
    CredentialFileError,
    load_or_create_auth_token,
)


def test_auth_token_is_random_persisted_and_owner_only(tmp_path: Path) -> None:
    token_path = tmp_path / "private" / "auth.token"

    token = load_or_create_auth_token(token_path)

    assert len(token) >= 40
    assert load_or_create_auth_token(token_path) == token
    if os.name != "nt":
        assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(token_path.parent.stat().st_mode) == 0o700


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits only")
def test_auth_token_rejects_group_or_world_readable_file(tmp_path: Path) -> None:
    token_path = tmp_path / "auth.token"
    token_path.write_text("sufficiently-long-test-token-value", encoding="utf-8")
    token_path.chmod(0o644)

    with pytest.raises(CredentialFileError, match="owner-only"):
        load_or_create_auth_token(token_path)
