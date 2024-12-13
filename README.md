# Bitwarden Autofill Script

This Bitwarden autofill script automates the process of filling in login credentials on desktop applications. It leverages Bitwarden's CLI to retrieve and input usernames, passwords, and TOTP codes into non-browser apps, solving the browser-only limitation of Bitwarden's native autofill feature.

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

You can download the [latest binary releases from here](https://codeberg.org/marvin1099/BitwardenAutofiller/releases).  
After downloading the binary, **continue reading at the [Usage](#usage) section** to understand how to run the script.

If you want to build the project from source or run it directly in a development environment,  
**continue reading this section** for the setup instructions.

## Installation (For Running From Source)

1. **Clone the repository:**
   ```bash
   git clone https://codeberg.org/marvin1099/BitwardenAutofiller.git
   cd BitwardenAutofiller
   ```

2. **Create a virtual environment (Linux users):**
   The following steps will need to be adjusted if you're on Windows. Run the following in a bash console:
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
   You can download and install it from the [official Bitwarden CLI page](https://bitwarden.com/help/article/cli/).

### Building From Source

1. **Clone the repository (if not already done):**
   ```bash
   git clone https://codeberg.org/marvin1099/BitwardenAutofiller.git
   cd BitwardenAutofiller
   ```
   Run this in PowerShell on Windows or a bash console on Linux.

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
   If you're using the binary, **refer to the [Usage](#usage) section** for running the autofiller.  
   If you prefer running from source, **continue reading below**.

## Usage

If running the script from source use following command:

```bash
python bitwardenautofiller.py
```

Otherwise if you use binarys run / dobble click the file: 
- `BitwardenAutofillerWindows.exe` on Windows
- `BitwardenAutofillerLinux` on Linux

#### **IMPORTANT**  
To make autofill work, you must add the program name as a URL entry in your Bitwarden account.  
For example, if your application is called `steam`, you should add `pcprocess://steam` as a URL in the Bitwarden GUI app.  
Always use the format `pcprocess://<app_name>` for applications you want to autofill.

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
    (Default: `C14724635`, a sequence of actions: 1 = user, 2 = pass, 3 = totp, 4 = type, 5 = copy,  
    6 = newline, 7 = tab, A = next account, B = previous account, C = first account, D = last account.)
- `-x, --closedaemon`: Send a close signal to the daemon.
- `-y, --sync`: Sync the Bitwarden vault.

For more details, run:
```bash
python bitwardenautofiller.py -h
```

To run the binary versions with arguments open a terminal and run:  
- `"BitwardenAutofillerWindows.exe" -h` on Windows  
- `"BitwardenAutofillerLinux" -h` on Linux  

The full filepaths will be needed, if you are not at the script directory.  
eg. `"/home/user/Apps/Autofiller/BitwardenAutofillerLinux" -h` this is just an example of course.  
You need to enter your path of the autofiller.

### Examples

To start the script in daemon mode with a certfile and with a custom additional communication password
```bash
python bitwardenautofiller.py -d -cf /path/to/cert/file.cer -e ComplexPassword
```
The same communication password would also need to be set for the client

To start the script in client mode with a sync command and a custom combination password
```bash
python bitwardenautofiller.py -c -e ComplexPassword
```

To start the script in client mode (daemon must already be running) with a custom fill action sequence:
```bash
python bitwardenautofiller.py -c -f C14724635
```
This will fill in the login information (username, password, and copy the TOTP code),  
and it will hit tab after the username and enter after the password.

The daemon can be closed with the client by sending:
```bash
python bitwardenautofiller.py -c -x
```

If you use a binary you just replace `python bitwardenautofiller.py` with the path to your binary.

## Contributing

Contributions are welcome! If you'd like to contribute, please fork the repository and submit a pull request.  
Please do so on the main repo on codeberg.org if possible.