"""Command-line entry point for one-shot desktop autofill."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from bitwarden_autofiller import __version__
from bitwarden_autofiller.actions import parse_action_sequence
from bitwarden_autofiller.app_identity import (
    ActiveApplicationUnavailable,
    resolve_app_id,
)
from bitwarden_autofiller.authentication import (
    AuthenticationError,
    authenticate_vault,
)
from bitwarden_autofiller.bitwarden import BitwardenCLI, BitwardenCLIError
from bitwarden_autofiller.daemon import DaemonClient, DaemonRequestError
from bitwarden_autofiller.daemon_cli import default_token_path
from bitwarden_autofiller.platforms import (
    InputBackendError,
    LazyInputAdapter,
    create_input_adapter,
)
from bitwarden_autofiller.remote import RemoteVaultService
from bitwarden_autofiller.security import CredentialFileError, read_auth_token
from bitwarden_autofiller.workflow import FillService, fill_for_app


class CLIService(FillService, Protocol):
    def sync(self) -> None: ...

    def close(self) -> None: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bitwarden-autofiller",
        description="Fill explicitly mapped desktop application logins from Bitwarden.",
    )
    parser.add_argument(
        "--app-id",
        help=(
            "Application ID used by the vault URI pcprocess://<app-id> "
            "(required on Wayland)"
        ),
    )
    parser.add_argument(
        "--actions",
        default="C14724635",
        help="Fill sequence (default: C14724635); see --help for action codes",
    )
    parser.add_argument(
        "--bw-path",
        default="bw",
        type=Path,
        help="Path to the official Bitwarden CLI (default: bw)",
    )
    parser.add_argument("--email", help="Bitwarden account email (never a password)")
    parser.add_argument(
        "--daemon-host",
        help="Use an authenticated daemon instead of the local Bitwarden CLI",
    )
    parser.add_argument("--daemon-port", type=_port, default=64756)
    parser.add_argument("--token-file", type=Path)
    parser.add_argument(
        "--ca-certificate",
        type=Path,
        help="Trusted CA certificate for a remote TLS daemon",
    )
    parser.add_argument(
        "--sync", action="store_true", help="Sync the vault before filling"
    )
    parser.add_argument(
        "--delay",
        type=_nonnegative_float,
        default=3.0,
        metavar="SECONDS",
        help="Seconds to wait before sending input (default: 3)",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.epilog = (
        "Actions: 1=username, 2=password, 3=current TOTP, 4=type, 5=copy, "
        "6=Enter, 7=Tab, A=next match, B=previous, C=first, D=last. "
        "The master password is prompted securely and is never accepted as an argument."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        app_id = resolve_app_id(args.app_id)
        actions = parse_action_sequence(args.actions)
        service: CLIService
        if args.daemon_host:
            token = read_auth_token(args.token_file or default_token_path())
            daemon_client = DaemonClient(
                args.daemon_host,
                args.daemon_port,
                token,
                ca_certificate=args.ca_certificate,
            )
            service = RemoteVaultService(daemon_client)
        else:
            if args.ca_certificate is not None:
                raise ValueError("--ca-certificate requires --daemon-host")
            service = authenticate_vault(BitwardenCLI(args.bw_path), email=args.email)
        try:
            if args.sync:
                service.sync()
            matches = service.list_matches(app_id)
            if not matches:
                print(
                    f"No Bitwarden login is mapped to pcprocess://{app_id}.",
                    file=sys.stderr,
                )
                return 1

            print(
                f"Found {len(matches)} matching login(s). "
                "Focus the target application; "
                f"sending input in {args.delay:g} seconds."
            )
            if args.delay:
                time.sleep(args.delay)
            adapter = LazyInputAdapter(create_input_adapter)
            try:
                result = fill_for_app(service, app_id, actions, adapter)
            finally:
                close = getattr(adapter, "close", None)
                if callable(close):
                    close()
            print(
                f"Completed {result.selected_items} selected login action group(s) "
                f"with {result.input_operations} input operation(s)."
            )
            return 0
        finally:
            service.close()
    except (
        ActiveApplicationUnavailable,
        AuthenticationError,
        BitwardenCLIError,
        CredentialFileError,
        DaemonRequestError,
        InputBackendError,
        ValueError,
        OSError,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


def _nonnegative_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a number") from error
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


if __name__ == "__main__":
    raise SystemExit(main())
