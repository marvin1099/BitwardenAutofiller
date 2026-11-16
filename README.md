# Bitwarden Autofiller

Bitwarden Autofiller fills login fields in desktop applications using explicitly
mapped Bitwarden Password Manager entries. It uses the official `bw` CLI, offers
a command-line client and Qt GUI, and supports Wayland input through the XDG
Remote Desktop portal plus compositor-supported active-app detection.

## Requirements

- Python 3.12 or newer and [uv](https://docs.astral.sh/uv/)
- The official Bitwarden Password Manager CLI (`bw`) on the machine that
  accesses the vault
- A desktop session for typing. Wayland requires an XDG Remote Desktop portal
  and `libxkbcommon`; X11 and Windows use the optional PyAutoGUI backend.
- Wayland types text one character at a time through the active keymap and pastes
  only characters the keymap cannot represent. Install `wl-clipboard` for the
  CLI fallback; the CLI's optional `desktop` extra also provides `pyperclip`,
  and the GUI can use Qt's clipboard.
- The `desktop` extra includes PyWinCtl for X11 active-window detection; it is
  retained for older X11 clients.
- On Wayland, install the `wayland` extra for input support and wlr
  foreign-toplevel detection. KDE Plasma 6 detection uses the `kdotool` command
  (install it from your distribution or with `cargo install kdotool`); manual
  app-ID entry and the custom PID command below remain available when native
  detection is missing.

## Install and run

Install the GUI and Wayland input support on Linux/Wayland:

```sh
uv sync --extra gui --extra wayland
uv run bwautofillergui
```

For an X11 or Windows CLI/GUI installation, use the `desktop` extra instead:

```sh
uv sync --extra gui --extra desktop
uv run bwautofillergui
```

Run a one-shot fill from a terminal:

```sh
uv run bitwarden-autofiller --app-id steam
```

The CLI prompts for a master password without echoing it. You can provide the
account email with `--email`; passwords are deliberately not accepted as
command-line options. The default three-second focus delay gives you time to
switch to the target application. Set `--delay 0` to disable it or choose a
different delay. For a compositor without native detection, pass a trusted PID
command such as:

```sh
uv run bitwarden-autofiller \
  --active-app-command 'hyprctl activewindow -j | jq -r .pid'
```

The configured command is tried first; if it fails, native detection is still
attempted. Avoid putting credentials in the command: it is saved as a GUI
setting or may be visible in CLI process arguments. Use `--help` for all options.

Before each typing or key action, the CLI and GUI re-check the focused
application. KWin and PyWinCtl also expose a window handle, which is pinned on
the first check; a later change cancels the fill, even if the new window belongs
to the same app. Compositors without stable window handles fall back to app-ID
checks. If detection is unavailable, filling stops unless you explicitly enable
**Allow fill if active app cannot be verified** in the GUI or pass
`--allow-unverified-target` to the CLI. That override warns that input will go
to whichever window has focus.

In the GUI, connect to the vault and detect or enter the target application ID.
Detection waits through a focus countdown on both X11 and Wayland. KDE uses
`kdotool`; wlroots compositors use the foreign-toplevel protocol when available.
If native detection is unavailable, enter the ID manually or configure an
**Active-app PID command** in the GUI. The GUI saves this setting. The command is
run through your shell and must print only the active window's numeric PID; the
process name is used for the app ID to match PyWinCtl's previous Linux behavior.
The configured command is tried first and native detection is the fallback.
Only configure commands you trust, and do not include credentials. PyWinCtl is
retained for X11 detection and PyAutoGUI for older input setups. Load the mapped
account names, then use each account's
**Autofill**, **Copy username**, **Copy password**, or **Copy TOTP** button. The
GUI can also generate and copy a mapping URI from the app ID and action sequence.
The master password field is masked, cleared immediately after connecting, and
is never saved in settings.

## Map a vault entry

Add a URI to each Bitwarden login item using this format:

```text
pcprocess://<application-id>
```

For example, map a Steam login to `pcprocess://steam`, then enter `steam` as the
application ID in the GUI or CLI. Matching is case-insensitive. On KDE, detected
IDs use the active process name (the same value PyWinCtl used previously), with
the KWin window class as a fallback when the PID or process name is unavailable.
On wlroots compositors, detection uses the compositor-reported application ID.
Custom PID commands also resolve to a process name. Confirm the detected value
against the URI you mapped. No generic XDG portal currently provides active-app
identity, so unsupported compositors can use the custom command or manual-ID
fallback.

An optional `actions` parameter stores a per-login fill profile in the URI:

```text
pcprocess://steam?actions=14724635
```

The query does not affect app matching. Generate a URI from the CLI with
`bitwarden-autofiller --generate-uri --app-id steam --actions 14724635`. If
`--actions` is omitted when filling, the CLI uses the first matching login's
profile, falling back to the default sequence for legacy URIs. An explicit
`--actions` overrides the stored profile.

## Fill actions

The default sequence is `C14724635`:

| Code | Action |
| --- | --- |
| `1` | Select username |
| `2` | Select password |
| `3` | Fetch and select the current TOTP code |
| `4` | Type the selected value |
| `5` | Copy the selected value to the clipboard |
| `6` | Press Enter |
| `7` | Press Tab |
| `A` / `B` | Select the next / previous matching login |
| `C` / `D` | Select the first / last matching login |

For example, `C14724635` selects the first match, types the username, tabs,
types the password, presses Enter, then copies a freshly requested TOTP code.
Configure a different sequence with `--actions` or in the GUI. An account
navigation code separates action groups; following actions apply to the
selected match.

## Optional daemon mode

The authenticated daemon keeps a Bitwarden session on one host and accepts
client fill requests. It binds to loopback by default and stores its random
authentication token in an owner-only file under the user configuration
directory:

```sh
uv run bitwarden-autofiller-daemon start --email you@example.com
```

Stop it locally with:

```sh
uv run bitwarden-autofiller-daemon stop
```

To bind on a network interface, TLS is mandatory:

```sh
uv run bitwarden-autofiller-daemon start \
  --host 0.0.0.0 --port 64756 \
  --tls-certificate server-cert.pem --tls-private-key server-key.pem
```

The client must have a securely provisioned copy of the daemon token file and
trust the server certificate/CA:

```sh
uv run bitwarden-autofiller --app-id steam \
  --daemon-host autofill.example.net --daemon-port 64756 \
  --token-file ./daemon.token --ca-certificate server-cert.pem
```

Do not put the token or a master password in shell arguments, shared folders,
or source control. The token file must remain owner-only. The daemon protocol
uses bounded, authenticated messages; all non-loopback connections require
TLS.

## Security and privacy

- Master passwords and Bitwarden session keys are passed to `bw` through
  environment variables, never process arguments.
- The CLI error adapter does not echo raw subprocess output.
- Listing a vault produces summary objects only. A full login is fetched only
  when the selected action will emit its password; TOTP is fetched only when
  requested. The full vault is not cached.
- The local daemon uses a random owner-only token and constant-time token
  comparison. Remote daemon binds require TLS.
- Wayland input uses the XDG Remote Desktop portal via `eitype`; the compositor
  can ask the user to grant permission. If that backend is unavailable, the
  application fails closed rather than silently falling back to X11 input. Text
  is typed character-by-character using the active keymap; only an unmappable
  character is sent through the clipboard paste fallback before keymap typing
  resumes.
- Autofill necessarily places selected credential strings in process memory
  and sends them to the focused application. This is not an OS-level sandbox
  against a process running as the same user.
- Application logs contain operation/status summaries only. Use
  `--log-level DEBUG` or `BITWARDEN_AUTOFILLER_LOG_LEVEL=DEBUG` for diagnostics;
  account names, usernames, app URIs, passwords, TOTP codes, and session tokens
  are not logged.

## Development

The `src/bitwarden_autofiller` package is organized by responsibility:

- `vault/` contains Bitwarden CLI access, vault item parsing, authentication,
  and on-demand vault services.
- `filling/` contains app matching, fill actions, and workflow orchestration.
- `daemon/` contains the authenticated client/server protocol and token handling.
- `desktop/` contains the GUI and desktop-specific app/input adapters.
- `cli.py` is the one-shot command-line entry point.

```sh
uv sync --all-groups --extra gui
uv run pytest --cov
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv build
```

Install platform extras when exercising the corresponding input backend:

```sh
uv sync --all-groups --extra gui --extra desktop --extra wayland
```

Tests use fake Bitwarden CLI responses and local sockets; they do not need vault
credentials. GUI tests run with Qt's offscreen platform. The GUI is also
manually smoke-tested in a private KDE session.

## License

AGPL-3.0-or-later. See [LICENSE](LICENSE).
