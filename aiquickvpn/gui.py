#!/usr/bin/env python3
r"""AIQuick VPN -- an Aura (QuickOpen design system) GUI over the ``aiquickvpn`` library.

A single Aura window: a left sidebar (Connection, Profiles, About) and a main
panel that swaps to the selected section.  Every operation calls the tested core
library (never re-implements OpenVPN logic); the connection itself runs as a
supervised background process whose state and log stream back to the UI via
``self.after`` and are shown in the status bar and a live log view.

House-style guarantees baked in here:
  * Built on the vendored ``aiquickvpn/aura.py`` design system (CustomTkinter +
    darkdetect).  The PyInstaller build adds ``--collect-all customtkinter``.
  * **Never dials home / never auto-connects.**  Importing this module does
    nothing; building the window connects nothing.  A tunnel is established ONLY
    when the user presses Connect.
  * Degrades gracefully: with no display or without customtkinter it prints a
    note and returns 0; with no ``openvpn`` binary it shows a clear banner and
    disables Connect rather than failing.
  * Secrets stay in memory: a username/password (for profiles that need one) is
    prompted at connect time, written to a 0600 temp file consumed by openvpn,
    and deleted as soon as the tunnel is up — never persisted.
  * Optional tray presence (connect/disconnect + status colour); fully guarded.

100% AI-built, open source, published on QuickOpen (quickopen.ai).
"""

from __future__ import annotations

import os
import sys
import threading

# NOTE: tkinter/customtkinter are imported lazily inside main()/build_app so that
# merely importing this module (packaging, headless CI) never fails.

APP_NAME = "AIQuick VPN"
APP_VERSION = "1.0.0"
WINDOW_TITLE = "AIQuick VPN — by QuickOpen (quickopen.ai)"
PROJECT_URL = "https://quickopen.ai/projects/aiquick-vpn"
ACCENT = "#0891b2"      # cyan — matches the shield/keyhole icon

SECTIONS = [
    ("connection", "Connection", "⇄"),
    ("profiles", "Profiles", "▤"),
    ("about", "About", "ℹ"),
]

SECTION_DESCRIPTIONS = {
    "connection": "Choose an imported profile and connect on demand. Nothing is "
                  "dialed anywhere until you press Connect.",
    "profiles": "Import your own .ovpn files and inspect what they connect to. "
                "Importing never makes a connection.",
}


# ---------------------------------------------------------------------------
# Asset / frozen handling
# ---------------------------------------------------------------------------
def asset_path(name):
    """Locate a bundled asset from source OR a PyInstaller one-file build."""
    roots = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(meipass)
        roots.append(os.path.dirname(os.path.abspath(sys.executable)))
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        roots += [here, os.path.dirname(here), os.getcwd()]
    for root in roots:
        candidate = os.path.join(root, name)
        if os.path.exists(candidate):
            return candidate
    return None


