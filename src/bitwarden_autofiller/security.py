"""Small helpers for protecting local daemon credentials."""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path


class CredentialFileError(RuntimeError):
    """The daemon authentication token could not be stored safely."""


def load_or_create_auth_token(path: Path) -> str:
    """Read or atomically create a 256-bit token with owner-only permissions."""
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        path.parent.chmod(0o700)

    try:
        file_descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        return _read_existing_token(path)
    except OSError as error:
        raise CredentialFileError("Unable to create daemon token file") from error

    token = secrets.token_urlsafe(32)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as token_file:
            token_file.write(token)
    except OSError as error:
        path.unlink(missing_ok=True)
        raise CredentialFileError("Unable to write daemon token file") from error
    return token


def read_auth_token(path: Path) -> str:
    """Read a pre-existing, owner-only daemon token without creating one."""
    return _read_existing_token(Path(path))


def _read_existing_token(path: Path) -> str:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise CredentialFileError("Daemon token path must be a regular file")
        if os.name != "nt" and stat.S_IMODE(metadata.st_mode) & 0o077:
            raise CredentialFileError(
                "Daemon token file permissions must be owner-only (0600)"
            )
        token = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise CredentialFileError("Unable to read daemon token file") from error
    if len(token) < 32:
        raise CredentialFileError("Daemon token must contain at least 32 characters")
    return token
