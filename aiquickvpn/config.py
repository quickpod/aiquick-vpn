r"""OS-aware config + data locations for AIQuick VPN, plus a tiny JSON store.

This module owns *where* AIQuick VPN keeps things, and it does so by **detecting
the platform** rather than hardcoding a single layout (requirement A8):

* **Windows**   -> ``%APPDATA%\AIQuickVPN``            (roaming app data)
* **macOS**     -> ``~/Library/Application Support/AIQuickVPN``
* **Linux/BSD** -> ``$XDG_CONFIG_HOME/aiquick-vpn`` or ``~/.config/aiquick-vpn``

Imported ``.ovpn`` profiles live in ``<config_dir>/profiles``; the small JSON
config (theme + recently-used profile) lives in ``<config_dir>/config.json``.
Setting ``AIQUICK_VPN_CONFIG_DIR`` overrides everything (used by the test-suite
to keep all state inside a tmp tree, and handy for portable installs).

Every function here is defensive: a corrupt or unreadable config must never stop
the app from starting, so :func:`load` always returns valid defaults.
"""

from __future__ import annotations

import json
import os
import sys

APP_DIRNAME_WIN = "AIQuickVPN"      # %APPDATA%\AIQuickVPN
APP_DIRNAME_XDG = "aiquick-vpn"     # ~/.config/aiquick-vpn
CONFIG_NAME = "config.json"
PROFILES_DIRNAME = "profiles"
VALID_THEMES = ("light", "dark")
ENV_OVERRIDE = "AIQUICK_VPN_CONFIG_DIR"


def config_dir():
    r"""Per-OS base directory for AIQuick VPN's config + imported profiles.

    Detected, not hardcoded (A8).  Precedence:
    ``$AIQUICK_VPN_CONFIG_DIR`` -> ``%APPDATA%\AIQuickVPN`` on Windows ->
    ``~/Library/Application Support/AIQuickVPN`` on macOS ->
    ``$XDG_CONFIG_HOME/aiquick-vpn`` (or ``~/.config/aiquick-vpn``) elsewhere.
    The directory is created on demand by the callers that write to it.
    """
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        return override
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Roaming")
        return os.path.join(base, APP_DIRNAME_WIN)
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library",
                            "Application Support", APP_DIRNAME_WIN)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = xdg if xdg else os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, APP_DIRNAME_XDG)


def profiles_dir():
    """Directory holding imported ``.ovpn`` profiles (``<config_dir>/profiles``)."""
    return os.path.join(config_dir(), PROFILES_DIRNAME)


def config_path():
    return os.path.join(config_dir(), CONFIG_NAME)


def ensure_dirs():
    """Create the config + profiles directories (best-effort)."""
    try:
        os.makedirs(profiles_dir(), exist_ok=True)
    except Exception:
        pass


def _defaults():
    return {"theme": "dark", "recent": None}


def load():
    """Return the config dict, always with ``theme`` and ``recent`` keys."""
    cfg = _defaults()
    try:
        with open(config_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            if data.get("theme") in VALID_THEMES:
                cfg["theme"] = data["theme"]
            recent = data.get("recent")
            if isinstance(recent, str) and recent.strip():
                cfg["recent"] = recent
    except Exception:
        pass  # missing/corrupt -> defaults; never fatal
    return cfg


def save(cfg):
    """Persist *cfg* (best-effort; failures are swallowed)."""
    try:
        os.makedirs(config_dir(), exist_ok=True)
        clean = {
            "theme": cfg.get("theme") if cfg.get("theme") in VALID_THEMES else "dark",
            "recent": cfg.get("recent") if isinstance(cfg.get("recent"), str) else None,
        }
        tmp = config_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(clean, fh, indent=2)
        os.replace(tmp, config_path())
    except Exception:
        pass


def get_theme():
    return load().get("theme", "dark")


def set_theme(theme):
    if theme not in VALID_THEMES:
        return
    cfg = load()
    cfg["theme"] = theme
    save(cfg)


def get_recent():
    return load().get("recent")


def set_recent(name):
    cfg = load()
    cfg["recent"] = name or None
    save(cfg)
