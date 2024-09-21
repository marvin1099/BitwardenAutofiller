import subprocess

# import time
import encryption
import tempfile
import random
import string
import json
import os


class BitwardenRunner:
    def __init__(self, defaults):
        self.bw_path = defaults.bw_path
        self.encryption = defaults.encryption
        self.cache = None

    def cache_cript(self, create=True):
        on_premise_key_local = (
            "Bitwarden+Cli~Autofiller:Script-Store*Passphrase"
        )
        saltfile = os.path.join(
            tempfile.gettempdir(),
            "Bitwarden+Cli-Autofiller+Store-Salt+File",
        )
        if create:
            if os.path.isfile(saltfile):
                os.remove(saltfile)

            salt = "".join(
                random.choice(string.ascii_uppercase + string.digits)
                for _ in range(32)
            )
            with open(saltfile, "w") as salty:
                salty.write(salt)

            on_premise_key_local += self.encryption
            on_premise_key_local += salt
            return on_premise_key_local
        else:
            salt = ""
            if os.path.isfile(saltfile):
                with open(saltfile, "r") as salty:
                    salt = salty.read()
            if len(salt) < 32:
                print("Error no salt file or short salt, exiting...")
                exit(1)

            # Encryption passphrase/key used for both encryption and decryption
            on_premise_key_local += self.encryption
            on_premise_key_local += salt
            return on_premise_key_local

    def run_bw_command(self, command, ret_json=True, dictfilter={}):
        """Run a Bitwarden CLI command and return the parsed JSON output."""
        command.insert(
            0, self.bw_path
        )  # Insert the bw_path at the start of the command list
        try:
            if ret_json:
                if "--response" not in command:
                    command.append("--response")

            if self.cache and len(command) > 1 and command[1] == "sync":
                self.cache = None

            fromcache = False
            result = None
            if self.cache and ret_json:
                if (
                    len(command) > 2
                    and command[1] == "list"
                    and command[2] == "items"
                ):
                    fromcache = True
                    on_premise_key_local = self.cache_cript(False)
                    result = json.loads(
                        encryption.decrypt_aes_256(
                            self.cache, on_premise_key_local
                        )
                    )
                    error = None

                elif (
                    len(command) > 3
                    and command[1] == "get"
                    and command[2] == "item"
                ):
                    nr = command[3]
                    if nr:
                        fitem = None
                        on_premise_key_local = self.cache_cript(False)
                        for item in (
                            json.loads(
                                encryption.decrypt_aes_256(
                                    self.cache, on_premise_key_local
                                )
                            )
                            .get("data")
                            .get("data")
                        ):
                            if item.get("id") == nr:
                                fitem = item
                                break
                    if fitem:
                        fromcache = True
                        result = {"success": True, "data": item}
                        error = None
                    else:
                        fromcache = True
                        result = {
                            "success": False,
                            "message": "Requested item was not found",
                        }
                        error = None

            if not result:
                # print("A " + str(time.time() % 60))
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )  # this takes a while, not a lot to do about it

                result, error = process.communicate()
            # print("B " + str(time.time() % 60))

            # with open('output.json', 'w') as file:
            #    file.write(json.dumps(json.loads(result), indent=4))

            if error and not result:
                result = error
            if not result:
                return {
                    "success": False,
                    "type": "error",
                    "reason": "No result for requested command",
                    "message": "No result for requested command",
                }
            if ret_json:
                try:
                    if fromcache:
                        ldict = result
                    else:
                        ldict = json.loads(result)

                    if (
                        not self.cache
                        and len(command) > 2
                        and command[1] == "list"
                        and command[2] == "items"
                        and ret_json
                    ):
                        on_premise_key_local = self.cache_cript()
                        self.cache = encryption.encrypt_aes_256(
                            json.dumps(ldict), on_premise_key_local
                        )

                    if dictfilter:
                        ret = []
                        q = dictfilter.get("uriquery", "")
                        r = dictfilter.get("return", "id")

                        for l in ldict["data"]["data"]:  # for all login items
                            add = False
                            a_id = l.get("id")  # get id
                            if q and a_id:  # if id and uriquery are set
                                uris = l.get("login", {}).get(
                                    "uris", {}
                                )  # get the uris
                                if uris:  # if there are uris
                                    for (
                                        uric
                                    ) in uris:  # get all uri collections
                                        uri = uric.get(
                                            "uri"
                                        )  # get the uri form the colletion
                                        if (
                                            uri and uri == q
                                        ):  # if the query is the uri
                                            ret.append(
                                                a_id
                                            )  # add it to a list
                                            continue

                        if ret:
                            ldict = {
                                "success": True,
                                "returns": ret,
                                "message": "grabbed filtered uriquery",
                            }
                        else:
                            ldict = {
                                "success": False,
                                "type": "error",
                                "message": "Not found.",
                                "addional": "no matches for filtered uriquery",
                            }
                    return ldict
                except json.JSONDecodeError as e:
                    return {
                        "success": False,
                        "type": "error",
                        "reason": "Failed to parse JSON response",
                        "message": str(e),
                    }
            else:
                return result
        except FileNotFoundError as e:
            print(f"An error occurred: {e}")
            exit(1)
        except Exception as e:
            print(f"An error occurred: {e}")
            exit(1)
