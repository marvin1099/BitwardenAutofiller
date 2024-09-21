import subprocess

# import time
import json


class BitwardenRunner:
    def __init__(self, bw_path):
        self.bw_path = bw_path

    def run_bw_command(self, command, ret_json=True, dictfilter={}):
        """Run a Bitwarden CLI command and return the parsed JSON output."""
        command.insert(
            0, self.bw_path
        )  # Insert the bw_path at the start of the command list
        try:
            if ret_json:
                if "--response" not in command:
                    command.append("--response")

            # print("A " + str(time.time() % 60))
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )  # this takes a while, not a lot to do about it
            result, error = process.communicate()
            # print("B " + str(time.time() % 60))

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
                    ldict = json.loads(result)
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
