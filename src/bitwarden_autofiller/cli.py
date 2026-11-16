"""Command-line entry point for one-shot desktop autofill."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from bitwarden_autofiller import __version__
from bitwarden_autofiller.app_uri import (
    AppUriError,
    build_app_uri,
    profile_actions_for_uris,
)
from bitwarden_autofiller.daemon.cli import default_token_path
from bitwarden_autofiller.daemon.daemon import DaemonClient, DaemonRequestError
from bitwarden_autofiller.daemon.remote import RemoteVaultService
from bitwarden_autofiller.daemon.security import CredentialFileError, read_auth_token
from bitwarden_autofiller.desktop.app_identity import (
    ActiveApplicationUnavailable,
    ActiveApplicationVerifier,
    resolve_app_id,
)
from bitwarden_autofiller.desktop.platforms import (
    InputBackendError,
    LazyInputAdapter,
    create_input_adapter,
)
from bitwarden_autofiller.filling.actions import DEFAULT_ACTIONS, parse_action_sequence
from bitwarden_autofiller.filling.workflow import (
    FillService,
    fill_for_app,
    fill_selected_login,
)
from bitwarden_autofiller.logging_config import configure_logging
from bitwarden_autofiller.vault.authentication import (
    AuthenticationError,
    authenticate_vault,
)
from bitwarden_autofiller.vault.bitwarden import BitwardenCLI, BitwardenCLIError


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
            "(auto-detected where the compositor supports it)"
        ),
    )
    parser.add_argument(
        "--active-app-command",
        metavar="COMMAND",
        help=(
            "Trusted shell command that prints the active window PID; its process "
            "name is used as the app ID when auto-detecting"
        ),
    )
    parser.add_argument(
        "--allow-unverified-target",
        action="store_true",
        help=(
            "Allow filling if active-window detection is unavailable; a warning "
            "is printed before input"
        ),
    )
    parser.add_argument(
        "--actions",
        help=("Override the mapped URI profile; defaults to that profile or C14724635"),
    )
    parser.add_argument(
        "--generate-uri",
        action="store_true",
        help="Generate a Bitwarden pcprocess:// URI instead of filling",
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
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        help="Safe diagnostic log level (default: INFO)",
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
    configure_logging(args.log_level)
    try:
        if args.generate_uri:
            if not args.app_id:
                raise AppUriError("--generate-uri requires --app-id")
            generated_actions = (
                parse_action_sequence(args.actions)
                if args.actions is not None
                else DEFAULT_ACTIONS
            )
            print(build_app_uri(args.app_id, generated_actions))
            return 0

        app_id = (
            resolve_app_id(args.app_id, active_app_command=args.active_app_command)
            if args.app_id
            else None
        )
        actions = (
            parse_action_sequence(args.actions) if args.actions is not None else None
        )
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
            if app_id is None:
                print(
                    "Focus the target application; detecting its app ID in "
                    f"{args.delay:g} seconds."
                )
                if args.delay:
                    time.sleep(args.delay)
                app_id = resolve_app_id(active_app_command=args.active_app_command)
            matches = service.list_matches(app_id)
            if not matches:
                print(
                    f"No Bitwarden login is mapped to pcprocess://{app_id}.",
                    file=sys.stderr,
                )
                return 1

            if args.app_id:
                print(
                    f"Found {len(matches)} matching login(s). "
                    "Focus the target application; "
                    f"sending input in {args.delay:g} seconds."
                )
                if args.delay:
                    time.sleep(args.delay)
            else:
                print(f"Found {len(matches)} matching login(s); sending input now.")
            adapter = LazyInputAdapter(create_input_adapter)
            verifier = ActiveApplicationVerifier(
                app_id,
                active_app_command=args.active_app_command,
                allow_unverified=args.allow_unverified_target,
                on_unverified=lambda: print(
                    "Warning: active application could not be verified; "
                    "sending input to the focused window anyway.",
                    file=sys.stderr,
                ),
            )
            try:
                if actions is not None:
                    result = fill_for_app(
                        service,
                        app_id,
                        actions,
                        adapter,
                        before_input=verifier.verify,
                    )
                else:
                    profile_actions = profile_actions_for_uris(matches[0].uris, app_id)
                    if profile_actions is None:
                        result = fill_for_app(
                            service,
                            app_id,
                            DEFAULT_ACTIONS,
                            adapter,
                            before_input=verifier.verify,
                        )
                    else:
                        result = fill_selected_login(
                            service,
                            app_id,
                            matches[0].id,
                            profile_actions,
                            adapter,
                            before_input=verifier.verify,
                        )
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
