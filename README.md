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
- On Wayland, install the `wayland` extra for active-app detection through
  KWin scripting and the wlr foreign-toplevel protocol. Manual app-ID entry
  remains available if a compositor does not expose either interface.

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
different delay. Use `--help` for all options.

In the GUI, connect to the vault and detect or enter the target application ID.
Detection waits through a focus countdown on both X11 and Wayland. Wayland
detection uses KWin's scripting API or the compositor's foreign-toplevel
protocol when available; otherwise enter the ID manually. Load the mapped
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
application ID in the GUI or CLI. Matching is case-insensitive. On supported
Wayland compositors, detection reads the compositor-reported application ID or
resource class; app IDs can differ between compositors, so confirm the detected
value against the URI you mapped. No generic XDG portal currently provides this
information, so unsupported compositors use the manual-ID fallback.

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
  application fails closed rather than silently falling back to X11 input.
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
