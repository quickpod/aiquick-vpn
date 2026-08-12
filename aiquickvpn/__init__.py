r"""aiquickvpn -- a small, offline-first OpenVPN client library behind AIQuick VPN.

Public surface (all failures raise :class:`AIQuickVPNError`)::

    from aiquickvpn import openvpn
    name = openvpn.import_profile("~/office.ovpn")   # nothing is connected
    info = openvpn.profile_info(name)                # parsed remotes/proto/…
    conn = openvpn.VPNConnection(name, on_state=print)
    conn.start()                                     # the ONLY dial-out step
    ...
    conn.stop()

Design guarantees:
  * **Never dials home / never auto-connects.** Importing this package,
    listing/inspecting profiles and reading availability all stay offline. A
    tunnel is established only by an explicit :meth:`VPNConnection.start` /
    :func:`openvpn.connect_blocking` call.
  * The pure helpers (:func:`parse_config`, :func:`build_connect_args`,
    :func:`parse_state_event`, the profile store) need no root and import on any
    platform; the connection layer shells out to the system ``openvpn`` binary
    and, when it is absent, degrades with a clear message.
  * Config + imported ``.ovpn`` profiles are stored in an OS-aware location
    (XDG on Linux, ``%APPDATA%`` on Windows, Application Support on macOS).

100% AI-built, open source, published on QuickOpen (quickopen.ai).
"""

from __future__ import annotations

from . import config, openvpn
from .errors import AIQuickVPNError
from .openvpn import (
    CONNECTED,
    CONNECTING,
    DISCONNECTED,
    DISCONNECTING,
    ERROR,
    RECONNECTING,
    STATES,
    ConfigInfo,
    Remote,
    VPNConnection,
    build_connect_args,
    connect_blocking,
    import_profile,
    list_profiles,
    openvpn_available,
    openvpn_version,
    parse_config,
    parse_state_event,
    profile_info,
    profile_path,
    read_profile,
    remove_profile,
)

__version__ = "1.0.0"

__all__ = [
    "AIQuickVPNError",
    "ConfigInfo",
    "Remote",
    "VPNConnection",
    "STATES",
    "DISCONNECTED",
    "CONNECTING",
    "CONNECTED",
    "RECONNECTING",
    "DISCONNECTING",
    "ERROR",
    "parse_config",
    "build_connect_args",
    "parse_state_event",
    "import_profile",
    "list_profiles",
    "read_profile",
    "profile_info",
    "profile_path",
    "remove_profile",
    "openvpn_available",
    "openvpn_version",
    "connect_blocking",
    "config",
    "openvpn",
]
