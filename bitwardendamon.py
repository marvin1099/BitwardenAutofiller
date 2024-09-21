#!/usr/bin/env python

import multiprocessing
import encryption
import tempfile
import socket
import time
import json
import os


class BitwardenDaemon(multiprocessing.Process):
    def __init__(self, runner, defaults):
        super().__init__()
        self.session_key = None
        self.runner = runner
        self.timeout = defaults.timeout
        self.host = defaults.host
        self.port = defaults.port
        self.encryption = defaults.encryption
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def set_session_key(self, key):
        self.session_key = key

    def run(self):
        """Start the daemon process to listen for incoming requests."""
        cac = self.handle_request(
            json.dumps({"command": "list", "args": ["items"]})
        )  # run list command to cache results
        if not cac.get("success"):
            print(
                f"There was a issue with getting the bitwaden vault data {cac.get("message")}\nExiting..."
            )
            exit(1)
        self.sock.bind((self.host, self.port))
        self.sock.listen()
        if self.timeout > -1:
            self.sock.settimeout(self.timeout)
        print(
            f"Bitwarden CLI Daemon listening on {self.host}:{self.port}...\n"
        )

        while True:
            try:
                # Accept new connections
                conn, addr = self.sock.accept()
            except socket.timeout:  # if the timeout is reached exit
                print("Socket waiting timeout reached\nExiting...")
                try:
                    self.sock.close()
                except Exception as e:
                    pass
                exit()
            except Exception as e:
                print(
                    f"Error occored while waiting for the connection: {e}\nExiting..."
                )
                try:
                    self.sock.close()
                except Exception as e:
                    pass
                exit()

            with conn:
                print(f"Connected by {addr}")

                while True:
                    data = conn.recv(1024)
                    if not data:
                        break

                    saltfile = os.path.join(
                        tempfile.gettempdir(),
                        "Bitwarden+Cli-Autofiller+Script-Salt+File",
                    )
                    salt = ""
                    if os.path.isfile(saltfile):
                        with open(saltfile, "r") as salty:
                            salt = salty.read()
                    if len(salt) < 32:
                        conn.close()
                        print(
                            "Error no salt file or short salt, listening too new connections...\n"
                        )
                        break

                    # Encryption passphrase/key used for both encryption and decryption
                    on_premise_key_local = "Bitwarden+Cli~Autofiller:Script-Comunication*Passphrase"
                    on_premise_key_local += self.encryption
                    on_premise_key_local += salt

                    try:
                        # Decrypt the received bytes (no need to decode)
                        decrypted_data = encryption.decrypt_aes_256(
                            data, on_premise_key_local
                        )
                    except Exception as e:
                        print(
                            f"Failed to decrypt incoming data (encryption password might not match): {e}\nlistening too new connections...\n"
                        )
                        conn.sendall("Decryption failed")
                        conn.close()
                        break

                    # Process the decrypted request
                    response = self.handle_request(decrypted_data)

                    try:
                        # Encrypt the outgoing response (already bytes)
                        encrypted_response = encryption.encrypt_aes_256(
                            json.dumps(response), on_premise_key_local
                        )
                    except Exception as e:
                        print(
                            f"Failed to encrypt response: {e}\nlistening too new connections...\n"
                        )
                        conn.sendall("Encryption failed")
                        conn.close()
                        break

                    # Send encrypted response
                    conn.sendall(encrypted_response)
                    conn.close()

                    # Remove salt file
                    if os.path.isfile(saltfile):
                        os.remove(saltfile)

                    # exit()
                    print(
                        f"Finished connection, listening too new connections...\n"
                    )
                    break  # break to listen to new connections

    def handle_request(self, request):
        """Process the incoming request and run the appropriate Bitwarden command."""
        try:
            command = ""
            args = []
            request_data = json.loads(request)
            command = request_data.get("command", "")
            args = request_data.get("args", [])
            if isinstance(command, str) and command.lower() == "exit":
                print("Daemon exit command issued, closing daemon...")
                exit()
            elif command:
                # Append the session key to the command
                argcp = list(args)
                args.append("--session")
                args.append(self.session_key)
                result = self.runner.run_bw_command(
                    [command] + args,
                    dictfilter=request_data.get("filter", {}),
                )

                if result.get("success") != None:
                    result.update({"command": [command] + argcp})
                    return result
                else:
                    result.update(
                        {
                            "success": False,
                            "command": [command] + argcp,
                            "error": "No successful command",
                        }
                    )
                    return result
            else:
                return {
                    "success": False,
                    "command": [command] + argcp,
                    "error": "Invalid command",
                }
        except Exception as e:
            return {
                "success": False,
                "command": [command] + argcp,
                "error": str(e),
            }

    def is_running(self):
        """Check if the daemon is already running by attempting to connect to the socket."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.connect((self.host, self.port))
                return True
            except ConnectionRefusedError:
                return False
            except socket.error:
                return False
