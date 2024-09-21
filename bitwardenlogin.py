#!/usr/bin/env python

from getpass import getpass
import subprocess
import json
import sys
import os


class BitwardenLogin:
    def __init__(self, runner, defaults):
        self.runner = runner
        self.interactive = not defaults.noblock
        self.mail = defaults.mail
        self.passw = defaults.passw
        self.certfile = defaults.certfile
        self.serverurl = defaults.serverurl

    def get_session_token(self):
        """Login to Bitwarden and retrieve a session token."""
        print("Attempting to login...")
        if not self.mail:
            if self.interactive:
                self.mail = input("Mail: ")
            else:
                print(
                    "Noblocking was activated, but no mail was given, Exiting"
                )
                sys.exit(1)
            if not self.mail:
                print("Mail not given, Exiting")
                sys.exit(1)

        if not self.passw:
            if self.interactive:
                self.passw = getpass(prompt="Password: [hidden]")
            else:
                print(
                    "Noblocking was activated, but no password was given, Exiting"
                )
                sys.exit(1)
            if not self.passw:
                print("Password not given, Exiting")
                sys.exit(1)

        if self.serverurl:
            response = self.runner.run_bw_command(
                ["config", "server", self.serverurl]
            )
            if response.get("success"):
                print(
                    f"Successfuly set and saved the serverurl to the value: {self.serverurl}"
                )
            else:
                print(
                    f"There was a issue setting the serverurl, skipping it: {response.get("message")}"
                )

        response = self.runner.run_bw_command(
            ["login", self.mail, self.passw, "--response"]
        )

        if response.get("success"):
            self.passw = "-" * len(self.passw)
            self.passw = None
            session_key = response["data"]["raw"]
            print(f"Login successful. Returning session key")
            return session_key
        else:
            session_key = self.cert_detector(response)
            if session_key:
                self.passw = "-" * len(self.passw)
                self.passw = None
                return session_key
            else:
                print("Login failed. Please check your credentials.")
                print("Returned was: " + response.get("message"))
                sys.exit(1)

    def check_status(self):
        """Check the current Bitwarden status."""
        status_response = self.runner.run_bw_command(["status", "--response"])

        return status_response

    def unlock_vault(self):
        """Unlock the vault if the user is already logged in."""
        print("Vault is locked. Unlocking...")
        if not self.passw:
            if self.interactive:
                self.passw = getpass(prompt="Password: [hidden]")
            else:
                print(
                    "Noblocking was activated, but no password was given, Exiting"
                )
                sys.exit(1)
            if not self.passw:
                print("Password not given, Exiting")
                sys.exit(1)

        unlock_response = self.runner.run_bw_command(
            ["unlock", self.passw, "--response"]
        )

        if unlock_response.get("success"):
            session_key = unlock_response["data"]["raw"]

            syncresp = self.runner.run_bw_command(["sync", "--response"])

            if not syncresp.get("success"):
                if not self.cert_detector(syncresp, True):
                    print("Failed to unlock the vault.")
                    print("Returned was: " + syncresp.get("message"))
                    sys.exit(1)

            self.passw = "-" * len(self.passw)
            self.passw = None

            print(f"Vault unlocked. Returning session key")
            return session_key
        else:
            session_key = self.cert_detector(unlock_response)
            self.passw = "-" * len(self.passw)
            self.passw = None
            if session_key:
                return session_key
            else:
                print("Failed to unlock the vault.")
                print("Returned was: " + unlock_response.get("message"))
                sys.exit(1)

    def cert_detector(self, response, sync=False):
        if "self-signed certificate in certificate chain" in response.get(
            "message"
        ):
            if os.environ.get("NODE_EXTRA_CA_CERTS"):
                print("Returned was: " + response.get("message"))
                print("The set cert path was not set correctly, Exiting")
                sys.exit(1)

            print("Self singed certificate detected")
            print("On Unix Systems you may want to run:")
            print(
                '\texport NODE_EXTRA_CA_CERTS="/absolute/path/to/your/certificates.pem"'
            )
            print("And on Windows Powershell you may want to run:")
            print(
                '\t$env:NODE_EXTRA_CA_CERTS="/absolute/path/to/your/certificates.pem"'
            )
            print(
                "In case you want to set it yourself and keep it around in this terminal session"
            )

            path = None
            if self.certfile:
                path = self.certfile
                if path and os.path.isfile(path) and path.endswith(".pem"):
                    print("Vailid cert file was set as argument, using it")
                else:
                    print(
                        "Cert file set as argument is not a existing file or not a .pem file"
                    )
                    path = None

            if self.interactive and not path:
                path = input(
                    "\nOtherwise input the path to the certificate .pem file now\nPem File: "
                ).strip()
            elif not self.interactive and not path:
                print(
                    "Noblocking was activated, but no certfile argument was given, Exiting"
                )
                sys.exit(1)

            if path and os.path.isfile(path) and path.endswith(".pem"):
                os.environ["NODE_EXTRA_CA_CERTS"] = os.path.abspath(path)
                if sync:
                    return True
                if self.mail:
                    return self.get_session_token()
                return self.unlock_vault()
            else:
                print("Cert file not given or invalid path, Exiting")
                sys.exit(1)
        else:
            return None

    def return_session(self):
        # Check current status
        status = self.check_status()
        active_state = status.get("data").get("template").get("status")

        if active_state == "locked" or active_state == "unlocked":
            # If logged in, unlock to get the session key
            session_token = self.unlock_vault()
        else:
            # If not logged in, perform login
            session_token = self.get_session_token()

        # Proceed with the daemon startup (to be implemented)
        # For now, we'll just print the session token
        if session_token:
            return session_token
        else:
            print("There was some problem getting the session_token, Exiting")
            sys.exit(1)

    def main(self):
        return self.return_session()


if __name__ == "__main__":
    print("Use: import bitwardenlogin")
    print("Then: bl = BitwardenLogin(bw_path)")
    print("And: key = bl.return_session()")
    print("To Login / Unlock and return the session_key")
