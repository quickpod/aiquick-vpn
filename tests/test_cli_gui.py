"""CLI behaviour + headless GUI/tray guards (no server, no display, no network)."""

import sys

import pytest

from aiquickvpn import __main__ as cli
from aiquickvpn import gui
from aiquickvpn import openvpn as ovpn
from aiquickvpn import tray


def test_cli_status_runs(capsys):
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "Config dir:" in out
    assert "Not connected" in out          # never auto-connects


def test_cli_import_list_info_remove(sample_ovpn_file, capsys):
    assert cli.main(["import", sample_ovpn_file, "--name", "office"]) == 0
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "office" in out and "192.0.2.10" in out

    assert cli.main(["info", "office"]) == 0
    out = capsys.readouterr().out
    assert "192.0.2.10:1194/udp" in out
    assert "username/password required" in out

    assert cli.main(["remove", "office"]) == 0
    capsys.readouterr()
    assert cli.main(["list"]) == 0
    assert "No profiles" in capsys.readouterr().out


def test_cli_info_from_path(sample_ovpn_file, capsys):
    assert cli.main(["info", sample_ovpn_file]) == 0
    assert "192.0.2.10" in capsys.readouterr().out


def test_cli_import_rejects_garbage(tmp_path, capsys):
    bad = tmp_path / "bad.ovpn"
    bad.write_text("this is not a vpn config", encoding="utf-8")
    rc = cli.main(["import", str(bad)])
    assert rc == 1
    assert "error:" in capsys.readouterr().err


def test_cli_connect_without_openvpn_degrades(monkeypatch, sample_ovpn_file,
                                              capsys):
    cli.main(["import", sample_ovpn_file, "--name", "office"])
    capsys.readouterr()
    monkeypatch.setattr(ovpn, "openvpn_path", lambda: None)
    rc = cli.main(["connect", "office"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "error:" in err and "OpenVPN" in err


def test_cli_unknown_profile_exits_nonzero(capsys):
    assert cli.main(["remove", "nope"]) == 1
    assert "error:" in capsys.readouterr().err


# ---- tray (optional; always safe) ------------------------------------------
def test_tray_start_returns_none_when_disabled():
    # conftest sets AIQUICK_VPN_NO_TRAY=1, so no tray is created and no error.
    assert tray.start_tray() is None


# ---- headless GUI guards ----------------------------------------------------
@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows CI has a real display; main() would open a window and block")
def test_gui_imports_without_display():
    assert hasattr(gui, "main")


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows CI has a real display; main() would open a window and block")
def test_gui_main_headless_returns_zero(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert gui.main() == 0
