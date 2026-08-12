"""Pure argv builder + log-line state classification."""

import pytest

from aiquickvpn import openvpn as ovpn
from aiquickvpn.errors import AIQuickVPNError


def test_build_connect_args_minimal():
    args = ovpn.build_connect_args("/cfg/office.ovpn")
    assert args[:3] == ["--config", "/cfg/office.ovpn", "--nobind"]
    assert args[-2:] == ["--verb", "3"]
    assert "--auth-user-pass" not in args


def test_build_connect_args_full():
    args = ovpn.build_connect_args(
        "/cfg/office.ovpn", auth_file="/tmp/a.auth",
        writepid="/run/x.pid", log_file="/tmp/x.log", mgmt_port=7505)
    # config must come first so later flags override the profile's directives
    assert args.index("--config") == 0
    assert "--auth-user-pass" in args and "/tmp/a.auth" in args
    assert "--writepid" in args and "/run/x.pid" in args
    assert "--management" in args and "127.0.0.1" in args and "7505" in args


def test_build_connect_args_requires_file():
    with pytest.raises(AIQuickVPNError):
        ovpn.build_connect_args("")


@pytest.mark.parametrize("line,expected", [
    ("Wed ... Initialization Sequence Completed", ovpn.CONNECTED),
    ("AUTH_FAILED", ovpn.ERROR),
    ("SIGUSR1[soft,connection-reset] received, process restarting", ovpn.RECONNECTING),
    ("Attempting to establish TCP connection with [AF_INET]192.0.2.10:1194",
     ovpn.CONNECTING),
    ("TLS Error: TLS key negotiation failed to occur within 60 seconds",
     ovpn.ERROR),
    ("SIGTERM[hard,] received, process exiting", ovpn.DISCONNECTED),
])
def test_parse_state_event(line, expected):
    assert ovpn.parse_state_event(line) == expected


def test_parse_state_event_unrelated_is_none():
    assert ovpn.parse_state_event("OpenVPN 2.6.0 x86_64-pc-linux-gnu") is None
    assert ovpn.parse_state_event("") is None
