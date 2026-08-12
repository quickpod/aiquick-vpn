r"""Optional system-tray presence for AIQuick VPN (connect/disconnect + status).

This is a *plus*, not a requirement: it is built on ``pystray`` (+ Pillow) and is
entirely guarded.  :func:`start_tray` returns ``None`` — harmlessly — when
``pystray``/Pillow are missing, when there is no display, or if anything goes
wrong building the icon, so importing this module and calling it is always safe
on a headless CI box.  When it does run, the tray icon colour reflects the live
VPN state and its menu offers Connect/Disconnect, Show and Quit.

Nothing here ever connects on its own; it only calls back into the callbacks the
GUI supplies.
"""

from __future__ import annotations

import os
import sys
import threading

from .openvpn import (
    CONNECTED,
    CONNECTING,
    DISCONNECTED,
    DISCONNECTING,
    ERROR,
    RECONNECTING,
)

# State -> RGB dot colour for the tray glyph.
_STATE_COLOR = {
    CONNECTED: (14, 145, 90),      # green
    CONNECTING: (224, 166, 58),    # amber
    RECONNECTING: (224, 166, 58),
    DISCONNECTING: (224, 166, 58),
    DISCONNECTED: (120, 130, 145),  # grey
    ERROR: (207, 45, 58),          # red
}
_ACCENT = (8, 145, 178)            # AIQuick VPN accent (shield outline)


def _tray_available() -> bool:
    """True only if a tray can plausibly be shown here (deps + a display)."""
    if os.environ.get("AIQUICK_VPN_NO_TRAY"):
        return False
    if sys.platform == "win32" or sys.platform == "darwin":
        pass  # a desktop session is assumed present
    elif not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return False
    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception:
        return False
    return True


def _make_image(state):
    from PIL import Image, ImageDraw
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # A small shield outline (the app motif) with a state-coloured status dot.
    d.polygon([(20, 8), (44, 8), (52, 20), (32, 58), (12, 20)],
              outline=_ACCENT, width=4)
    col = _STATE_COLOR.get(state, _STATE_COLOR[DISCONNECTED])
    d.ellipse([26, 24, 38, 36], fill=col)
    return img


class TrayController:
    """Thin controller around a running ``pystray`` icon (thread-managed)."""

    def __init__(self, icon):
        self._icon = icon
        self._thread = None

    def _run(self):
        try:
            self._icon.run()
        except Exception:
            pass

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def set_state(self, state):
        try:
            self._icon.icon = _make_image(state)
            self._icon.title = f"AIQuick VPN — {state}"
        except Exception:
            pass

    def stop(self):
        try:
            self._icon.stop()
        except Exception:
            pass


def start_tray(*, on_toggle=None, on_show=None, on_quit=None,
               initial_state=DISCONNECTED):
    """Start a tray icon and return a :class:`TrayController`, or ``None``.

    ``on_toggle`` connects/disconnects, ``on_show`` raises the window, ``on_quit``
    exits the app.  Returns ``None`` (never raises) if a tray cannot be shown.
    """
    if not _tray_available():
        return None
    try:
        import pystray

        def _cb(fn):
            def handler(icon=None, item=None):
                if fn:
                    try:
                        fn()
                    except Exception:
                        pass
            return handler

        menu = pystray.Menu(
            pystray.MenuItem("Show AIQuick VPN", _cb(on_show), default=True),
            pystray.MenuItem("Connect / Disconnect", _cb(on_toggle)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", _cb(on_quit)),
        )
        icon = pystray.Icon("aiquick-vpn", _make_image(initial_state),
                            "AIQuick VPN", menu)
        controller = TrayController(icon)
        controller.start()
        return controller
    except Exception:
        return None
