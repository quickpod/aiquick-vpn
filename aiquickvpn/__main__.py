r"""Command-line interface: ``python -m aiquickvpn <command> ...``.

Commands (all print clean output; any :class:`AIQuickVPNError` exits non-zero
with a one-line ``error: ...`` message and no traceback)::

    aiquickvpn status                       # openvpn availability + version
    aiquickvpn list                         # imported profiles
    aiquickvpn import ~/office.ovpn [--name office] [--force]
    aiquickvpn info office                  # parsed remotes / proto / cipher
    aiquickvpn remove office
    aiquickvpn connect office [--auth-user-pass CREDFILE]   # brings the tunnel UP

Nothing dials out until you run ``connect`` — ``connect`` shells out to the
system ``openvpn`` binary and runs in the foreground (Ctrl-C stops it). If
``openvpn`` is not installed, every network command prints a clear message and
exits non-zero instead of failing cryptically.
"""

from __future__ import annotations

import argparse
import sys

from . import config as appconfig
from . import openvpn as ovpn
from .errors import AIQuickVPNError


# --- command handlers -------------------------------------------------------
def cmd_status(a):
    if ovpn.openvpn_available():
        ver = ovpn.openvpn_version() or "unknown version"
        print(f"OpenVPN: available ({ovpn.openvpn_path()}, {ver})")
    else:
        print("OpenVPN: NOT installed")
        print(ovpn.unavailable_message())
    profiles = ovpn.list_profiles()
    print(f"Config dir: {appconfig.config_dir()}")
    print(f"Profiles: {len(profiles)}"
          + (" (" + ", ".join(profiles) + ")" if profiles else ""))
    print("Not connected. A tunnel is only established when you run "
          "'aiquickvpn connect <profile>'.")


def cmd_list(a):
    profiles = ovpn.list_profiles()
    if not profiles:
        print("No profiles imported. Add one with: "
              "aiquickvpn import <file.ovpn>")
        return
    width = max(len(p) for p in profiles)
    for name in profiles:
        try:
            info = ovpn.profile_info(name)
            first = info.remotes[0].describe() if info.remotes else "(no remote)"
        except AIQuickVPNError:
            first = "(unreadable)"
        print(f"{name:<{width}}  {first}")


def cmd_import(a):
    name = ovpn.import_profile(a.file, a.name, overwrite=a.force)
    print(f"Imported profile {name!r} -> {ovpn.profile_path(name)}")


def _print_info(name, info):
    print(f"Profile: {name}")
    if info.remotes:
        for r in info.remotes:
            print(f"  remote   {r.describe()}")
    else:
        print("  remote   (none)")
    print(f"  proto    {info.proto}")
    print(f"  device   {info.dev}")
    if info.cipher:
        print(f"  cipher   {info.cipher}")
    if info.auth:
        print(f"  auth     {info.auth}")
    print(f"  login    {'username/password required' if info.auth_user_pass else 'certificate only'}")
    if info.inline_blocks:
        print(f"  inline   {', '.join(info.inline_blocks)}")
    for w in info.warnings:
        print(f"  warning  {w}")


def cmd_info(a):
    # Accept either an imported profile name or a path to an .ovpn file.
    import os
    if os.path.isfile(a.profile):
        info = ovpn.parse_config(open(a.profile, "r", encoding="utf-8",
                                      errors="replace").read())
        _print_info(os.path.basename(a.profile), info)
    else:
        _print_info(ovpn.sanitize_name(a.profile), ovpn.profile_info(a.profile))


def cmd_remove(a):
    ovpn.remove_profile(a.name)
    print(f"Removed profile {ovpn.sanitize_name(a.name)!r}")


def cmd_connect(a):
    # This is the ONLY command that dials out; it blocks until openvpn exits.
    print(f"Connecting profile {ovpn.sanitize_name(a.profile)!r} "
          f"(Ctrl-C to disconnect)…")
    return ovpn.connect_blocking(a.profile, auth_file=a.auth_user_pass)


# --- parser -----------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(
        prog="aiquickvpn",
        description="An offline OpenVPN client. Import your own .ovpn profile "
                    "and connect on demand — nothing is dialed anywhere until "
                    "you run 'connect'.")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("status", help="Show OpenVPN availability and version")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("list", help="List imported profiles")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("import", help="Import a .ovpn profile (no connection made)")
    s.add_argument("file", help="path to a .ovpn file")
    s.add_argument("--name", help="name to store it under (default: filename)")
    s.add_argument("--force", action="store_true",
                   help="overwrite an existing profile of the same name")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("info", help="Show parsed details of a profile or .ovpn file")
    s.add_argument("profile", help="imported profile name or path to a .ovpn file")
    s.set_defaults(func=cmd_info)

    s = sub.add_parser("remove", help="Delete an imported profile")
    s.add_argument("name")
    s.set_defaults(func=cmd_remove)

    s = sub.add_parser("connect", help="Bring the tunnel up (foreground; Ctrl-C stops)")
    s.add_argument("profile")
    s.add_argument("--auth-user-pass", dest="auth_user_pass", metavar="FILE",
                   help="file with two lines (username, password) for auth")
    s.set_defaults(func=cmd_connect)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        rc = args.func(args)
    except AIQuickVPNError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("\naborted", file=sys.stderr)
        return 130
    return rc if isinstance(rc, int) else 0


if __name__ == "__main__":
    sys.exit(main())
