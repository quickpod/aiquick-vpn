"""Shared pytest fixtures for the aiquickvpn tests.

Everything here is deterministic and OFFLINE: the config/profiles directory is
redirected into a tmp tree via ``AIQUICK_VPN_CONFIG_DIR`` so nothing touches the
real user config, and no test ever launches ``openvpn`` or opens a socket.
Sample ``.ovpn`` text uses TEST-NET-1 (192.0.2.0/24, RFC 5737) addresses and a
placeholder inline block (no real key material), so the secret scanner stays
clean.
"""

from __future__ import annotations

import pytest


# A realistic client profile: two remotes (IP + hostname), a global proto, a
# cipher, username/password auth, and an inline <ca> block recorded by name only.
SAMPLE_OVPN = """\
client
dev tun
proto udp
remote 192.0.2.10 1194 udp
remote vpn.example.net 443 tcp
cipher AES-256-GCM
auth SHA256
auth-user-pass
<ca>
INLINE-CA-PLACEHOLDER-NOT-A-REAL-KEY
</ca>
"""

# A cert-only profile (no auth-user-pass, single remote, global port).
SAMPLE_OVPN_CERTONLY = """\
client
dev tun
proto tcp
remote 192.0.2.20
port 443
<cert>
INLINE-CERT-PLACEHOLDER
</cert>
<key>
INLINE-KEY-PLACEHOLDER
</key>
"""


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    """Redirect all config + profile storage into a per-test tmp dir."""
    monkeypatch.setenv("AIQUICK_VPN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("AIQUICK_VPN_NO_TRAY", "1")
    yield


@pytest.fixture
def sample_ovpn():
    return SAMPLE_OVPN


@pytest.fixture
def sample_ovpn_certonly():
    return SAMPLE_OVPN_CERTONLY


@pytest.fixture
def sample_ovpn_file(tmp_path):
    p = tmp_path / "office.ovpn"
    p.write_text(SAMPLE_OVPN, encoding="utf-8")
    return str(p)


class FakeProc:
    """A stand-in for a Popen ``openvpn`` process driven by canned log lines.

    Iterating ``stdout`` yields the given lines and then stops (as a real
    process's pipe does when it exits), which drives :class:`VPNConnection`'s
    state machine end-to-end without launching anything or touching the network.
    """

    def __init__(self, lines):
        self.stdout = iter(lines)
        self.returncode = 0
        self.pid = 4242
        self._alive = True

    def poll(self):
        return None if self._alive else self.returncode

    def wait(self, timeout=None):
        self._alive = False
        return self.returncode

    def terminate(self):
        self._alive = False

    def kill(self):
        self._alive = False


@pytest.fixture
def fake_proc():
    return FakeProc
