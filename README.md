# AIQuick VPN

A fast, **offline**, **100% open-source** OpenVPN client for Windows. Nothing is uploaded anywhere. Built entirely by AI with human testing and guidance, and published on [QuickOpen](https://quickopen.ai/projects/aiquick-vpn).

> **100% AI-built and open source.** Apache-2.0.

## What it does

A friendly, fully-offline OpenVPN client. Import your own .ovpn profile and the app manages connect, disconnect and live status with a tray indicator — nothing is dialed anywhere until you explicitly connect. No telemetry, no dial-home, no auto-update. Shells out to the system 'openvpn' binary when present and degrades with a clear message when it is not.

## Install

Download **`AIQuickVPN-Setup.exe`** from the [QuickOpen page](https://quickopen.ai/projects/aiquick-vpn) or the [GitHub release](https://github.com/quickpod/aiquick-vpn/releases/latest) and double-click it. It installs per-user, adds Desktop and Start Menu shortcuts, and can optionally trust the QuickOpen Root CA. Authenticode-signed by the QuickOpen Code Signing CA — verify at [quickopen.ai/trust](https://quickopen.ai/trust).

## Run from source

```sh
pip install -r requirements.txt
python aiquick_vpn_app.py          # GUI
python -m aiquickvpn --help    # CLI
```

It drives the system **`openvpn`** binary (install OpenVPN Community on Windows,
or `sudo apt install openvpn` on Linux). If it is not present, the app says so
clearly and simply does nothing — it never fails cryptically.

## Features

- **Preinstalled, but never dials on its own.** Importing a profile,
  inspecting it, or reading status all stay completely offline. A tunnel is
  established **only** when you press Connect (GUI) or run `connect` (CLI).
- **Bring your own `.ovpn`.** Import a standard OpenVPN client profile; the app
  parses and shows its remotes, protocol, cipher and whether it needs a
  username/password.
- **Connect / disconnect / live status** with a streaming session log, plus an
  optional **tray icon** whose colour reflects the tunnel state (green =
  connected, amber = connecting, red = failed, grey = off).
- **OS-aware storage.** Imported profiles and settings live in the right
  per-OS location — `%APPDATA%\AIQuickVPN` on Windows, `$XDG_CONFIG_HOME`
  (`~/.config/aiquick-vpn`) on Linux, Application Support on macOS.
- **No phone-home.** No telemetry, no dial-home, no auto-update. Credentials
  are asked for at connect time, written to a private temp file consumed by
  `openvpn`, and deleted as soon as the tunnel is up — never stored.
- **Graceful without `openvpn`.** Missing binary → a clear, actionable message
  instead of a crash.

## CLI examples

```sh
aiquickvpn status                       # is openvpn installed? where are profiles?
aiquickvpn import ~/office.ovpn --name office
aiquickvpn list                         # imported profiles + their first remote
aiquickvpn info office                  # remotes / proto / cipher / login type
aiquickvpn connect office               # brings the tunnel UP (Ctrl-C to stop)
aiquickvpn connect office --auth-user-pass ~/creds.txt   # non-interactive auth
aiquickvpn remove office
```

`connect` is the only command that dials out; it shells out to `openvpn` and
runs in the foreground. Bringing a tunnel up needs root/administrator rights
(a tun/tap device); on Linux the app elevates via `pkexec`/`sudo` when needed.

## License

Apache-2.0 — see [LICENSE](LICENSE). A 100% AI-built project published on QuickOpen.
