"""Device actions: eligibility, notices, dual control, re-check at dispatch,
partial lock, and the one-hour unlock limit with compensation.

Timing follows the RBI draft amendment of May 2026. With the fixture's first
EMI due 10 Feb 2026:

    11 Apr  60 days past due   first notice, pay by 2 May
     3 May  first notice ran out   second notice, pay by 10 May
    11 May  90 days past due, second notice ran out   restriction allowed
"""
from __future__ import annotations

import datetime as _dt

import pytest

from emi_locker import devices, lifecycle, payments, settings_store
from emi_locker.core import Actor, create_user, rupees
from emi_locker.db import migrate, open_db, tx
from emi_locker.errors import PermissionDenied, ValidationError
from tests.helpers import build_world, make_finance

START = _dt.date(2026, 1, 10)
FIRST_DUE = _dt.date(2026, 2, 10)
FIRST_NOTICE_DAY = FIRST_DUE + _dt.timedelta(days=60)      # 11 Apr
SECOND_NOTICE_DAY = _dt.date(2026, 5, 3)                    # day after first pay_by
LOCK_DAY = FIRST_DUE + _dt.timedelta(days=90)               # 11 May
PAID_AT = _dt.datetime(2026, 5, 12, 10, 0, tzinfo=_dt.timezone.utc)


class AckProvider:
    name = "test-emm"

    def __init__(self):
        self.sent = []
        self.contexts = []

    def send(self, imei, command, context):
        self.sent.append((imei, command))
        self.contexts.append(context)
        return {"delivered": True, "provider_ref": "ref-%d" % len(self.sent), "detail": "ok"}


class DownProvider:
    name = "test-emm-down"

    def send(self, imei, command, context):
        return {"delivered": False, "provider_ref": None, "detail": "provider timeout"}


def sweep(world, as_of):
    with tx(world["conn"]):
        return lifecycle.run_daily_status_sweep(world["conn"], world["admin"], as_of=as_of)


def base_world():
    world = build_world()
    world["finance"] = make_finance(world, start=START, grace_days=5)
    with tx(world["conn"]):
        world["ops"] = Actor(
            create_user(world["conn"], "SUPER_ADMIN", "Ops", actor=world["admin"]), "SUPER_ADMIN")
    return world


def noticed_world():
    """Both notices issued and run out: restriction is allowed on LOCK_DAY."""
    world = base_world()
    sweep(world, FIRST_NOTICE_DAY)
    sweep(world, SECOND_NOTICE_DAY)
    sweep(world, LOCK_DAY)
    return world


def device_id(world):
    return world["finance"]["device_id"]


def device_status(world):
    return world["conn"].execute(
        "SELECT status FROM devices WHERE id = ?", (device_id(world),)).fetchone()["status"]


def restrict(world, provider, as_of=LOCK_DAY):
    conn = world["conn"]
    with tx(conn):
        cmd = devices.request_command(conn, world["ops"], device_id(world), "RESTRICT",
                                      reason="overdue, both notices expired", as_of=as_of)
        devices.approve_command(conn, world["admin"], cmd["command_id"])
        return devices.send_to_provider(conn, world["admin"], cmd["command_id"], provider,
                                        as_of=as_of)


def pay_arrears(world):
    conn = world["conn"]
    for emi in conn.execute(
        "SELECT id, amount_paise FROM emi_schedules WHERE finance_id = ?"
        " AND status = 'OVERDUE' ORDER BY seq", (world["finance"]["finance_id"],)
    ).fetchall():
        payments.record_cash_collection(conn, world["retailer"], world["finance"]["finance_id"],
                                        emi["amount_paise"], emi_id=emi["id"])


def refusal(world, as_of):
    with pytest.raises(PermissionDenied) as exc:
        with tx(world["conn"]):
            devices.request_command(world["conn"], world["ops"], device_id(world), "RESTRICT",
                                    reason="test", as_of=as_of)
    return str(exc.value)


# ------------------------------------------------------------- the timeline


def test_restriction_is_refused_while_nothing_is_overdue():
    world = base_world()
    assert "no instalment is past its grace period" in refusal(world, FIRST_DUE)


