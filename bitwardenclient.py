#!/usr/bin/env python

import encryption
import tempfile
import random
import socket
import string
import json
import os


class BitwardenClient:
    def __init__(self, defauts):
        self.host = defauts.host
        self.port = defauts.port
        self.encryption = defauts.encryption

    def send_request(self, request_data):
        """Send an encrypted request to the Bitwarden daemon and receive the response."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.connect((self.host, self.port))

                saltfile = os.path.join(
                    tempfile.gettempdir(),
                    "Bitwarden+Cli-Autofiller+Script-Salt+File",
                )
                if os.path.isfile(saltfile):
                    os.remove(saltfile)

                salt = "".join(
                    random.choice(string.ascii_uppercase + string.digits)
                    for _ in range(32)
                )
                with open(saltfile, "w") as salty:
                    salty.write(salt)

                on_premise_key_local = (
                    "Bitwarden+Cli~Autofiller:Script-Comunication*Passphrase"
                )
                on_premise_key_local += self.encryption
                on_premise_key_local += salt

                # Encrypt the request data and send it as bytes
                encrypted_request = encryption.encrypt_aes_256(
                    json.dumps(request_data), on_premise_key_local
                )
                sock.sendall(encrypted_request)
                if request_data.get("command", "") == "exit":
                    return

                # Receive and decrypt the response
                encrypted_response = self.receive_data(sock)
                try:
                    err = str(encrypted_response)
                    if err == "Decryption failed":
                        print(
                            f"Server failed to decrypt incoming data (encryption password might not match)\nClosing..."
                        )
                        exit(1)
                    elif err == "Encryption failed":
                        print("Server failed to encrypt data\nClosing...")
                        exit(1)
                except Exception as e:
                    pass

                try:
                    decrypted_response = encryption.decrypt_aes_256(
                        encrypted_response, on_premise_key_local
                    )
                except Exception as e:
                    print(
                        f"Failed to decrypt incoming data (encryption password might not match): {e}\nClosing..."
                    )
                    exit(1)

                return json.loads(decrypted_response)
            except Exception as e:
                print(f"An error occurred: {e}")
                return None

    def receive_data(self, sock):
        """Receive data from the socket."""
        data = b""
        while True:
            packet = sock.recv(4096)
            if not packet:
                break
            data += packet
            break  # only receive one pice of data
        # No need to decode, just return raw bytes
        return data

    def send_command(self, command, args=[], dictfilter={}):
        """Send a command to the Bitwarden daemon and return the result."""
        request_data = {
            "command": command,
            "args": args,
            "filter": dictfilter,
        }
        response = self.send_request(request_data)
        return response
