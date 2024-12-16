#!/usr/bin/env python

import defaults as df
import bitwardenrunner as bwr
import bitwardenlogin as bwl
import bitwardendaemon as bwd
import bitwardenclient as bwc
import autofiller as auto
import time
import sys

def main(args=None):

    defaults = df.Defaults()
    defaults.args_processor(args)

    if defaults.daemonmode or defaults.clientmode:
        runner = bwr.BitwardenRunner(defaults)
        daemon = bwd.BitwardenDaemon(runner, defaults)
    else:
        print(
            "Running was diabled, this will only print arg settings, closing"
        )

    drun = daemon.is_running()
    if (not drun and defaults.daemonmode) or (defaults.daemonmode and not defaults.clientmode):
        if drun:
            print("Deaemon is already running, exiting")
            if defaults.do_raise:
                raise RuntimeError("Deaemon is already running")
            else:
                exit(1)

        # Initialize the bw login manager
        login = bwl.BitwardenLogin(runner, defaults)

        # Login / Unlock the vault to get the session key
        key = login.return_session()

        # Set the sesson key of the daemon
        daemon.set_session_key(key)

        key = "-" * len(key) # Make shure the key is cleared in memorry after it is set
        key = None # Also set the variable to none to indicate it was cleared

        print("\nStarting daemon, do not close this window")
        print(
            "If your console imput is blocked becalse of the daemon use a new terminal window"
        )

        # Start the daemon
        daemon.start()
    elif defaults.clientmode:
        if not drun:
            print("Daemon is not running, closing client...")
            if defaults.do_raise:
                raise RuntimeError("Daemon is not running")
            else:
                exit(1)
        client = bwc.BitwardenClient(defaults)
        autofiller = auto.AutoFiller(client, defaults)
        autofiller.fill_process()
        if autofiller.message and __name__ != "__main__":
            return autofiller.message

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Exception was triggerd:\n{e}\nClosing")
