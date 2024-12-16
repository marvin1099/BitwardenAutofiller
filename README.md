# Bitwarden Autofill Script

This Bitwarden autofill script automates the process of filling in login credentials on desktop applications.  
It leverages Bitwarden's CLI to retrieve and input usernames, passwords, and TOTP codes into non-browser apps,  
solving the browser-only limitation of Bitwarden's native autofill feature.  
The project now includes a GUI version that makes it easier to run the autofiller if you don't know the terminal.

## Features

- Automatically fills usernames, passwords, and TOTP codes into non-browser apps.
- Supports customizable fill actions and sequences.
- Operates in both daemon and client modes.
- Offers additional security options with encryption for communication.
- The GUI Provides a user-friendly interface to manage input options, configure settings, and control the daemon/client.

## Security

Encryption is implemented to ensure that sensitive data, such as passwords and communication between client and daemon, is securely handled:

- **Encryption for Communication**: All communication between the client and the daemon is encrypted using `AES-256`. The encryption passphrase is derived from a combination of:
  - A **hardcoded password**
  - An **optional user-specified password** that can be set using the `--encryption` flag
  - A **salt**, which is stored in a hardcoded file location.
  
- **Passphrase Hashing**: The passphrase generated from the above components is hashed using `SHA-256`,  
  and the resulting hash is used as the key for AES-256 encryption.

- **Encrypted Command Caching**: Commands sent to the Bitwarden autofill runner are cached in an encrypted format,  
  which helps protect against memory-based attacks. Even if an attacker gains access to the cache,  
  the commands remain encrypted and unusable without the correct passphrase.

This ensures that data at rest and in transit is protected, minimizing the risk of sensitive information leakage.

## Downloads