def test_restriction_is_refused_before_90_days_past_due():
    world = base_world()
    sweep(world, FIRST_DUE + _dt.timedelta(days=30))
    assert "only 30 days past due; restriction needs 90" in refusal(
        world, FIRST_DUE + _dt.timedelta(days=30))


def test_90_days_alone_is_not_enough_without_both_notices():
    """A device nobody sent notices for stays unrestricted, however late."""
    world = base_world()
    late = FIRST_DUE + _dt.timedelta(days=120)
    sweep(world, late)  # issues only the first notice, today
    assert "second notice has not been issued" in refusal(world, late)


def test_restriction_waits_out_the_second_notice_even_past_90_days():
    world = base_world()
    sweep(world, FIRST_NOTICE_DAY)
    # The second notice goes out late, at 88 days, so it runs until day 95.
    sweep(world, FIRST_DUE + _dt.timedelta(days=88))
    day_92 = FIRST_DUE + _dt.timedelta(days=92)
    sweep(world, day_92)
    assert "until 2026-05-16" in refusal(world, day_92)


def test_notices_follow_the_60_day_and_21_plus_7_day_schedule():
    world = base_world()
    assert sweep(world, FIRST_NOTICE_DAY - _dt.timedelta(days=1))["NOTICE_FIRST"] == []
    first = sweep(world, FIRST_NOTICE_DAY)["NOTICE_FIRST"]
    assert len(first) == 1
    # Not before the first notice's 21 days have run out.
    assert sweep(world, _dt.date(2026, 5, 2))["NOTICE_SECOND"] == []
    second = sweep(world, SECOND_NOTICE_DAY)["NOTICE_SECOND"]
    assert len(second) == 1

    rows = world["conn"].execute(
        "SELECT kind, days_past_due, issued_on, pay_by, delivered_at FROM restriction_notices"
        " ORDER BY kind").fetchall()
    assert [dict(r) for r in rows] == [
        {"kind": "FIRST", "days_past_due": 60, "issued_on": "2026-04-11",
         "pay_by": "2026-05-02", "delivered_at": None},
        {"kind": "SECOND", "days_past_due": 82, "issued_on": "2026-05-03",
         "pay_by": "2026-05-10", "delivered_at": None},
    ]
    # Idempotent: a re-run issues nothing new.
    again = sweep(world, SECOND_NOTICE_DAY)
    assert again["NOTICE_FIRST"] == [] and again["NOTICE_SECOND"] == []


def test_paying_the_oldest_instalment_restarts_the_notice_cycle():
    """Notices belong to one default. Clearing it means a new one needs its own."""
    world = noticed_world()
    conn = world["conn"]
    oldest = conn.execute(
        "SELECT id, amount_paise FROM emi_schedules WHERE finance_id = ? AND seq = 1",
        (world["finance"]["finance_id"],)).fetchone()
    with tx(conn):
        payments.record_cash_collection(conn, world["retailer"], world["finance"]["finance_id"],
                                        oldest["amount_paise"], emi_id=oldest["id"])
    # EMI 2 (due 10 Mar) is now the oldest: 62 days past due, no notices of its own.
    assert "only 62 days past due" in refusal(world, LOCK_DAY)


def test_restriction_needs_recorded_device_management_consent():
    world = noticed_world()
    world["conn"].execute("DELETE FROM customer_consents WHERE consent_type = 'DEVICE_MANAGEMENT'")
    assert "no recorded consent to device management" in refusal(world, LOCK_DAY)


# ------------------------------------------------------------ dual control


def test_restriction_requires_a_reason():
    world = noticed_world()
    with pytest.raises(ValidationError):
        with tx(world["conn"]):
            devices.request_command(world["conn"], world["ops"], device_id(world), "RESTRICT",
                                    reason="", as_of=LOCK_DAY)


def test_restriction_needs_a_second_approver():
    world = noticed_world()
    conn = world["conn"]
    with tx(conn):
        cmd = devices.request_command(conn, world["ops"], device_id(world), "RESTRICT",
                                      reason="overdue", as_of=LOCK_DAY)
    assert cmd["status"] == "PENDING_APPROVAL"
    with pytest.raises(PermissionDenied):
        with tx(conn):
            devices.approve_command(conn, world["ops"], cmd["command_id"])
    with tx(conn):
        out = devices.approve_command(conn, world["admin"], cmd["command_id"])
    assert out["status"] == "APPROVED"


