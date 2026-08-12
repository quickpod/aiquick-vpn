"""OpenVPN availability detection + graceful degradation (no binary needed)."""

from aiquickvpn import openvpn as ovpn


def test_available_true_when_path_found(monkeypatch):
    monkeypatch.setattr(ovpn, "openvpn_path", lambda: "/usr/sbin/openvpn")
    assert ovpn.openvpn_available() is True


def test_available_false_when_missing(monkeypatch):
    monkeypatch.setattr(ovpn, "openvpn_path", lambda: None)
    assert ovpn.openvpn_available() is False


def test_unavailable_message_is_actionable():
    msg = ovpn.unavailable_message()
    assert "OpenVPN" in msg and "install" in msg.lower()


def test_which_is_consulted(monkeypatch):
    # openvpn_path must consult shutil.which first.
    monkeypatch.setattr(ovpn.shutil, "which",
                        lambda name: "/opt/openvpn" if name == "openvpn" else None)
    assert ovpn.openvpn_path() == "/opt/openvpn"


def test_privilege_prefix_root(monkeypatch):
    # As root, no prefix is needed.
    monkeypatch.setattr(ovpn.os, "name", "posix")
    monkeypatch.setattr(ovpn.os, "geteuid", lambda: 0, raising=False)
    assert ovpn._privilege_prefix() == []