You can download the [latest binary releases from here](https://codeberg.org/marvin1099/BitwardenAutofiller/releases).  
Both GUI and CLI versions can be downloaded there.  
After downloading the binary, **continue reading at the [Usage](#usage) section** to understand how to run the script.

If you want to build the project from source or run it directly in a development environment,  
**continue reading** for the setup instructions.

## Installation (For Running From Source)

1. **Clone the repository:**
   Git is need for this step, make shure you install it and add it to your PATH.  
   ```bash
   git clone https://codeberg.org/marvin1099/BitwardenAutofiller.git
   cd BitwardenAutofiller
   ```

2. **Create a virtual environment (Linux users):**
   This step can be skipped on Windows. On Linux run the following in a bash console:  
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

3. **Install required dependencies:**
   ```bash
   pip install -e .
   ```

4. **Bitwarden CLI:**
   Ensure the Bitwarden CLI (`bw`) is installed and accessible in your system's PATH.  
   You can also provide a custom path for the `bw` cli tool, if you don't want it in your PATH.  
   You can download and install it from the [official Bitwarden CLI page](https://bitwarden.com/help/article/cli/).

5. **Continue reading at the [Usage](#usage) section** to understand how to run the script.  
   **Otherwise continue reading** for building from source.  

### Building From Source

1. **Clone the repository (if not already done):**
   Git is need for this step, make shure you install it and add it to your PATH.  
   ```bash
   git clone https://codeberg.org/marvin1099/BitwardenAutofiller.git
   cd BitwardenAutofiller
   ```
   Run this `in PowerShell on Windows` or `a bash console on Linux`.

2. **Build the binary:**
   - On **Windows**, run:
     ```powershell
     powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1
     ```
   - On **Linux**, run:
     ```bash
     ./build.sh
     ```
   (Note: The `.venv` creation is automatic during the Linux build.)

3. The binary files will be located in the `dist` folder.  

## Usage

If running the script from source use following command:
```bash
python bitwardenautofiller.py
```
And use the following if you want the gui instead:
```bash
python bwautofillergui.py
```

Otherwise if you use binarys run / dobble click the file:  
- `BitwardenAutofillerWindowsCLI.exe` on Windows (for the CLI)
- `BitwardenAutofillerWindowsGUI.exe` on Windows (for the GUI)
- `BitwardenAutofillerLinuxCLI` on Linux (for the CLI)
- `BitwardenAutofillerLinuxGUI` on Linux (for the GUI)

#### IMPORTANT
To make autofill work, you must add the program name as a URL entry in the app entry.  
So if you have a browser autofill account for your app you just add the URL there.  
Otherwise you add the URL to a new entry and input your username and password as usual.  
For example, if your application is called `steam`,  
you should add `pcprocess://steam` as a URL in the Bitwarden GUI app under your steam account entry.  
Always use the format `pcprocess://<app_name>` for applications you want to autofill.

### Command-line Arguments

The script supports the following command-line options for flexible usage:

- `-s, --serverurl`: URL that Bitwarden uses.
- `-cf, --certfile`: Path to the certificate file (if Bitwarden is self-signed).
- `-l, --logout`: Logout from Bitwarden (fixes sync issues, relogin needed).
- `-p, --password`: Bitwarden vault password.
- `-m, --mail`: Bitwarden vault email.
- `-e, --encryption`: Additional password for encryption.
- `-d, --daemonmode`: Start in daemon mode only.
- `-c, --clientmode`: Start in client mode only.
- `-nm, --nomode`: Do not start the daemon or client (for testing argument setup).
- `-bw, --bitwardenclipath`: Path to Bitwarden CLI (default is 'bw').
- `-n, --noblocking`: Non-blocking/non-interactive mode.
- `-t, --daemontimeout`: Set the daemon connection timeout.
- `-sf, --saltfolder`: Create the saltfiles in a subfolder in /tmp  
    (usefull for file sync, when daemon and client are on 2 PCs).
- `-ip, --localip`: Local IP address for the daemon server (default is '127.0.0.1').
- `-lp, --localport`: Local port for the daemon server (default is '64756').
- `-f, --fillactions`: Set custom fill actions for autofill  
    (Default: `C14724635`, a sequence of actions: 1 = user, 2 = pass, 3 = totp, 4 = type, 5 = copy,  
    6 = newline, 7 = tab, A = next account, B = previous account, C = first account, D = last account).
- `-x, --closedaemon`: Send a close signal to the daemon.
- `-y, --sync`: Sync the Bitwarden vault.
- `-r, --raise`: raises errors instead of exiting (used for the gui)
- `-cli`: CAN ONLY BE USED WITH THE GUI, will bypass the GUI and make the GUI like the CLI.

For more details, run:
```bash
python bitwardenautofiller.py -h
```
If you have the GUI version it sould be easy enoght to understand.  
but if not you can bypass the gui as mentioned to run cli stiuff with the gui binary.  
for that you would run the command:
```bash
python bwautofillergui.py -cli -h
```
This would then display the cli help.

To run the CLI binary versions with arguments open a terminal and run:  
- `"BWAutofillerWindowsCLI.exe" -h` on Windows.  
- `"BWAutofillerLinuxCLI" -h` on Linux.  

If you use the GUI you probably wont need to use the cli.  
Just dobble click / run:
- `"BWAutofillerWindowsGUI.exe"` on Windows.  
- `"BWAutofillerLinuxGUI"` on Linux.  

The full filepaths will be needed, if you are in the terminal and not at the script directory.  
eg. `"/home/user/Apps/Autofiller/BWAutofillerLinuxCLI" -h` this is just an example of course.  
You need to enter your path of the autofiller.

### Cli Examples

To start the script in daemon mode with a certfile and with a custom additional communication password:
```bash
python bitwardenautofiller.py -d -cf /path/to/cert/file.cer -e ComplexPassword
```
The same communication password would also need to be set for the client.

To start the script in client mode with the sync command and a additional custom communication password (daemon needs to run):
```bash
python bitwardenautofiller.py -c -e ComplexPassword
```

To use a custom Installation path of Bitwarden you would use:
```bash
python bitwardenautofiller.py -bw /path/to/bw
```
In here there is no info on daemon or clientmode.  
In this case daemon will be used if it isn't running, otherwise the client will run.

To start the script in client mode (daemon must already be running) with a custom fill action sequence:
```bash
python bitwardenautofiller.py -c -f C14724635
```
On Linux add `sleep 1; ` in front to wait 1 second before checking for the active app.  
On PowerShell Windows add `Start-Sleep -Seconds 1; ` in front for the same behavior.  
This will fill in the login information (username, password, and copy the TOTP code),  
and it will hit tab after the username and enter after the password.

The daemon can be closed with the client by sending:
```bash
python bitwardenautofiller.py -c -x
```

If you use a binary you just replace `python bitwardenautofiller.py` with the path to your binary.

### Network usage
If you want, you can use the daemon on a other pc of your network.  
For that you want to fist setup a SMB share or something like it.  
You want to do this on the pc that runs the the daemon.  
This pc will never have to type anything, as the client will do that.  
So you can have this on a server without a GUI.  
You want to share the "/tmp/Bitwarden+Cli-Autofiller+Script-Directory" folder.

Next go to the client pc (the one where you like to autofill).  
There mount the share to "/tmp/Bitwarden+Cli-Autofiller+Script-Directory".  
By doing this (or a variation of this) the salt files are now the same on both PCs.

Next on the server run:
```bash
python bitwardenautofiller.py -n -d -sf -t -1 -cf CERTFILE -s SERVERURL  -p PASSWORD -m MAIL 
```
Not all of this is needed but lets break it down:
- `-n`: disables all inputs, for a server this is useful. 
- `-d`: runs daemonmode.
- `-sf`: enables the saltfile subfolder "/Bitwarden+Cli-Autofiller+Script-Directory".
- `-t` `-1`: disables timeout, also useful on a server.
- `-cf` `CERTFILE`: set the certfile (only needed for self-signed Bitwarden).
- `-s` `SERVERURL`: set the server URL (if you use your own server, only needs to be set once).
- `-p` `PASSWORD`: set the vault password.
- `-m` `MAIL`: set the vault mail.

Replace uppercase words with the correct info for you.

On the client run:
```bash
python bitwardenautofiller.py -c -sf -ip LOCALIP -lp LOCALPORT
```
This will then autofill the active app.  
Add `sleep 1; ` in front to wait 1 second before cheking for the active app.  
On PowerShell Windows add `Start-Sleep -Seconds 1; ` in front for the same behavior.  
Let's also break down the command:
- `-c`: runs clientmode.
- `-sf`: enables the saltfile subfolder "/Bitwarden+Cli-Autofiller+Script-Directory".
- `-ip` `LOCALIP`: set the daemon IP.
- `-lp` `LOCALPORT`: set the daemon port.

Replace uppercase words with the correct info for you.

## Contributing

Contributions are welcome! If you'd like to contribute, please fork the repository and submit a pull request.  
Please do so on the [main repo on codeberg.org](https://codeberg.org/marvin1099/BitwardenAutofiller) if possible.
