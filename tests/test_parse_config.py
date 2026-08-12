"""Pure parsing of .ovpn text into structured ConfigInfo (no I/O, no network)."""

from aiquickvpn import openvpn as ovpn


def test_parse_full_profile(sample_ovpn):
    info = ovpn.parse_config(sample_ovpn)
    assert len(info.remotes) == 2
    assert info.remotes[0].host == "192.0.2.10"
    assert info.remotes[0].port == 1194
    assert info.remotes[0].proto == "udp"
    assert info.remotes[1].host == "vpn.example.net"
    assert info.remotes[1].port == 443
    assert info.remotes[1].proto == "tcp"
    assert info.dev == "tun"
    assert info.cipher == "AES-256-GCM"
    assert info.auth == "SHA256"
    assert info.auth_user_pass is True
    assert "ca" in info.inline_blocks and info.has_inline_ca
    assert info.warnings == []


def test_parse_cert_only_and_global_port(sample_ovpn_certonly):
    info = ovpn.parse_config(sample_ovpn_certonly)
    assert len(info.remotes) == 1
    assert info.remotes[0].host == "192.0.2.20"
    # global 'port 443' applies to the remote that used the default port
    assert info.remotes[0].port == 443
    assert info.proto == "tcp"
    assert info.auth_user_pass is False
    assert set(("cert", "key")).issubset(set(info.inline_blocks))


def test_parse_ignores_comments_and_blanks():
    text = "# a comment\n; another\n\nclient\nremote 192.0.2.5 1194\n"
    info = ovpn.parse_config(text)
    assert len(info.remotes) == 1
    assert info.remotes[0].host == "192.0.2.5"


def test_parse_empty_is_safe_and_warns():
    info = ovpn.parse_config("")
    assert info.remotes == []
    assert any("empty" in w for w in info.warnings)


def test_parse_no_remote_warns():
    info = ovpn.parse_config("client\ndev tun\n")
    assert info.remotes == []
    assert any("remote" in w for w in info.warnings)


def test_inline_block_body_is_not_retained():
    # Only the tag name is recorded; the body is never inspected or kept.
    text = "remote 192.0.2.9 1194\n<tls-auth>\nSOME-BODY-LINE\n</tls-auth>\n"
    info = ovpn.parse_config(text)
    assert info.inline_blocks == ["tls-auth"]
    assert "SOME-BODY-LINE" not in repr(info.as_dict())


def test_looks_like_ovpn():
    assert ovpn.looks_like_ovpn("remote 192.0.2.1 1194")
    assert ovpn.looks_like_ovpn("client\ndev tun")
    assert not ovpn.looks_like_ovpn("hello world, not a config")
    assert not ovpn.looks_like_ovpn("")
