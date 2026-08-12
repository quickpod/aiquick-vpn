"""VPNConnection state machine, driven by a FAKE process — never a real VPN.

These tests prove the supervisor reaches CONNECTED/ERROR purely from log lines,
without ever launching openvpn or touching the network: ``_spawn`` (the single
subprocess seam) is monkeypatched to a canned FakeProc.
"""

import pytest

from aiquickvpn import openvpn as ovpn
from aiquickvpn.errors import AIQuickVPNError


@pytest.fixture
def available(monkeypatch):
    monkeypatch.setattr(ovpn, "openvpn_path", lambda: "/usr/sbin/openvpn")


def _import(sample):
    return ovpn.import_profile(sample, "vpn", is_text=True)


def test_connect_reaches_connected_then_disconnected(monkeypatch, available,
                                                     sample_ovpn, fake_proc):
    name = _import(sample_ovpn)
    lines = [
        "OpenVPN 2.6.0 x86_64-pc-linux-gnu",
        "Attempting to establish TCP connection with [AF_INET]192.0.2.10:1194",
        "Initialization Sequence Completed",
    ]
    monkeypatch.setattr(ovpn, "_spawn", lambda argv: fake_proc(lines))

    states = []
    conn = ovpn.VPNConnection(name, on_state=states.append, privileged=False)
    conn.start()
    conn._reader.join(timeout=3)

    assert ovpn.CONNECTING in states
    assert ovpn.CONNECTED in states
    # pipe ended -> supervisor reports disconnected as the final state
    assert states[-1] == ovpn.DISCONNECTED


def test_auth_failure_becomes_error_and_sticks(monkeypatch, available,
                                               sample_ovpn, fake_proc):
    name = _import(sample_ovpn)
    lines = [
        "Attempting to establish TCP connection with [AF_INET]192.0.2.10:1194",
        "AUTH_FAILED",
    ]
    monkeypatch.setattr(ovpn, "_spawn", lambda argv: fake_proc(lines))

    states = []
    conn = ovpn.VPNConnection(name, on_state=states.append, privileged=False)
    conn.start()
    conn._reader.join(timeout=3)

    assert conn.state == ovpn.ERROR          # error is not overwritten by exit
    assert conn.last_error == "AUTH_FAILED"


def test_spawn_receives_expected_argv(monkeypatch, available, sample_ovpn,
                                      fake_proc):
    name = _import(sample_ovpn)
    captured = {}

    def fake_spawn(argv):
        captured["argv"] = argv
        return fake_proc([])

    monkeypatch.setattr(ovpn, "_spawn", fake_spawn)
    conn = ovpn.VPNConnection(name, privileged=False)
    conn.start(auth_file="/tmp/creds.auth")
    conn._reader.join(timeout=3)

    argv = captured["argv"]
    assert argv[0] == "/usr/sbin/openvpn"
    assert "--config" in argv and ovpn.profile_path(name) in argv
    assert "--auth-user-pass" in argv and "/tmp/creds.auth" in argv


def test_start_without_openvpn_raises(monkeypatch, sample_ovpn):
    name = _import(sample_ovpn)
    monkeypatch.setattr(ovpn, "openvpn_path", lambda: None)
    conn = ovpn.VPNConnection(name)
    with pytest.raises(AIQuickVPNError):
        conn.start()


def test_start_missing_profile_raises(monkeypatch, available):
    conn = ovpn.VPNConnection("does-not-exist")
    with pytest.raises(AIQuickVPNError):
        conn.start()


def test_stop_terminates_process_and_is_safe(fake_proc):
    conn = ovpn.VPNConnection("x", privileged=False)
    proc = fake_proc([])
    conn._proc = proc
    conn.stop()
    assert proc._alive is False
    assert conn.state == ovpn.DISCONNECTED
    # stopping again (nothing running) is harmless
    conn.stop()
