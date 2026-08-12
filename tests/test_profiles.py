"""Profile store CRUD + OS-aware config-dir behaviour (all in a tmp tree)."""

import os

import pytest

from aiquickvpn import config as appconfig
from aiquickvpn import openvpn as ovpn
from aiquickvpn.errors import AIQuickVPNError


def test_config_dir_uses_override(tmp_path, monkeypatch):
    target = str(tmp_path / "myconf")
    monkeypatch.setenv("AIQUICK_VPN_CONFIG_DIR", target)
    assert appconfig.config_dir() == target
    assert appconfig.profiles_dir() == os.path.join(target, "profiles")


def test_import_from_file_then_read_and_info(sample_ovpn_file):
    name = ovpn.import_profile(sample_ovpn_file)
    assert name == "office"
    assert ovpn.list_profiles() == ["office"]
    # stored under the profiles dir
    assert os.path.isfile(ovpn.profile_path("office"))
    assert ovpn.profile_path("office").startswith(appconfig.profiles_dir())
    info = ovpn.profile_info("office")
    assert info.remotes[0].host == "192.0.2.10"


def test_import_from_text_with_name(sample_ovpn):
    name = ovpn.import_profile(sample_ovpn, "Work VPN", is_text=True)
    assert name == "Work-VPN"                    # sanitized
    assert "Work-VPN" in ovpn.list_profiles()


def test_import_rejects_non_ovpn():
    with pytest.raises(AIQuickVPNError):
        ovpn.import_profile("just some text", "x", is_text=True)


def test_import_missing_file():
    with pytest.raises(AIQuickVPNError):
        ovpn.import_profile("/no/such/file.ovpn")


def test_import_duplicate_needs_overwrite(sample_ovpn):
    ovpn.import_profile(sample_ovpn, "dup", is_text=True)
    with pytest.raises(AIQuickVPNError):
        ovpn.import_profile(sample_ovpn, "dup", is_text=True)
    # overwrite=True succeeds
    assert ovpn.import_profile(sample_ovpn, "dup", is_text=True,
                               overwrite=True) == "dup"


def test_remove_profile(sample_ovpn):
    ovpn.import_profile(sample_ovpn, "gone", is_text=True)
    assert ovpn.remove_profile("gone") is True
    assert "gone" not in ovpn.list_profiles()
    with pytest.raises(AIQuickVPNError):
        ovpn.remove_profile("gone")


def test_sanitize_name_strips_path_and_suffix():
    assert ovpn.sanitize_name("../../etc/passwd") == "passwd"
    assert ovpn.sanitize_name("office.ovpn") == "office"
    with pytest.raises(AIQuickVPNError):
        ovpn.sanitize_name("   ")


def test_read_missing_profile_raises():
    with pytest.raises(AIQuickVPNError):
        ovpn.read_profile("nope")


def test_listing_empty_when_no_dir():
    # Fresh isolated config: no profiles dir yet -> empty list, no error.
    assert ovpn.list_profiles() == []
