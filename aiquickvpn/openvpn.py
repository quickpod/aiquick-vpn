r"""The OpenVPN engine behind AIQuick VPN.

Split into pure, testable layers so almost everything works with no root, no
``openvpn`` binary and — crucially — **without ever touching the network**:

* **Config parsing** — :func:`parse_config` turns the text of an ``.ovpn`` file
  into a structured :class:`ConfigInfo` (remotes, protocol, device, cipher,
  whether it needs a username/password, which inline blocks it carries).  Pure.
* **Profile store** — :func:`import_profile`, :func:`list_profiles`,
  :func:`profile_path`, :func:`read_profile`, :func:`remove_profile`.  Imported
  ``.ovpn`` files live under :func:`aiquickvpn.config.profiles_dir`.  Nothing is
  fetched or connected on import.
* **Argument builder** — :func:`build_connect_args` produces the exact
  ``openvpn`` argument vector.  Pure, so the CLI and GUI share one source of
  truth and it can be unit-tested by asserting on the produced args.
* **Availability** — :func:`openvpn_available` / :func:`openvpn_version`.  On a
  host with no ``openvpn`` binary the module still imports and every entry point
  degrades with a clear message instead of crashing.
* **Connection** — :class:`VPNConnection` spawns and supervises the ``openvpn``
  process, classifying its log with the pure :func:`parse_state_event`.  The one
  and only place we actually launch ``openvpn`` is :func:`_spawn`, the single
  seam tests monkeypatch — so the state machine is exercised end-to-end with a
  fake process and **no real VPN is ever dialed in the test-suite**.

The app never connects on its own: importing this package, listing/inspecting
profiles and reading status all stay completely offline.  A tunnel is
established only when the user explicitly calls :func:`VPNConnection.start` /
:func:`connect_blocking`.  Every failure raises :class:`AIQuickVPNError`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import config as appconfig
from .errors import AIQuickVPNError

# --------------------------------------------------------------------------- #
# Connection states
# --------------------------------------------------------------------------- #
DISCONNECTED = "disconnected"
CONNECTING = "connecting"
CONNECTED = "connected"
RECONNECTING = "reconnecting"
DISCONNECTING = "disconnecting"
ERROR = "error"

STATES = (DISCONNECTED, CONNECTING, CONNECTED, RECONNECTING, DISCONNECTING, ERROR)

PROFILE_SUFFIX = ".ovpn"
# Client directives that, when present, mark a file as a usable OpenVPN profile.
_CLIENT_MARKERS = ("remote", "client", "<connection>", "tls-client", "pull")


# --------------------------------------------------------------------------- #
# Structured config
# --------------------------------------------------------------------------- #
@dataclass
class Remote:
    """A single ``remote`` server entry from a profile."""

    host: str
    port: int = 1194
    proto: str = "udp"

    def describe(self) -> str:
        return f"{self.host}:{self.port}/{self.proto}"


@dataclass
class ConfigInfo:
    """A parsed, structured view of an ``.ovpn`` profile (no secrets kept)."""

    remotes: List[Remote] = field(default_factory=list)
    proto: str = "udp"
    dev: str = "tun"
    cipher: Optional[str] = None
    auth: Optional[str] = None
    auth_user_pass: bool = False        # needs an interactive username/password?
    inline_blocks: List[str] = field(default_factory=list)  # ca, cert, key, tls-auth…
    directives: int = 0
    warnings: List[str] = field(default_factory=list)

    @property
    def has_inline_ca(self) -> bool:
        return "ca" in self.inline_blocks

    def as_dict(self):
        return {
            "remotes": [r.describe() for r in self.remotes],
            "proto": self.proto,
            "dev": self.dev,
            "cipher": self.cipher,
            "auth": self.auth,
            "auth_user_pass": self.auth_user_pass,
            "inline_blocks": list(self.inline_blocks),
            "warnings": list(self.warnings),
        }


# --------------------------------------------------------------------------- #
# Config parsing (pure — no I/O, no network)
# --------------------------------------------------------------------------- #
def _norm_proto(tok: str) -> str:
    tok = (tok or "").strip().lower()
    if tok in ("tcp", "tcp-client", "tcp4", "tcp4-client", "tcp6", "tcp6-client"):
        return "tcp"
    return "udp"


def looks_like_ovpn(text: str) -> bool:
    """Heuristic: does *text* look like an OpenVPN client profile?

    True if any recognizable client directive or inline block is present.  Used
    to reject obviously-wrong imports early (a clear message beats a cryptic
    ``openvpn`` failure later).
    """
    if not text:
        return False
    low = text.lower()
    return any(m in low for m in _CLIENT_MARKERS)


def parse_config(text: str) -> ConfigInfo:
    """Parse the text of an ``.ovpn`` file into a :class:`ConfigInfo`.

    Tolerant and pure: unknown directives are ignored, inline ``<tag>…</tag>``
    blocks are recorded by name (their bodies are never inspected or retained),
    and an empty/None input yields an empty info with a warning (never raises).
    """
    info = ConfigInfo()
    if not text:
        info.warnings.append("empty configuration")
        return info

    global_port: Optional[int] = None
    global_proto: Optional[str] = None
    in_block: Optional[str] = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue

        # inline <tag> … </tag> blocks (ca/cert/key/tls-auth/tls-crypt…)
        if in_block:
            if line.lower() == f"</{in_block}>":
                in_block = None
            continue
        m = re.match(r"^<([a-zA-Z0-9_-]+)>$", line)
        if m:
            in_block = m.group(1).lower()
            if in_block not in info.inline_blocks:
                info.inline_blocks.append(in_block)
            continue

        parts = line.split()
        key = parts[0].lower()
        args = parts[1:]
        info.directives += 1

        if key == "remote" and args:
            host = args[0]
            port = 1194
            proto = None
            if len(args) >= 2 and args[1].isdigit():
                port = int(args[1])
            if len(args) >= 3:
                proto = _norm_proto(args[2])
            info.remotes.append(Remote(host=host, port=port,
                                       proto=proto or "udp"))
        elif key == "port" and args and args[0].isdigit():
            global_port = int(args[0])
        elif key == "proto" and args:
            global_proto = _norm_proto(args[0])
        elif key == "dev" and args:
            info.dev = args[0].lower()
        elif key in ("cipher", "data-ciphers") and args:
            info.cipher = args[0]
        elif key == "auth" and args:
            info.auth = args[0]
        elif key == "auth-user-pass":
            # No file argument -> credentials are prompted interactively.
            info.auth_user_pass = not bool(args)

    # Apply global proto/port to remotes that did not specify their own.
    if global_proto:
        info.proto = global_proto
    elif info.remotes:
        info.proto = info.remotes[0].proto
    for r in info.remotes:
        # A remote line that omitted its port inherits a global 'port N'.
        if global_port and r.port == 1194:
            r.port = global_port

    if not info.remotes:
        info.warnings.append("no 'remote' server line found")
    return info


# --------------------------------------------------------------------------- #
# Argument builder (pure)
# --------------------------------------------------------------------------- #
def build_connect_args(
    profile_file: str,
    *,
    auth_file: Optional[str] = None,
    writepid: Optional[str] = None,
    log_file: Optional[str] = None,
    mgmt_port: Optional[int] = None,
    verb: int = 3,
) -> List[str]:
    """Build the ``openvpn`` argument vector (no leading ``openvpn``).

    ``--config`` comes first so any later flag (e.g. an ``--auth-user-pass``
    credentials file) deliberately overrides the profile's own directive::

        build_connect_args("/cfg/office.ovpn", writepid="/run/x.pid")
            -> ["--config", "/cfg/office.ovpn", "--nobind",
                "--writepid", "/run/x.pid", "--verb", "3"]
    """
    if not profile_file:
        raise AIQuickVPNError("no profile file given")
    args: List[str] = ["--config", profile_file, "--nobind"]
    if auth_file:
        args += ["--auth-user-pass", auth_file]
    if writepid:
        args += ["--writepid", writepid]
    if log_file:
        args += ["--log", log_file]
    if mgmt_port:
        args += ["--management", "127.0.0.1", str(int(mgmt_port))]
    args += ["--verb", str(int(verb))]
    return args


# --------------------------------------------------------------------------- #
# Log-line classification (pure)
# --------------------------------------------------------------------------- #
# Ordered (pattern, state) — first match wins.
_STATE_PATTERNS = (
    (re.compile(r"Initialization Sequence Completed", re.I), CONNECTED),
    (re.compile(r"AUTH_FAILED|auth-failure|authenticate/Deferred", re.I), ERROR),
    (re.compile(r"Cannot resolve host address|RESOLVE:", re.I), ERROR),
    (re.compile(r"TLS Error|TLS handshake failed|TLS key negotiation failed", re.I), ERROR),
    (re.compile(r"Connection reset|Restart pause|SIGUSR1|reconnecting", re.I), RECONNECTING),
    (re.compile(r"process exiting|SIGTERM.*exiting|Closing TUN/TAP", re.I), DISCONNECTED),
    (re.compile(r"Attempting to establish|TCP/UDP: Preparing|Connecting to|"
                r"TLS: Initial packet", re.I), CONNECTING),
)


def parse_state_event(line: str) -> Optional[str]:
    """Classify one ``openvpn`` log line into a state, or ``None`` if unrelated."""
    if not line:
        return None
    for pat, state in _STATE_PATTERNS:
        if pat.search(line):
            return state
    return None


# --------------------------------------------------------------------------- #
# Profile store
# --------------------------------------------------------------------------- #
_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_name(name: str) -> str:
    """Turn an arbitrary label into a safe profile stem (no path separators)."""
    name = (name or "").strip()
    if name.lower().endswith(PROFILE_SUFFIX):
        name = name[: -len(PROFILE_SUFFIX)]
    name = os.path.basename(name)               # strip any directory part
    name = _NAME_RE.sub("-", name).strip("-.")
    if not name:
        raise AIQuickVPNError("please give the profile a name")
    return name


def profile_path(name: str) -> str:
    """Absolute path a profile named *name* would live at (may not exist)."""
    return os.path.join(appconfig.profiles_dir(), sanitize_name(name) + PROFILE_SUFFIX)


def list_profiles() -> List[str]:
    """Sorted names of imported profiles (``[]`` if none)."""
    d = appconfig.profiles_dir()
    if not os.path.isdir(d):
        return []
    names = []
    for fn in os.listdir(d):
        if fn.lower().endswith(PROFILE_SUFFIX):
            names.append(fn[: -len(PROFILE_SUFFIX)])
    return sorted(names, key=str.lower)


def read_profile(name: str) -> str:
    """Return the text of an imported profile (raises if it is missing)."""
    p = profile_path(name)
    if not os.path.exists(p):
        raise AIQuickVPNError(f"no profile named {sanitize_name(name)!r}")
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError as exc:
        raise AIQuickVPNError(f"could not read profile {name!r}: {exc}")


def profile_info(name: str) -> ConfigInfo:
    """Parsed :class:`ConfigInfo` for an imported profile."""
    return parse_config(read_profile(name))


def import_profile(source: str, name: Optional[str] = None,
                   *, is_text: bool = False, overwrite: bool = False) -> str:
    """Import an ``.ovpn`` profile and return its stored name.

    *source* is a filesystem path to a ``.ovpn`` file, or the config text itself
    when ``is_text=True``.  The content is validated as an OpenVPN profile and
    copied into the per-OS profiles directory — **nothing is connected**.  If
    *name* is omitted it is derived from the source filename.
    """
    if is_text:
        text = source or ""
        base = name or "profile"
    else:
        if not source or not os.path.isfile(source):
            raise AIQuickVPNError(f"file not found: {source!r}")
        try:
            with open(source, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as exc:
            raise AIQuickVPNError(f"could not read {source!r}: {exc}")
        base = name or os.path.basename(source)

    if not looks_like_ovpn(text):
        raise AIQuickVPNError(
            "that does not look like an OpenVPN profile "
            "(no 'remote'/'client' directive found)")

    stem = sanitize_name(base)
    appconfig.ensure_dirs()
    dest = os.path.join(appconfig.profiles_dir(), stem + PROFILE_SUFFIX)
    if os.path.exists(dest) and not overwrite:
        raise AIQuickVPNError(
            f"a profile named {stem!r} already exists (use overwrite to replace)")
    try:
        tmp = dest + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, dest)
    except OSError as exc:
        raise AIQuickVPNError(f"could not save profile: {exc}")
    return stem


def remove_profile(name: str) -> bool:
    """Delete an imported profile (raises if it is not present)."""
    p = profile_path(name)
    if not os.path.exists(p):
        raise AIQuickVPNError(f"no profile named {sanitize_name(name)!r} to remove")
    try:
        os.remove(p)
    except OSError as exc:
        raise AIQuickVPNError(f"could not remove profile: {exc}")
    return True


# --------------------------------------------------------------------------- #
# Availability / environment
# --------------------------------------------------------------------------- #
def openvpn_path() -> Optional[str]:
    """Absolute path to the ``openvpn`` binary, or ``None`` if not installed."""
    found = shutil.which("openvpn")
    if found:
        return found
    cands = [
        "/usr/sbin/openvpn", "/usr/bin/openvpn", "/sbin/openvpn",
        "/usr/local/sbin/openvpn", "/usr/local/bin/openvpn",
        "/opt/homebrew/sbin/openvpn",
    ]
    if os.name == "nt":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        cands += [os.path.join(pf, "OpenVPN", "bin", "openvpn.exe")]
    for c in cands:
        if os.path.exists(c):
            return c
    return None


def openvpn_available() -> bool:
    """True only if an ``openvpn`` binary is present on this host.

    Every entry point checks this first, so with no binary installed the app
    stays importable and degrades with a clear message rather than raising deep
    in subprocess land.
    """
    return openvpn_path() is not None


def openvpn_version() -> Optional[str]:
    """Return the ``openvpn`` version string, or ``None`` if unavailable."""
    path = openvpn_path()
    if not path:
        return None
    try:
        proc = subprocess.run([path, "--version"], capture_output=True,
                              text=True, timeout=10, check=False)
    except Exception:
        return None
    line = (proc.stdout or proc.stderr or "").splitlines()
    if not line:
        return None
    m = re.search(r"OpenVPN\s+([0-9][0-9.]*)", line[0])
    return m.group(1) if m else line[0].strip()


def _privilege_prefix() -> List[str]:
    """Command prefix that gains root to bring a tunnel up (needs a tun device).

    Prefers ``pkexec`` (graphical polkit prompt, so the GUI needs no terminal);
    falls back to non-interactive ``sudo -n``; needs nothing when already root
    or on Windows (the service/installer handles elevation there).
    """
    if os.name == "nt":
        return []
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return []
    pkexec = shutil.which("pkexec")
    if pkexec:
        return [pkexec]
    sudo = shutil.which("sudo")
    if sudo:
        return [sudo, "-n"]
    return []


def unavailable_message() -> str:
    """The single friendly 'openvpn missing' message, shared by CLI and GUI."""
    if os.name == "nt":
        return ("OpenVPN is not installed. AIQuick VPN drives the OpenVPN "
                "client — install OpenVPN Community (openvpn.net) and reopen "
                "the app.")
    return ("OpenVPN is not installed. AIQuick VPN drives the OpenVPN client; "
            "install it with your package manager (e.g. 'sudo apt install "
            "openvpn') and try again.")


# --------------------------------------------------------------------------- #
# Subprocess boundary (the single seam tests monkeypatch)
# --------------------------------------------------------------------------- #
def _spawn(argv: List[str]):
    """Launch *argv* and return the process handle (stdout+stderr merged, text).

    The ONE place AIQuick VPN actually starts ``openvpn``.  Tests replace this
    with a fake process so the connection state machine is exercised without a
    real VPN or network.
    """
    try:
        return subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True, bufsize=1)
    except FileNotFoundError as exc:
        raise AIQuickVPNError(f"could not launch openvpn: {exc}")
    except Exception as exc:  # pragma: no cover - defensive
        raise AIQuickVPNError(f"could not start openvpn: {exc}")


# --------------------------------------------------------------------------- #
# Connection supervisor
# --------------------------------------------------------------------------- #
class VPNConnection:
    """Supervises one ``openvpn`` process and tracks its live state.

    Construct with a profile name and optional callbacks; call :meth:`start` to
    bring the tunnel up (this is the only method that actually launches
    ``openvpn``) and :meth:`stop` to tear it down.  A background reader thread
    classifies the process log via :func:`parse_state_event` and reports state
    transitions and log lines through the callbacks.

    ``on_state(state)`` and ``on_log(line)`` are invoked from the reader thread;
    a GUI should marshal them back to the UI thread (e.g. ``self.after``).
    """

    def __init__(self, profile_name: str, *, on_state=None, on_log=None,
                 privileged: bool = True):
        self.profile_name = sanitize_name(profile_name)
        self._on_state = on_state
        self._on_log = on_log
        self._privileged = privileged
        self._proc = None
        self._reader = None
        self.state = DISCONNECTED
        self.last_error: Optional[str] = None

    # -- lifecycle -------------------------------------------------------
    def start(self, *, auth_file: Optional[str] = None) -> None:
        """Bring the tunnel up for this connection's profile (explicit action).

        Raises :class:`AIQuickVPNError` if ``openvpn`` is missing or the profile
        does not exist.  Returns as soon as the process is launched; watch the
        ``on_state`` callback for the transition to :data:`CONNECTED`.
        """
        if self._proc is not None:
            raise AIQuickVPNError("this connection is already running")
        if not openvpn_available():
            raise AIQuickVPNError(unavailable_message())
        pfile = profile_path(self.profile_name)
        if not os.path.exists(pfile):
            raise AIQuickVPNError(f"no profile named {self.profile_name!r}")

        args = build_connect_args(pfile, auth_file=auth_file)
        argv = [*_privilege_prefix(), openvpn_path(), *args] if self._privileged \
            else [openvpn_path(), *args]
        self._set_state(CONNECTING)
        self._proc = _spawn(argv)
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self):
        proc = self._proc
        try:
            if proc.stdout is not None:
                for line in proc.stdout:
                    line = line.rstrip("\n")
                    if self._on_log:
                        try:
                            self._on_log(line)
                        except Exception:
                            pass
                    ev = parse_state_event(line)
                    if ev == ERROR:
                        self.last_error = line
                    if ev is not None:
                        self._set_state(ev)
        except Exception:
            pass
        # process ended
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        if self.state not in (ERROR,):
            self._set_state(DISCONNECTED)

    def _set_state(self, state):
        if state not in STATES:
            return
        self.state = state
        if self._on_state:
            try:
                self._on_state(state)
            except Exception:
                pass

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stop(self, timeout: float = 8.0) -> None:
        """Tear the tunnel down (terminate the ``openvpn`` process).  Never raises."""
        proc = self._proc
        if proc is None:
            self._set_state(DISCONNECTED)
            return
        self._set_state(DISCONNECTING)
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=timeout)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        self._proc = None
        self._set_state(DISCONNECTED)


def connect_blocking(profile_name: str, *, auth_file: Optional[str] = None,
                     privileged: bool = True, out=None) -> int:
    """Connect in the foreground, streaming ``openvpn`` output until it exits.

    Used by the CLI: it truly shells out to ``openvpn`` and blocks (Ctrl-C
    stops it, the standard OpenVPN idiom).  Returns the process exit code.
    Raises :class:`AIQuickVPNError` before launching if ``openvpn`` or the
    profile is missing.
    """
    if out is None:
        out = sys.stdout
    if not openvpn_available():
        raise AIQuickVPNError(unavailable_message())
    pfile = profile_path(profile_name)
    if not os.path.exists(pfile):
        raise AIQuickVPNError(f"no profile named {sanitize_name(profile_name)!r}")
    args = build_connect_args(pfile, auth_file=auth_file)
    argv = [*_privilege_prefix(), openvpn_path(), *args] if privileged \
        else [openvpn_path(), *args]
    proc = _spawn(argv)
    try:
        if proc.stdout is not None:
            for line in proc.stdout:
                out.write(line if line.endswith("\n") else line + "\n")
                try:
                    out.flush()
                except Exception:
                    pass
        proc.wait()
    except KeyboardInterrupt:  # pragma: no cover - interactive
        try:
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:
            pass
        return 130
    return proc.returncode if proc.returncode is not None else 0
