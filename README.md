# Bitwarden Autofill Script

This Bitwarden autofill script automates the process of filling in login credentials on desktop applications. It leverages Bitwarden's CLI to retrieve and input usernames, passwords, and 2FA codes into non-browser apps, solving the browser-only limitation of Bitwarden's native autofill feature.

## Features

- Automatically fills usernames, passwords, and TOTP codes into non-browser apps.
- Supports customizable fill actions and sequences.
- Operates in both daemon and client modes.
- Offers additional security options with encryption for communication.

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

You can download the [latest binary releases from here](https://codeberg.org/marvin1099/BitwardenAutofiller/releases)  
After that scroll down to "usage" in the readme.  
And read the lines under **important**.  
And you can check the app arguments there as well. 
If you want to run from source or compile for yourself keep on reading from here.

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://codeberg.org/marvin1099/BitwardenAutofiller.git
   cd BitwardenAutofiller
   ```

2. **Create a virtual enviroment (needed on linux):**
   The following will need to be changed for windows if you want a venv on windows.
   Run the following in a bash console:
   ```bash
   python -m venv .venv
   cd .venv
   source .venv/bin/activate
   ```

3. **Install required dependencies:**
   ```bash
   pip install -e .
   ```

4. **Bitwarden CLI:**
   Ensure the Bitwarden CLI (`bw`) is installed and accessible in your system's PATH.  
   You can download and install it from the [official Bitwarden CLI page](https://bitwarden.com/help/article/cli/).

### Building
1. **To Build first clone the repository if you have not done it yet:**
   ```bash
   git clone https://codeberg.org/marvin1099/BitwardenAutofiller.git
   cd BitwardenAutofiller
   ```
   Run this in powershell on windows and on bash for linux.
2. Next on Windows run:
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1
   ```
   And on Linux run (the .venv creation is automatic here):
   ```bash
   ./build.sh
   ```
3. The binary files wil be in the dist folder.  
   The universal .pyz only gets build with Linux.  
   You can run the apropriate file for you now (in the terminal).   

## Usage

Run the script with the following command:

```bash
python bitwardenautofiller.py
```

**IMPORTANT**  
To make autofill work, you will have to add the name of the program as a URL.  
So for example if your program is called "steam",  
you would add "pcprocess://steam" as a URL in the Bitwarden GUI app.  
So always add "pcprocess://" in front of the app name in your account to be autofilled.

### Command-line Arguments

The script supports the following command-line options for flexible usage:

- `-s, --serverurl`: URL that Bitwarden uses.
- `-cf, --certfile`: Path to the certificate file (if Bitwarden is self-signed).
- `-p, --password`: Bitwarden vault password.
- `-m, --mail`: Bitwarden vault email.
- `-e, --encryption`: Additional password for encryption.
- `-d, --daemonmode`: Start in daemon mode only.
- `-c, --clientmode`: Start in client mode only.
- `-nm, --nomode`: Do not start the daemon or client (for testing argument setup).
- `-bw, --bitwardenclipath`: Path to Bitwarden CLI (default is 'bw').
- `-n, --noblocking`: Non-blocking/non-interactive mode.
- `-t, --daemontimeout`: Set the daemon connection timeout.
- `-ip, --localip`: Local IP address for the daemon server (default is '127.0.0.1').
- `-lp, --localport`: Local port for the daemon server (default is '64756').
- `-f, --fillactions`: Set custom fill actions for autofill.  
    (default: 'C14724635' is a sequence of actions: 1 user, 2 pass, 3  
    totp, 4 type, 5 copy, 6 newline, 7 tab, A next found account, B previus found  
    account, C first found account, D last found account)  
- `-x, --closedaemon`: Send a close signal to the daemon.
- `-y, --sync`: Sync the Bitwarden vault.

These can also be displayed by running (but with more info):
```bash
python bitwardenautofiller.py -h
```

### Example

To start the script in client mode (daemon must already be running) with a custom fill action sequence:

```bash
python bitwardenautofiller.py -c -f C14724635
```

This will fill in the login information (username, password, and copy the TOTP code),  
and it will hit tab after the username and enter after the password.

## Contributing

Contributions are welcome! If you'd like to contribute, please fork the repository and submit a pull request.  
Please do so on the main repo on codeberg.org if possible.