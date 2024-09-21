#!/usr/bin/env python

import defaults as df
import bitwardenrunner as bwr
import bitwardenlogin as bwl
import bitwardendamon as bwd
import bitwardenclient as bwc
import autofiller as auto
import time
import sys

if __name__ == "__main__":

    defaults = df.Defaults()
    defaults.args_processor()

    if defaults.daemonmode or defaults.clientmode:
        runner = bwr.BitwardenRunner(defaults)
        daemon = bwd.BitwardenDaemon(runner, defaults)
    else:
        print(
            "Running was diabled, this will only print arg settings, closing"
        )

    if not daemon.is_running() and defaults.daemonmode:
        # Initialize the bw login manager
        login = bwl.BitwardenLogin(runner, defaults)

        # Login / Unlock the vault to get the session key
        key = login.return_session()

        # Set the sesson key of the daemon
        daemon.set_session_key(key)
        print("\nStarting daemon, do not close this window")
        print(
            "If your console imput is blocked becalse of the daemon use a new terminal window"
        )

        # Start the daemon
        daemon.start()
    elif defaults.clientmode:
        client = bwc.BitwardenClient(defaults)
        autofiller = auto.AutoFiller(client, defaults)
        autofiller.fill_process()