def test_unapproved_command_cannot_be_dispatched():
    world = noticed_world()
    conn = world["conn"]
    with tx(conn):
        cmd = devices.request_command(conn, world["ops"], device_id(world), "RESTRICT",
                                      reason="overdue", as_of=LOCK_DAY)
    with pytest.raises(ValidationError):
        with tx(conn):
            devices.send_to_provider(conn, world["admin"], cmd["command_id"], AckProvider(),
                                     as_of=LOCK_DAY)


def test_payment_between_approval_and_dispatch_cancels_the_restriction():
    """The customer paying first must win the race, not the queued job."""
    world = noticed_world()
    conn = world["conn"]
    with tx(conn):
        cmd = devices.request_command(conn, world["ops"], device_id(world), "RESTRICT",
                                      reason="overdue", as_of=LOCK_DAY)
        devices.approve_command(conn, world["admin"], cmd["command_id"])
    with tx(conn):
        pay_arrears(world)
    sweep(world, LOCK_DAY)
    provider = AckProvider()
    with tx(conn):
        out = devices.send_to_provider(conn, world["admin"], cmd["command_id"], provider,
                                       as_of=LOCK_DAY)
    assert out["status"] == "REJECTED"
    assert provider.sent == []
    assert device_status(world) != "RESTRICTED"


# ------------------------------------------------------------ dispatch


def test_dispatch_marks_the_device_restricted_and_logs_the_provider_reply():
    world = noticed_world()
    provider = AckProvider()
    out = restrict(world, provider)
    assert out["status"] == "ACKED"
    assert provider.sent and provider.sent[0][1] == "RESTRICT"
    assert device_status(world) == "RESTRICTED"
    logs = world["conn"].execute(
        "SELECT event FROM device_command_logs WHERE command_id = ?",
        (out["command_id"],)).fetchall()
    assert [r["event"] for r in logs] == ["requested", "approved", "dispatch_acked"]


def test_restriction_is_always_a_partial_lock():
    """Calls in, internet, SOS and government alerts keep working; no data is read."""
    world = noticed_world()
    provider = AckProvider()
    restrict(world, provider)
    profile = provider.contexts[0]["profile"]
    assert profile["mode"] == "PARTIAL"
    for kept in ("incoming_calls", "internet", "emergency_sos", "government_alerts"):
        assert kept in profile["keep_working"]
    assert profile["read_device_data"] is False


def test_default_provider_never_claims_a_device_was_locked():
    world = noticed_world()
    out = restrict(world, devices.NullProvider())
    assert out["status"] == "FAILED"
    assert "no device-management provider configured" in out["detail"]
    assert device_status(world) != "RESTRICTED"


# ------------------------------------------------------------ unlocking


def test_restriction_is_lifted_once_the_arrears_clear():
    world = noticed_world()
    provider = AckProvider()
    restrict(world, provider)
    conn = world["conn"]
    with tx(conn):
        pay_arrears(world)
    sweep(world, LOCK_DAY)
    with tx(conn):
        # The payment path already tried (no provider configured) and failed;
        # this is the retry through a working provider.
        restored = devices.restore_on_payment(conn, world["admin"],
                                              world["finance"]["finance_id"], provider)
    assert restored["status"] == "ACKED"
    assert device_status(world) == "RESTORED"


def test_partial_payment_leaving_arrears_does_not_restore():
    world = noticed_world()
    provider = AckProvider()
    restrict(world, provider)
    conn = world["conn"]
    with tx(conn):
        payments.record_cash_collection(conn, world["retailer"],
                                        world["finance"]["finance_id"], rupees(2000))
        out = devices.restore_on_payment(conn, world["admin"],
                                         world["finance"]["finance_id"], provider)
    assert out is None
    assert device_status(world) == "RESTRICTED"


def _restricted_and_paid(world):
    """Restrict, then clear the arrears with the provider down, so the unlock is owed."""
    restrict(world, AckProvider())
    conn = world["conn"]
    with tx(conn):
        conn.execute("UPDATE devices SET status = 'RESTRICTED' WHERE id = ?", (device_id(world),))
        for emi in conn.execute(
            "SELECT id FROM emi_schedules WHERE finance_id = ? AND status = 'OVERDUE'",
            (world["finance"]["finance_id"],)
        ).fetchall():
            conn.execute("UPDATE emi_schedules SET status = 'PAID', paid_at = ? WHERE id = ?",
                         (PAID_AT.isoformat(), emi["id"]))
        first = devices.restore_on_payment(conn, world["admin"], world["finance"]["finance_id"],
                                           DownProvider(), at=PAID_AT)
    assert first["status"] == "FAILED"
    return world


