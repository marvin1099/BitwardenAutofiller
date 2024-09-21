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
  
- **Passphrase Hashing**: The passphrase generated from the above components is hashed using `SHA-256`, and the resulting hash is used as the key for AES-256 encryption.

- **Encrypted Command Caching**: Commands sent to the Bitwarden autofill runner are cached in an encrypted format, which helps protect against memory-based attacks. Even if an attacker gains access to the cache, the commands remain encrypted and unusable without the correct passphrase.

This ensures that data at rest and in transit is protected, minimizing the risk of sensitive information leakage.

## Dependencies

Install dependencies using `pip`:

```bash
pip install clipboard pyautogui pywinctl psutil cryptography
```

Keep in mind when using linux you will probably have to use a virtual enviroment.  
To make that work run this before running the pip install command:
```bash
cd "PlanedOrActiveScriptDir"
python -v .venv
source ./.venv/bin/activate
```

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://codeberg.org/marvin1099/BitwardenAutofiller.git
   cd BitwardenAutofiller
   ```

2. **Install required dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Bitwarden CLI:**
   Ensure the Bitwarden CLI (`bw`) is installed and accessible in your system's PATH. You can download and install it from the [official Bitwarden CLI page](https://bitwarden.com/help/article/cli/).

## Usage

Run the script with the following command:

```bash
python main.py
```

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
- `-x, --closedaemon`: Send a close signal to the daemon.
- `-y, --sync`: Sync the Bitwarden vault.

### Example

To start the script in clientmode mode (daemon allready has to be running) with a custom fill action sequence:

```bash
python main.py -c -f C14724635
```

This will fill in the login information (username, password, and copy the TOTP code) and it will hit tab after username and enter after password

## Contributing

Contributions are welcome! If you'd like to contribute, please fork the repository and submit a pull request.

### Notes

- Ensure all dependencies are properly installed to avoid runtime errors.