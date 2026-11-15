"""Start or stop the authenticated Bitwarden vault daemon."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from platformdirs import user_config_path

from bitwarden_autofiller.authentication import authenticate_vault
from bitwarden_autofiller.bitwarden import BitwardenCLI, BitwardenCLIError
from bitwarden_autofiller.daemon import AutofillDaemon, DaemonClient, DaemonRequestError
from bitwarden_autofiller.security import (
    CredentialFileError,
    load_or_create_auth_token,
    read_auth_token,
)


def default_token_path() -> Path:
    """Return the private per-user configuration path for daemon auth."""
    return (
        Path(user_config_path("bitwarden-autofiller", appauthor=False)) / "daemon.token"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bitwarden-autofiller-daemon",
        description="Run or stop the authenticated Bitwarden Autofiller daemon.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="authenticate and serve vault requests")
    start.add_argument("--bw-path", type=Path, default=Path("bw"))
    start.add_argument("--email")
    start.add_argument("--host", default="127.0.0.1")
    start.add_argument("--port", type=_port, default=64756)
    start.add_argument("--token-file", type=Path, default=default_token_path())
    start.add_argument("--tls-certificate", type=Path)
    start.add_argument("--tls-private-key", type=Path)

    stop = commands.add_parser("stop", help="send an authenticated shutdown request")
    stop.add_argument("--host", default="127.0.0.1")
    stop.add_argument("--port", type=_port, default=64756)
    stop.add_argument("--token-file", type=Path, default=default_token_path())
    stop.add_argument("--ca-certificate", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "stop":
            token = read_auth_token(args.token_file)
            client = DaemonClient(
                args.host,
                args.port,
                token,
                ca_certificate=args.ca_certificate,
            )
            client.request("close")
            print("Authenticated shutdown request sent.")
            return 0

        service = authenticate_vault(BitwardenCLI(args.bw_path), email=args.email)
        try:
            token = load_or_create_auth_token(args.token_file)
            daemon = AutofillDaemon(
                service,
                token,
                host=args.host,
                port=args.port,
                tls_certificate=args.tls_certificate,
                tls_private_key=args.tls_private_key,
            )
            host, port = daemon.address
            print(f"Bitwarden Autofiller daemon listening on {host}:{port}.")
            try:
                daemon.serve_forever()
            except KeyboardInterrupt:
                print("Stopping Bitwarden Autofiller daemon.")
            finally:
                daemon.shutdown()
            return 0
        finally:
            service.close()
    except (
        BitwardenCLIError,
        CredentialFileError,
        DaemonRequestError,
        OSError,
        ValueError,
        RuntimeError,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


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