def test_an_unlock_within_the_hour_owes_nothing():
    world = _restricted_and_paid(noticed_world())
    with tx(world["conn"]):
        devices.restore_on_payment(world["conn"], world["admin"],
                                   world["finance"]["finance_id"], AckProvider(),
                                   at=PAID_AT + _dt.timedelta(minutes=50))
    row = world["conn"].execute("SELECT * FROM unlock_obligations").fetchone()
    assert row["confirmed_at"] == (PAID_AT + _dt.timedelta(minutes=50)).isoformat()
    assert row["compensation_paise"] == 0


def test_a_late_unlock_owes_250_rupees_per_started_hour():
    world = _restricted_and_paid(noticed_world())
    # Deadline is 11:00; confirmed 13:05 is 2h05m late: three started hours.
    with tx(world["conn"]):
        devices.restore_on_payment(world["conn"], world["admin"],
                                   world["finance"]["finance_id"], AckProvider(),
                                   at=PAID_AT + _dt.timedelta(hours=3, minutes=5))
    rows = world["conn"].execute("SELECT * FROM unlock_obligations").fetchall()
    # The retry continued the same obligation; the clock did not restart.
    assert len(rows) == 1
    assert rows[0]["due_by"] == (PAID_AT + _dt.timedelta(hours=1)).isoformat()
    assert rows[0]["compensation_paise"] == rupees(750)
    assert world["conn"].execute(
        "SELECT COUNT(*) c FROM audit_logs WHERE action = 'device.unlock_late'"
    ).fetchone()["c"] == 1


def test_unlock_monitor_flags_waiting_unlocks_before_the_deadline():
    world = _restricted_and_paid(noticed_world())
    conn = world["conn"]
    assert devices.unlock_monitor(conn, at=PAID_AT + _dt.timedelta(minutes=20)) == []

    warned = devices.unlock_monitor(conn, at=PAID_AT + _dt.timedelta(minutes=35))
    assert len(warned) == 1
    assert warned[0]["overdue"] is False
    assert warned[0]["compensation_so_far_paise"] == 0

    late = devices.unlock_monitor(conn, at=PAID_AT + _dt.timedelta(minutes=90))
    assert late[0]["overdue"] is True
    assert late[0]["compensation_so_far_paise"] == rupees(250)


# ------------------------------------------------------------ settings floors


def test_admin_cannot_loosen_the_rbi_minimums():
    world = base_world()
    conn = world["conn"]
    for key, value in (("restriction.min_days_past_due", 30),
                       ("restriction.first_notice_days_past_due", 15),
                       ("restriction.first_notice_window_days", 7),
                       ("restriction.second_notice_window_days", 2),
                       ("restriction.late_unlock_compensation_paise_per_hour", 0),
                       ("restriction.unlock_limit_minutes", 240)):
        with pytest.raises(ValidationError):
            with tx(conn):
                settings_store.set_setting(conn, world["admin"], key, value)


def test_admin_can_be_stricter_than_the_minimums():
    world = base_world()
    conn = world["conn"]
    with tx(conn):
        settings_store.set_setting(conn, world["admin"], "restriction.min_days_past_due", 120)
        settings_store.set_setting(conn, world["admin"], "restriction.unlock_limit_minutes", 30)
    sweep(world, FIRST_NOTICE_DAY)
    sweep(world, SECOND_NOTICE_DAY)
    sweep(world, LOCK_DAY)
    assert "only 90 days past due; restriction needs 120" in refusal(world, LOCK_DAY)


# ------------------------------------------------------------ migration


def test_an_existing_database_gains_the_new_tables_on_open():
    conn = open_db()
    conn.execute("DROP TABLE restriction_notices")
    conn.execute("DROP TABLE unlock_obligations")
    migrate(conn)
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"restriction_notices", "unlock_obligations"} <= names
