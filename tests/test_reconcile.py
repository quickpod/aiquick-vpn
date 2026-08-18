r"""Reported state must match the process that actually exists.

State is inferred from openvpn's log output. A tunnel that ends without saying
so -- crashed, killed from outside, peer gone -- leaves the UI claiming
CONNECTED, telling the user their traffic is protected when it is not.
"""

from __future__ import annotations

from aiquickvpn import openvpn as ovpn


class FakeProc:
    """Stands in for the openvpn Popen object."""

    def __init__(self, alive=True):
        self._alive = alive

    def poll(self):
        return None if self._alive else 1

    def die(self):
        self._alive = False


def make(state, proc):
    conn = ovpn.VPNConnection.__new__(ovpn.VPNConnection)
    conn.state = state
    conn._proc = proc
    conn._on_state = None
    return conn


def test_a_dead_process_is_reported_as_disconnected():
    conn = make(ovpn.CONNECTED, FakeProc(alive=False))
    assert conn.reconcile() == ovpn.DISCONNECTED


def test_a_live_process_stays_connected():
    conn = make(ovpn.CONNECTED, FakeProc(alive=True))
    assert conn.reconcile() == ovpn.CONNECTED


def test_a_process_that_dies_flips_the_state():
    proc = FakeProc(alive=True)
    conn = make(ovpn.CONNECTED, proc)
    assert conn.reconcile() == ovpn.CONNECTED
    proc.die()
    assert conn.reconcile() == ovpn.DISCONNECTED


def test_no_process_at_all_is_disconnected():
    """The reported symptom: app says connected, nothing is running."""
    conn = make(ovpn.CONNECTED, None)
    assert conn.reconcile() == ovpn.DISCONNECTED


def test_the_handle_is_dropped_so_it_is_not_rechecked():
    conn = make(ovpn.CONNECTED, FakeProc(alive=False))
    conn.reconcile()
    assert conn._proc is None


def test_it_reports_through_the_state_callback():
    seen = []
    conn = make(ovpn.CONNECTED, FakeProc(alive=False))
    conn._on_state = seen.append
    conn.reconcile()
    assert seen == [ovpn.DISCONNECTED]


def test_an_already_disconnected_session_is_left_alone():
    conn = make(ovpn.DISCONNECTED, None)
    assert conn.reconcile() == ovpn.DISCONNECTED


def test_an_error_state_is_not_overwritten():
    """ERROR says why it stopped; DISCONNECTED would lose that."""
    conn = make(ovpn.ERROR, None)
    assert conn.reconcile() == ovpn.ERROR


def test_connecting_with_a_live_process_is_not_cut_short():
    conn = make(ovpn.CONNECTING, FakeProc(alive=True))
    assert conn.reconcile() == ovpn.CONNECTING
