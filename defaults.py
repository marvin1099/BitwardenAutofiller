#!/usr/bin/env python

import argparse


class Defaults:
    def __init__(self):
        self.bw_path = "bw"
        self.timeout = 3600
        self.host = "127.0.0.1"
        self.port = 64756
        self.fillactions = "C14724635"

    def args_processor(self, args=None):
        # Initialize argument parser
        parser = argparse.ArgumentParser(
            description="Bitwarden autofill tool"
        )

        # Server and connection related arguments
        parser.add_argument(
            "-s",
            "--serverurl",
            type=str,
            help="URL that Bitwarden uses (will be saved after its set once, for daemon)",
        )
        parser.add_argument(
            "-cf",
            "--certfile",
            type=str,
            help="Certificate file used if Bitwarden is self-signed (will exit / ask if not set and needed, can be set via env, for daemon)",
        )

        # Authentication related arguments
        parser.add_argument(
            "-p",
            "--password",
            type=str,
            help="Bitwarden vault password (for daemon)",
        )
        parser.add_argument(
            "-m",
            "--mail",
            type=str,
            help="Bitwarden vault email (for daemon)",
        )
        parser.add_argument(
            "-e",
            "--encryption",
            type=str,
            help="provide a addional server / client password for encryption to improve securrity",
        )

        parser.add_argument(
            "-d",
            "--daemonmode",
            action="store_true",
            help="Start daemon mode if possible (if not exit, enabled with clientmode by default)",
        )
        parser.add_argument(
            "-c",
            "--clientmode",
            action="store_true",
            help="Start client mode if possible (if not exit, enabled with daemonmode by default)",
        )
        parser.add_argument(
            "-nm",
            "--nomode",
            action="store_true",
            help="Do not start the daemon or the client (only prints argsetup)",
        )

        # Path and execution behavior
        parser.add_argument(
            "-bw",
            "--bitwardenclipath",
            type=str,
            help=f"Path to Bitwarden CLI (default '{self.bw_path}')",
            default=self.bw_path,
        )
        parser.add_argument(
            "-n",
            "--noblocking",
            action="store_true",
            help="Non-blocking / Non-interactive mode",
        )
        parser.add_argument(
            "-t",
            "--daemontimeout",
            type=int,
            help=f"Set daemon connection timeout in seconds (default '{self.timeout}', for daemon)",
        )

        # Local IP and port configuration for daemon
        parser.add_argument(
            "-ip",
            "--localip",
            type=str,
            help=f"Local IP address for the daemon server (default '{self.host}'",
            default=self.host,
        )
        parser.add_argument(
            "-lp",
            "--localport",
            type=int,
            help=f"Local port for the daemon server (default '{self.port}'",
            default=self.port,
        )

        # Filling and action configuration
        parser.add_argument(
            "-f",
            "--fillactions",
            type=str,
            help="Set fill actions (default: 'C14724635' is a sequence of actions: 1 user, 2 pass, 3 totp, 4 type, 5 copy, 6 newline, 7 tab, A next found account, B previus found account, C first found account, D last found account)",
            default=self.fillactions,
        )

        # Client-specific options
        parser.add_argument(
            "-x",
            "--closedaemon",
            action="store_true",
            help="Send close signal to the daemon (for client)",
        )
        parser.add_argument(
            "-y",
            "--sync",
            action="store_true",
            help="Sync Bitwarden vault (for client)",
        )

        # Parse the arguments; if args are provided, use them
        if args:
            parsed_args = parser.parse_args(args)
        else:
            parsed_args = parser.parse_args()

        something_printed = False

        if parsed_args.serverurl:
            print(f"Using server URL: {parsed_args.serverurl}")
            something_printed = True
            self.serverurl = parsed_args.serverurl
        else:
            self.serverurl = None

        if parsed_args.certfile:
            print(f"Using certificate file: {parsed_args.certfile}")
            something_printed = True
            self.certfile = parsed_args.certfile
        else:
            self.certfile = None

        if parsed_args.password:
            print(f"Using provided password")
            something_printed = True
            self.passw = parsed_args.password
        else:
            self.passw = None

        if parsed_args.mail:
            print(f"Using email: {parsed_args.mail}")
            something_printed = True
            self.mail = parsed_args.mail
        else:
            self.mail = None

        if parsed_args.encryption:
            print(f"Using addional provided password for encryption")
            something_printed = True
            self.encryption = parsed_args.encryption
        else:
            self.encryption = ""

        if parsed_args.daemonmode != parsed_args.clientmode:
            if parsed_args.daemonmode:
                print("Starting in daemon only mode...")
                something_printed = True
                self.daemonmode = True
                self.clientmode = False
            else:
                print("Starting in client only mode...")
                something_printed = True
                self.clientmode = True
                self.daemonmode = False
        elif parsed_args.daemonmode and parsed_args.clientmode:
            self.clientmode = True
            self.daemonmode = True
        elif parsed_args.nomode:
            self.clientmode = False
            self.daemonmode = False
        else:
            self.clientmode = True
            self.daemonmode = True

        if parsed_args.bitwardenclipath:
            if parsed_args.bitwardenclipath != self.bw_path:
                print(
                    f"Set bitwarden cli path to: {parsed_args.bitwardenclipath}"
                )
                something_printed = True
                self.bw_path = parsed_args.bitwardenclipath
        else:
            print(f"Error bitwarden cli path not set using: '{self.bw_path}'")
            something_printed = True

        if parsed_args.noblocking:
            print("Running in non-blocking / non-interactive mode")
            something_printed = True
            self.noblock = True
        else:
            self.noblock = False

        if parsed_args.daemontimeout:
            try:
                self.timeout = int(parsed_args.daemontimeout)
            except Exception as e:
                pass
            else:
                print(f"Set timeout to '{self.timeout}'")
                something_printed = True

        if parsed_args.localip:
            if parsed_args.localip != self.host:
                print(f"Set ip to: {parsed_args.localip}")
                something_printed = True
                self.host = parsed_args.localip
        else:
            print(f"Error localip not set using: '{self.host}'")
            something_printed = True

        if parsed_args.localport:
            if parsed_args.localport != self.port:
                self.port = parsed_args.localport
        else:
            print(f"Error port not set using: '{self.port}'")
            something_printed = True

        if parsed_args.fillactions:
            if parsed_args.fillactions != self.fillactions:
                print(f"Fill actions set to: {parsed_args.fillactions}")
                something_printed = True
                self.fillactions = parsed_args.fillactions.upper()
        else:
            self.fillactions = ""

        if parsed_args.closedaemon:
            print("Storing the close signal to send to the daemon later")
            something_printed = True
            self.close = True
        else:
            self.close = False

        if parsed_args.sync:
            print("Enabling the Bitwarden vault sync")
            something_printed = True
            self.sync = True
        else:
            self.sync = False

        if something_printed:
            print()
