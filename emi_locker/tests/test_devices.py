"""Device actions: eligibility, dual control, re-check at dispatch, audit."""
from __future__ import annotations

import datetime as _dt

import pytest

from emi_locker import devices, lifecycle, payments
from emi_locker.core import Actor, create_user, rupees
from emi_locker.db import tx
from emi_locker.errors import PermissionDenied, ValidationError
from tests.helpers import build_world, make_finance

START = _dt.date(2026, 1, 10)
LATE = _dt.date(2026, 3, 1)


class AckProvider:
    name = "test-emm"

    def __init__(self):
        self.sent = []

    def send(self, imei, command, context):
        self.sent.append((imei, command))
        return {"delivered": True, "provider_ref": "ref-%d" % len(self.sent), "detail": "ok"}


def overdue_world():
    world = build_world()
    result = make_finance(world, start=START, grace_days=5)
    with tx(world["conn"]):
        lifecycle.run_daily_status_sweep(world["conn"], world["admin"], as_of=LATE)
    world["finance"] = result
    with tx(world["conn"]):
        world["ops"] = Actor(
            create_user(world["conn"], "SUPER_ADMIN", "Ops", actor=world["admin"]), "SUPER_ADMIN")
    return world


def test_restriction_is_refused_while_nothing_is_overdue():
    world = build_world()
    result = make_finance(world, start=START)
    with pytest.raises(PermissionDenied) as exc:
        with tx(world["conn"]):
            devices.request_command(world["conn"], world["admin"], result["device_id"],
                                    "RESTRICT", reason="test")
    assert "not eligible" in str(exc.value)


def test_restriction_requires_a_reason():
    world = overdue_world()
    with pytest.raises(ValidationError):
        with tx(world["conn"]):
            devices.request_command(world["conn"], world["ops"],
                                    world["finance"]["device_id"], "RESTRICT", reason="")


def test_restriction_needs_a_second_approver():
    world = overdue_world()
    conn = world["conn"]
    with tx(conn):
        cmd = devices.request_command(conn, world["ops"], world["finance"]["device_id"],
                                      "RESTRICT", reason="overdue beyond grace")
    assert cmd["status"] == "PENDING_APPROVAL"
    with pytest.raises(PermissionDenied):
        with tx(conn):
            devices.approve_command(conn, world["ops"], cmd["command_id"])
    with tx(conn):
        out = devices.approve_command(conn, world["admin"], cmd["command_id"])
    assert out["status"] == "APPROVED"


def test_unapproved_command_cannot_be_dispatched():
    world = overdue_world()
    conn = world["conn"]
    with tx(conn):
        cmd = devices.request_command(conn, world["ops"], world["finance"]["device_id"],
                                      "RESTRICT", reason="overdue")
    with pytest.raises(ValidationError):
        with tx(conn):
            devices.send_to_provider(conn, world["admin"], cmd["command_id"], AckProvider())


def test_payment_between_approval_and_dispatch_cancels_the_restriction():
    """The customer paying first must win the race, not the queued job."""
    world = overdue_world()
    conn = world["conn"]
    with tx(conn):
        cmd = devices.request_command(conn, world["ops"], world["finance"]["device_id"],
                                      "RESTRICT", reason="overdue")
        devices.approve_command(conn, world["admin"], cmd["command_id"])
    with tx(conn):
        payments.record_cash_collection(conn, world["retailer"],
                                        world["finance"]["finance_id"], rupees(2000))
        lifecycle.run_daily_status_sweep(conn, world["admin"], as_of=LATE)
    provider = AckProvider()
    with tx(conn):
        out = devices.send_to_provider(conn, world["admin"], cmd["command_id"], provider)
    assert out["status"] == "REJECTED"
    assert provider.sent == []
    assert conn.execute("SELECT status FROM devices WHERE id = ?",
                        (world["finance"]["device_id"],)).fetchone()["status"] != "RESTRICTED"


def test_dispatch_marks_the_device_restricted_and_logs_the_provider_reply():
    world = overdue_world()
    conn = world["conn"]
    provider = AckProvider()
    with tx(conn):
        cmd = devices.request_command(conn, world["ops"], world["finance"]["device_id"],
                                      "RESTRICT", reason="overdue")
        devices.approve_command(conn, world["admin"], cmd["command_id"])
        out = devices.send_to_provider(conn, world["admin"], cmd["command_id"], provider)
    assert out["status"] == "ACKED"
    assert provider.sent and provider.sent[0][1] == "RESTRICT"
    assert conn.execute("SELECT status FROM devices WHERE id = ?",
                        (world["finance"]["device_id"],)).fetchone()["status"] == "RESTRICTED"
    logs = conn.execute("SELECT event FROM device_command_logs WHERE command_id = ?",
                        (cmd["command_id"],)).fetchall()
    assert [r["event"] for r in logs] == ["requested", "approved", "dispatch_acked"]


def test_default_provider_never_claims_a_device_was_locked():
    world = overdue_world()
    conn = world["conn"]
    with tx(conn):
        cmd = devices.request_command(conn, world["ops"], world["finance"]["device_id"],
                                      "RESTRICT", reason="overdue")
        devices.approve_command(conn, world["admin"], cmd["command_id"])
        out = devices.send_to_provider(conn, world["admin"], cmd["command_id"])
    assert out["status"] == "FAILED"
    assert "no device-management provider configured" in out["detail"]
    assert conn.execute("SELECT status FROM devices WHERE id = ?",
                        (world["finance"]["device_id"],)).fetchone()["status"] != "RESTRICTED"


def test_restriction_is_lifted_once_the_arrears_clear():
    world = overdue_world()
    conn = world["conn"]
    provider = AckProvider()
    with tx(conn):
        cmd = devices.request_command(conn, world["ops"], world["finance"]["device_id"],
                                      "RESTRICT", reason="overdue")
        devices.approve_command(conn, world["admin"], cmd["command_id"])
        devices.send_to_provider(conn, world["admin"], cmd["command_id"], provider)
    with tx(conn):
        payments.record_cash_collection(conn, world["retailer"],
                                        world["finance"]["finance_id"], rupees(2000))
        lifecycle.run_daily_status_sweep(conn, world["admin"], as_of=LATE)
        restored = devices.restore_on_payment(conn, world["admin"],
                                              world["finance"]["finance_id"], provider)
    assert restored["status"] == "ACKED"
    assert conn.execute("SELECT status FROM devices WHERE id = ?",
                        (world["finance"]["device_id"],)).fetchone()["status"] == "RESTORED"


def test_partial_payment_leaving_arrears_does_not_restore():
    world = overdue_world()
    conn = world["conn"]
    provider = AckProvider()
    # Two instalments are overdue by this date.
    with tx(conn):
        lifecycle.run_daily_status_sweep(conn, world["admin"], as_of=_dt.date(2026, 4, 1))
        cmd = devices.request_command(conn, world["ops"], world["finance"]["device_id"],
                                      "RESTRICT", reason="two overdue")
        devices.approve_command(conn, world["admin"], cmd["command_id"])
        devices.send_to_provider(conn, world["admin"], cmd["command_id"], provider)
    with tx(conn):
        payments.record_cash_collection(conn, world["retailer"],
                                        world["finance"]["finance_id"], rupees(2000))
        out = devices.restore_on_payment(conn, world["admin"],
                                         world["finance"]["finance_id"], provider)
    assert out is None
    assert conn.execute("SELECT status FROM devices WHERE id = ?",
                        (world["finance"]["device_id"],)).fetchone()["status"] == "RESTRICTED"
