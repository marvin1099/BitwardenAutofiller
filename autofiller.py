#!/usr/bin/env python

import clipboard
import pyautogui
import pywinctl
import platform
import psutil
import os


class AutoFiller:
    def __init__(self, client, defaults):
        self.sender = client.send_command
        self.actions = defaults.fillactions
        self.close = defaults.close
        self.sync = defaults.sync

    def get_active_process(self):
        try:
            # Get the focused window and retrieve the process name
            active_window = pywinctl.getActiveWindow()
            process_name = active_window.getAppName()

            # Get a list of processes with matching names
            # process_list = list(filter(lambda p: p.name() == process_name, psutil.process_iter()))
            # process_list = None
            if process_name:
                process_info = {"window": active_window, "name": process_name}
                return process_info
            else:
                print(f"Process is not set")
                return None

            # if process_list:
            #     # Sort the process list by creation time (newest first)
            #     sorted_processes = sorted(process_list, key=lambda p: p.create_time(), reverse=True)
            #
            #     # Get the newest process (most recent)
            #     newest_process = sorted_processes[0]
            #     process_info = {
            #         'name': process_name,
            #         'pid': newest_process.pid,
            #         'cmdline': newest_process.cmdline(),
            #         'status': newest_process.status()
            #     }
            #     return process_info

        except Exception as e:
            print(f"Unable to find process name for active window: {e}")
            return None

    def get_login_ids(self, process_name):
        """Query Bitwarden for login item related to the process."""
        if process_name:
            query = f"pcprocess://{process_name}"
            print(
                f"Found active process, running query '{query}' to look for login item..."
            )
            response = self.sender(
                "list",
                ["items"],
                dictfilter={"uriquery": query, "returns": "id"},
            )
            return response
        else:
            print(
                f"With the process name {process_name} could not be determined."
            )
            return None

    def get_login_item(self, item_id):
        if item_id:
            response = self.sender("get", ["item", item_id])
            return response

    def get_login_totp(self, item_id):
        if item_id:
            response = self.sender("get", ["totp", item_id])
            return response

    def accountselect(self, items, allactions):
        activeaccount = 0  # The current selected account
        lastacc = len(items)  # The number of available accounts
        nractions = ""  # Buffer for collecting numeric actions
        letters = None  # Current selected letter (account switcher)
        haveyield = (
            False  # Whether a value has been yielded in this iteration
        )

        if allactions:
            for action in str(
                allactions + "C"
            ):  # Append 'C' to ensure selection execution
                # Handle letters (account switching commands)
                if action in "ABCD":
                    if letters is None:
                        letters = int(activeaccount)

                    if action == "C":  # Select first account
                        activeaccount = 0
                    elif action == "D":  # Select last account
                        activeaccount = lastacc - 1
                    elif action == "A":  # Move to the next account
                        activeaccount = (activeaccount + 1) % lastacc
                    elif action == "B":  # Move to the previous account
                        activeaccount = (
                            activeaccount - 1 + lastacc
                        ) % lastacc

                    # Handle previously collected actions for the last account (if any)
                    if letters is not None and nractions:
                        yield items[letters], nractions
                        haveyield = True
                        letters = None
                        nractions = ""

                # Handle numeric actions (to be applied to the selected account)
                elif action.isnumeric():
                    nractions += action

            if not haveyield:
                yield None, None
        else:
            yield None, None

    def autofill(self, login_id, actions):
        item = self.get_login_item(login_id)
        logindata = item.get("data", {}).get("login", {})
        store = ""

        usern = logindata.get("username")
        if usern:
            store = str(usern)
        passw = logindata.get("password")
        if passw and not store:
            store = str(usern)
        istotp = logindata.get("totp")
        totp = None

        if actions:
            for action in actions:
                if action == "1":
                    if usern:
                        store = str(usern)
                    else:
                        store = ""
                elif action == "2":
                    if passw:
                        store = str(passw)
                    else:
                        store = ""
                elif action == "3":
                    if istotp:
                        if not totp:
                            totp = str(
                                self.get_login_totp(login_id)
                                .get("data", {})
                                .get("data", "")
                            )
                        store = str(totp)
                    else:
                        store = ""
                elif action == "4" and store:
                    pyautogui.write(store)
                elif action == "5" and store:
                    clipboard.copy(store)
                elif action == "6":
                    pyautogui.press("enter")
                else:
                    pyautogui.press("tab")

    def fill_process(self):
        """Main function to perform autofill based on the active process."""
        if self.close:
            self.sender("exit")
            print("Send exit command to deamon and now closing client...")
            exit()
        if self.sync:
            sres = self.sender("sync")
            cac = self.sender(
                "list", ["items"]
            )  # run list command to cache results
            if not sres.get("success"):
                print(f"Problem syncing, skipping: {sres.get("message")}")
            else:
                print("Syncing successful")
            if not cac.get("success"):
                print(
                    f"There was a issue with getting the bitwaden vault data {cac.get("message")}\nExiting..."
                )
                exit(1)

        process_info = self.get_active_process()
        if process_info.get("name"):
            process_name = process_info.get("name")

            login_items = self.get_login_ids(process_name)
            if login_items and login_items.get("success"):
                print("Login item retrieved successfully.")
                # Proceed to autofill (not implemented yet)
                for item_id, actions in self.accountselect(
                    login_items.get("returns", []), self.actions
                ):
                    if item_id:
                        self.autofill(item_id, actions)
                    else:
                        print("Actions not set or valid, closing...")
            elif login_items.get("message") == "Not found.":
                print("No login item with that process name, closing...")
            else:
                print(
                    f"Failed to retrieve login item with message: {login_items.get("message")}\nClosing..."
                )
        else:
            print("Could not determine the active process.")