def open_with_default_app(path):
    """Open a file/URL with the OS default application, guarded."""
    try:
        if hasattr(os, "startfile"):
            os.startfile(path)                # noqa: S606
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", path])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# The app (built lazily; tkinter/customtkinter imported only inside build_app)
# ---------------------------------------------------------------------------
def build_app():
    """Construct and return the App class bound to live GUI imports."""
    import tempfile
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk
    import customtkinter as ctk

    from . import aura
    from . import config as appconfig
    from . import openvpn as ovpn
    from . import tray as traymod
    from .errors import AIQuickVPNError

    MONO = ("Consolas", 9) if sys.platform == "win32" else ("Monospace", 9)

    STATE_LABEL = {
        ovpn.DISCONNECTED: "Not connected",
        ovpn.CONNECTING: "Connecting…",
        ovpn.CONNECTED: "Connected",
        ovpn.RECONNECTING: "Reconnecting…",
        ovpn.DISCONNECTING: "Disconnecting…",
        ovpn.ERROR: "Connection failed",
    }

    class App(aura.AuraApp):
        def __init__(self):
            super().__init__(
                title=WINDOW_TITLE, app_name=APP_NAME, accent=ACCENT,
                theme=appconfig.get_theme(),
                icon_png=asset_path("aiquick-vpn.png"), version=APP_VERSION,
                tagline="offline OpenVPN",
                on_theme_change=appconfig.set_theme,
                size=(1040, 700), min_size=(880, 580))

            self._img_refs_gui = []
            self._conn = None            # live VPNConnection, or None
            self._auth_file = None       # temp credentials file (deleted after use)
            self._state = ovpn.DISCONNECTED
            self._tray = None

            self._set_icon()

            # header-right live connection indicator
            self._conn_lbl = ctk.CTkLabel(
                self.header_actions, text="● not connected",
                font=aura.font(role="caption"))
            self._conn_lbl.pack(side="right")

            for sid, label, glyph in SECTIONS:
                self.add_section(sid, label, glyph,
                                 getattr(self, "_build_" + sid))
            self.show("connection")
            self.set_status("Ready — nothing is connected.")
            self.protocol("WM_DELETE_WINDOW", self._on_close)
            self._start_tray()

        # ---- assets / icon
        def _set_icon(self):
            try:
                ico = asset_path("aiquick-vpn.ico")
                if ico and os.name == "nt":
                    self.iconbitmap(ico)
                    return
            except Exception:
                pass
            try:
                png = asset_path("aiquick-vpn.png")
                if png:
                    img = tk.PhotoImage(file=png)
                    self._img_refs_gui.append(img)
                    self.iconphoto(True, img)
            except Exception:
                pass  # icon is cosmetic; never block launch

        # ---- optional tray
        def _start_tray(self):
            try:
                self._tray = traymod.start_tray(
                    on_toggle=lambda: self.after(0, self._toggle_connection),
                    on_show=lambda: self.after(0, self._raise_window),
                    on_quit=lambda: self.after(0, self._on_close),
                    initial_state=self._state)
            except Exception:
                self._tray = None

        def _raise_window(self):
            try:
                self.deiconify()
                self.lift()
                self.focus_force()
            except Exception:
                pass

        # ---- status helpers
        def _show_error(self, message):
            self.set_error(message)

        def report_success(self, message):
            self.set_success(message)

        # ================================================================
        # Connection section
        # ================================================================
        def _build_connection(self, frame):
            aura.Caption(frame, SECTION_DESCRIPTIONS["connection"]).pack(
                anchor="w", pady=(0, 12))

            # openvpn availability banner
            self._avail_card = aura.Card(frame, title="OpenVPN")
            self._avail_card.pack(fill="x")
            self._avail_lbl = ctk.CTkLabel(
                self._avail_card.body, text="", justify="left", anchor="w",
                font=aura.font(role="body"), wraplength=620)
            self._avail_lbl.pack(anchor="w")

            # controls
            ctrl = aura.Card(frame, title="Tunnel")
            ctrl.pack(fill="x", pady=(14, 0))
            body = ctrl.body
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", pady=(0, 8))
            ctk.CTkLabel(row, text="Profile", width=70, anchor="w",
                         font=aura.font(role="body")).pack(side="left")
            self._profile_var = tk.StringVar(value="")
            self._profile_menu = aura.AuraOption(
                row, variable=self._profile_var, values=["(no profiles)"],
                width=240)
            self._profile_menu.pack(side="left")
            aura.AuraButton(row, "Refresh", kind="ghost", width=80,
                            command=self._refresh_profiles).pack(
                side="left", padx=(8, 0))

            staterow = ctk.CTkFrame(body, fg_color="transparent")
            staterow.pack(fill="x", pady=(4, 10))
            self._state_dot = ctk.CTkLabel(staterow, text="●",
                                           font=aura.font(16, "bold"))
            self._state_dot.pack(side="left")
            self._state_lbl = ctk.CTkLabel(
                staterow, text=STATE_LABEL[ovpn.DISCONNECTED],
                font=aura.font(role="heading"))
            self._state_lbl.pack(side="left", padx=(8, 0))

            btns = ctk.CTkFrame(body, fg_color="transparent")
            btns.pack(fill="x")
            self._connect_btn = aura.AuraButton(
                btns, "Connect", kind="primary", command=self._connect)
            self._connect_btn.pack(side="left")
            self._disconnect_btn = aura.AuraButton(
                btns, "Disconnect", kind="secondary", command=self._disconnect)
            self._disconnect_btn.pack(side="left", padx=8)
            self._disconnect_btn.configure(state="disabled")

            # log
            logcard = aura.Card(frame, title="Session log")
            logcard.pack(fill="both", expand=True, pady=(14, 0))
            lb = ctk.CTkFrame(logcard.body, fg_color="transparent")
            lb.pack(fill="both", expand=True)
            self._log = tk.Text(lb, wrap="char", height=12, font=MONO,
                                state="disabled", relief="flat", padx=8, pady=6)
            sb = ttk.Scrollbar(lb, orient="vertical", command=self._log.yview)
            self._log.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            self._log.pack(side="left", fill="both", expand=True)
            aura.track(self._log, "text")

            self._refresh_availability()
            self._refresh_profiles()
            self._apply_state(self._state)

        def _refresh_availability(self):
            if ovpn.openvpn_available():
                ver = ovpn.openvpn_version() or "unknown version"
                self._avail_lbl.configure(
                    text=f"Ready. OpenVPN {ver} detected at\n{ovpn.openvpn_path()}")
            else:
                self._avail_lbl.configure(text=ovpn.unavailable_message())

        def _refresh_profiles(self):
            names = ovpn.list_profiles()
            if names:
                self._profile_menu.configure(values=names)
                cur = self._profile_var.get()
                if cur not in names:
                    remembered = appconfig.get_recent()
                    self._profile_var.set(remembered if remembered in names
                                          else names[0])
            else:
                self._profile_menu.configure(values=["(no profiles)"])
                self._profile_var.set("(no profiles)")
            self._update_connect_enabled()

        def _update_connect_enabled(self):
            can = (ovpn.openvpn_available()
                   and bool(ovpn.list_profiles())
                   and self._state in (ovpn.DISCONNECTED, ovpn.ERROR))
            try:
                self._connect_btn.configure(state="normal" if can else "disabled")
            except Exception:
                pass

        def _log_write(self, text):
            try:
                self._log.configure(state="normal")
                self._log.insert("end", text if text.endswith("\n") else text + "\n")
                self._log.see("end")
                self._log.configure(state="disabled")
            except Exception:
                pass

        # -- connect / disconnect ----------------------------------------
        def _selected_profile(self):
            name = self._profile_var.get()
            if not name or name == "(no profiles)":
                return None
            return name

        def _prompt_auth_file(self, name):
            """Prompt for username/password and write a 0600 temp file for openvpn.

            Returns the temp-file path, or None if the user cancelled.  The file
            is deleted as soon as the tunnel is up (see :meth:`_clear_auth`).
            """
            user = simpledialog.askstring(
                APP_NAME, f"Username for {name}:", parent=self)
            if user is None:
                return None
            pw = simpledialog.askstring(
                APP_NAME, f"Password for {name}:", show="*", parent=self)
            if pw is None:
                return None
            fd, path = tempfile.mkstemp(prefix="aqvpn-", suffix=".auth")
            try:
                os.write(fd, (user + "\n" + pw + "\n").encode("utf-8"))
            finally:
                os.close(fd)
            try:
                os.chmod(path, 0o600)
            except Exception:
                pass
            return path

        def _clear_auth(self):
            if self._auth_file and os.path.exists(self._auth_file):
                try:
                    os.remove(self._auth_file)
                except Exception:
                    pass
            self._auth_file = None

        def _connect(self):
            if self._conn is not None and self._conn.is_running():
                self._show_error("Already connected — disconnect first.")
                return
            if not ovpn.openvpn_available():
                self._show_error(ovpn.unavailable_message())
                return
            name = self._selected_profile()
            if not name:
                self._show_error("Import a profile first (Profiles tab).")
                return
            # Ask for credentials only if the profile needs them.
            auth_file = None
            try:
                info = ovpn.profile_info(name)
            except AIQuickVPNError as exc:
                self._show_error(str(exc))
                return
            if info.auth_user_pass:
                auth_file = self._prompt_auth_file(name)
                if auth_file is None:
                    self.set_status("Ready — nothing is connected.")
                    return
            self._auth_file = auth_file

            self._log_write(f"--- connecting {name} ---")
            appconfig.set_recent(name)
            conn = ovpn.VPNConnection(
                name,
                on_state=lambda s: self.after(0, lambda: self._apply_state(s)),
                on_log=lambda ln: self.after(0, lambda: self._log_write(ln)))
            try:
                conn.start(auth_file=auth_file)
            except AIQuickVPNError as exc:
                self._clear_auth()
                self._show_error(str(exc))
                return
            self._conn = conn
            self.set_status("Connecting…", kind="working")

        def _disconnect(self):
            conn = self._conn
            if conn is None:
                self._apply_state(ovpn.DISCONNECTED)
                return
            self.set_status("Disconnecting…", kind="working")

            def work():
                conn.stop()
            threading.Thread(target=work, daemon=True).start()

        def _toggle_connection(self):
            if self._conn is not None and self._conn.is_running():
                self._disconnect()
            else:
                self.show("connection")
                self._connect()

        def _apply_state(self, state):
            self._state = state
            pal = aura.P()
            color = {
                ovpn.CONNECTED: pal["ok"],
                ovpn.CONNECTING: pal["accent"],
                ovpn.RECONNECTING: pal["warn"],
                ovpn.DISCONNECTING: pal["warn"],
                ovpn.ERROR: pal["danger"],
                ovpn.DISCONNECTED: pal["faint"],
            }.get(state, pal["faint"])
            # widgets may not exist yet if the panel is unbuilt
            for w, attr in ((getattr(self, "_state_dot", None), "text_color"),
                            (getattr(self, "_state_lbl", None), "text_color")):
                if w is not None:
                    try:
                        w.configure(text_color=color)
                    except Exception:
                        pass
            if getattr(self, "_state_lbl", None) is not None:
                try:
                    self._state_lbl.configure(text=STATE_LABEL.get(state, state))
                except Exception:
                    pass
            try:
                self._conn_lbl.configure(
                    text=("● connected" if state == ovpn.CONNECTED
                          else "● " + STATE_LABEL.get(state, state).lower()),
                    text_color=color)
            except Exception:
                pass
            running = state in (ovpn.CONNECTING, ovpn.CONNECTED,
                                ovpn.RECONNECTING, ovpn.DISCONNECTING)
            try:
                self._disconnect_btn.configure(
                    state="normal" if running else "disabled")
            except Exception:
                pass
            self._update_connect_enabled()

            if state == ovpn.CONNECTED:
                self._clear_auth()               # creds consumed; wipe temp file
                self.report_success("Connected.")
            elif state == ovpn.ERROR:
                self._clear_auth()
                self._show_error(
                    (self._conn.last_error if self._conn and self._conn.last_error
                     else "Connection failed — see the session log."))
            elif state == ovpn.DISCONNECTED:
                self._clear_auth()
                self.set_status("Not connected.")
                if self._conn is not None and not self._conn.is_running():
                    self._conn = None
            if self._tray is not None:
                self._tray.set_state(state)

        # ================================================================
        # Profiles section
        # ================================================================
        def _build_profiles(self, frame):
            aura.Caption(frame, SECTION_DESCRIPTIONS["profiles"]).pack(
                anchor="w", pady=(0, 12))
            body = ctk.CTkFrame(frame, fg_color="transparent")
            body.pack(fill="both", expand=True)

            left = aura.Card(body, title="Imported profiles")
            left.pack(side="left", fill="y", padx=(0, 14))
            box = ctk.CTkFrame(left.body, fg_color="transparent")
            box.pack(fill="both", expand=True)
            self._plist = tk.Listbox(box, height=15, width=26, activestyle="none",
                                     exportselection=False,
                                     font=aura.font(role="body"))
            sb = ttk.Scrollbar(box, orient="vertical", command=self._plist.yview)
            self._plist.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            self._plist.pack(side="left", fill="both", expand=True)
            aura.track(self._plist, "listbox")
            self._plist.bind("<<ListboxSelect>>", lambda e: self._show_profile_info())
            pbtns = ctk.CTkFrame(left.body, fg_color="transparent")
            pbtns.pack(fill="x", pady=(10, 0))
            aura.AuraButton(pbtns, "Import .ovpn…", kind="primary",
                            command=self._import_profile).pack(side="left")
            aura.AuraButton(pbtns, "Delete", kind="danger", width=72,
                            command=self._delete_profile).pack(
                side="left", padx=(8, 0))

            right = aura.Card(body, title="Profile details")
            right.pack(side="left", fill="both", expand=True)
            self._pinfo = tk.Text(right.body, wrap="word", height=16, font=MONO,
                                  state="disabled", relief="flat", padx=8, pady=6)
            self._pinfo.pack(fill="both", expand=True)
            aura.track(self._pinfo, "text")

            self._refresh_profile_list()

        def _refresh_profile_list(self):
            try:
                names = ovpn.list_profiles()
            except AIQuickVPNError as exc:
                self._show_error(str(exc))
                names = []
            self._plist.delete(0, "end")
            for n in names:
                self._plist.insert("end", n)

        def _selected_list_profile(self):
            sel = self._plist.curselection()
            if not sel:
                return None
            return self._plist.get(sel[0])

        def _show_profile_info(self):
            name = self._selected_list_profile()
            if not name:
                return
            try:
                info = ovpn.profile_info(name)
            except AIQuickVPNError as exc:
                self._show_error(str(exc))
                return
            lines = [f"Profile: {name}", ""]
            if info.remotes:
                for r in info.remotes:
                    lines.append(f"  remote   {r.describe()}")
            else:
                lines.append("  remote   (none found)")
            lines += [
                f"  proto    {info.proto}",
                f"  device   {info.dev}",
            ]
            if info.cipher:
                lines.append(f"  cipher   {info.cipher}")
            if info.auth:
                lines.append(f"  auth     {info.auth}")
            lines.append("  login    " + ("username/password required"
                         if info.auth_user_pass else "certificate only"))
            if info.inline_blocks:
                lines.append(f"  inline   {', '.join(info.inline_blocks)}")
            for w in info.warnings:
                lines.append(f"  warning  {w}")
            self._pinfo.configure(state="normal")
            self._pinfo.delete("1.0", "end")
            self._pinfo.insert("1.0", "\n".join(lines))
            self._pinfo.configure(state="disabled")

        def _import_profile(self):
            path = filedialog.askopenfilename(
                title="Choose an OpenVPN profile",
                filetypes=[("OpenVPN profiles", "*.ovpn *.conf"),
                           ("All files", "*.*")])
            if not path:
                return
            name = None
            try:
                name = ovpn.import_profile(path)
            except AIQuickVPNError as exc:
                # If it already exists, offer to overwrite.
                if "already exists" in str(exc) and messagebox.askyesno(
                        "Replace profile", str(exc) + "\n\nReplace it?",
                        parent=self):
                    try:
                        name = ovpn.import_profile(path, overwrite=True)
                    except AIQuickVPNError as exc2:
                        self._show_error(str(exc2))
                        return
                else:
                    self._show_error(str(exc))
                    return
            self._refresh_profile_list()
            self._refresh_profiles()
            self.report_success(f"Imported profile {name!r}.")

        def _delete_profile(self):
            name = self._selected_list_profile()
            if not name:
                self._show_error("Select a profile to delete.")
                return
            if not messagebox.askyesno(
                    "Delete profile", f"Delete profile {name!r}?", parent=self):
                return
            try:
                ovpn.remove_profile(name)
            except AIQuickVPNError as exc:
                self._show_error(str(exc))
                return
            self._refresh_profile_list()
            self._refresh_profiles()
            self.report_success(f"Deleted profile {name!r}.")

        # ================================================================
        # About
        # ================================================================
        def _build_about(self, frame):
            card = aura.Card(frame, title="About AIQuick VPN")
            card.pack(fill="x")
            aura.Heading(card.body, APP_NAME).pack(anchor="w")
            aura.Caption(card.body, f"Version {APP_VERSION}").pack(
                anchor="w", pady=(0, 10))
            ctk.CTkLabel(
                card.body, font=aura.font(), justify="left", anchor="w",
                wraplength=600,
                text="A preinstalled, fully-offline OpenVPN client. Import your "
                     "own .ovpn profile and connect on demand — the app manages "
                     "connect, disconnect and live status.\n\n"
                     "It never dials anywhere on its own: no telemetry, no "
                     "dial-home, no auto-update. A tunnel is established only "
                     "when you press Connect. Credentials are asked for at "
                     "connect time and never stored.").pack(anchor="w")
            aura.Caption(card.body,
                         "Licensed under Apache-2.0. Drives the OpenVPN client "
                         "(GPLv2); built on CustomTkinter (MIT).").pack(
                anchor="w", pady=(10, 4))
            aura.AuraButton(card.body, "Project page: quickopen.ai", kind="ghost",
                            command=lambda: open_with_default_app(
                                PROJECT_URL)).pack(anchor="w", pady=(6, 0))

        # ---- shutdown
        def _on_close(self):
            try:
                if self._conn is not None:
                    self._conn.stop()
            except Exception:
                pass
            self._clear_auth()
            if self._tray is not None:
                try:
                    self._tray.stop()
                except Exception:
                    pass
            self.destroy()

    return App


def main():
    """Entry point: build the root window and run.  Degrades on headless hosts.

    Importing this module does nothing; only this function creates a Tk root.
    With no display or without customtkinter it prints a note and returns 0
    instead of raising.
    """
    try:
        import tkinter as tk
    except Exception as exc:
        print(f"{APP_NAME}: a graphical environment with tkinter is required "
              f"to run the GUI ({exc}).")
        return 0

    if sys.platform != "win32" and not os.environ.get("DISPLAY") \
            and not os.environ.get("WAYLAND_DISPLAY"):
        print(f"{APP_NAME}: no graphical display available — the GUI is for the "
              f"desktop. (Use `python -m aiquickvpn --help` for the CLI.)")
        return 0

    try:
        App = build_app()
        app = App()
    except ImportError as exc:
        print(f"{APP_NAME}: the GUI needs the 'customtkinter' package "
              f"({exc}). Install it with:  pip install customtkinter")
        return 0
    except tk.TclError as exc:
        print(f"{APP_NAME}: no graphical display available — cannot start the "
              f"GUI here ({exc}).")
        return 0
    except Exception as exc:
        print(f"{APP_NAME}: could not start the GUI ({exc}).")
        return 1

    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
