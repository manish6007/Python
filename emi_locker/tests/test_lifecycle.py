"""Due -> grace -> overdue transitions, reminders and closure."""
from __future__ import annotations

import datetime as _dt

from emi_locker import finance, lifecycle, payments
from emi_locker.core import rupees
from emi_locker.db import tx
from tests.helpers import build_world, make_finance

START = _dt.date(2026, 1, 10)
FIRST_DUE = _dt.date(2026, 2, 10)


def sweep(world, as_of):
    with tx(world["conn"]):
        return lifecycle.run_daily_status_sweep(world["conn"], world["admin"], as_of=as_of)


def first_status(world, finance_id):
    return finance.get_schedule(world["conn"], finance_id)[0]["status"]


def test_instalment_walks_upcoming_due_grace_overdue():
    world = build_world()
    result = make_finance(world, start=START, grace_days=5)
    fid = result["finance_id"]

    sweep(world, FIRST_DUE - _dt.timedelta(days=1))
    assert first_status(world, fid) == "UPCOMING"

    sweep(world, FIRST_DUE)
    assert first_status(world, fid) == "DUE"

    sweep(world, FIRST_DUE + _dt.timedelta(days=3))
    assert first_status(world, fid) == "GRACE_PERIOD"

    sweep(world, FIRST_DUE + _dt.timedelta(days=6))
    assert first_status(world, fid) == "OVERDUE"


def test_grace_boundary_is_inclusive_of_the_last_grace_day():
    world = build_world()
    result = make_finance(world, start=START, grace_days=5)
    sweep(world, FIRST_DUE + _dt.timedelta(days=5))
    assert first_status(world, result["finance_id"]) == "GRACE_PERIOD"


def test_sweep_is_idempotent():
    world = build_world()
    make_finance(world, start=START, grace_days=5)
    as_of = FIRST_DUE + _dt.timedelta(days=10)
    first = sweep(world, as_of)
    second = sweep(world, as_of)
    assert first["OVERDUE"]
    assert second == {"DUE": [], "GRACE_PERIOD": [], "OVERDUE": []}


def test_account_and_device_follow_the_worst_instalment():
    world = build_world()
    result = make_finance(world, start=START, grace_days=5)
    conn = world["conn"]
    sweep(world, FIRST_DUE + _dt.timedelta(days=10))
    assert conn.execute("SELECT status FROM finance_accounts WHERE id = ?",
                        (result["finance_id"],)).fetchone()["status"] == "OVERDUE"
    assert conn.execute("SELECT status FROM devices WHERE id = ?",
                        (result["device_id"],)).fetchone()["status"] == "OVERDUE"


def test_clearing_arrears_returns_the_account_to_active():
    world = build_world()
    result = make_finance(world, start=START, grace_days=5)
    conn = world["conn"]
    sweep(world, FIRST_DUE + _dt.timedelta(days=10))
    with tx(conn):
        payments.record_cash_collection(conn, world["retailer"], result["finance_id"],
                                        rupees(2000))
    sweep(world, FIRST_DUE + _dt.timedelta(days=10))
    assert conn.execute("SELECT status FROM finance_accounts WHERE id = ?",
                        (result["finance_id"],)).fetchone()["status"] == "ACTIVE"


def test_reminders_fire_at_seven_three_one_and_zero_days():
    world = build_world()
    make_finance(world, start=START)
    conn = world["conn"]
    kinds = {}
    for offset, expected in [(7, "T-7"), (3, "T-3"), (1, "T-1"), (0, "DUE_TODAY")]:
        as_of = FIRST_DUE - _dt.timedelta(days=offset)
        rows = lifecycle.due_reminders(conn, as_of=as_of)
        kinds[expected] = [r for r in rows if r["kind"] == expected]
    for expected, rows in kinds.items():
        assert len(rows) == 1, expected
        assert rows[0]["mobile"] == "9876543210"


def test_no_reminder_on_an_unrelated_day():
    world = build_world()
    make_finance(world, start=START)
    as_of = FIRST_DUE - _dt.timedelta(days=5)
    assert lifecycle.due_reminders(world["conn"], as_of=as_of) == []


def test_overdue_report_counts_days_past_due():
    world = build_world()
    result = make_finance(world, start=START, grace_days=5)
    as_of = FIRST_DUE + _dt.timedelta(days=20)
    sweep(world, as_of)
    rows = lifecycle.overdue_report(world["conn"], as_of=as_of)
    assert len(rows) == 1
    assert rows[0]["finance_id"] == result["finance_id"]
    assert rows[0]["days_past_due"] == 20
    assert rows[0]["overdue_amount"] == rupees(2000)


def test_closure_certificate_reports_no_dues_only_when_settled():
    world = build_world()
    result = make_finance(world, start=START)
    conn = world["conn"]
    assert lifecycle.closure_certificate(conn, result["finance_id"])["no_dues"] is False
    with tx(conn):
        for _ in range(11):
            payments.record_cash_collection(conn, world["retailer"], result["finance_id"],
                                            rupees(2000))
    cert = lifecycle.closure_certificate(conn, result["finance_id"])
    assert cert["no_dues"] is True
    assert cert["total_collected"] == rupees(22000)
    assert cert["financed_amount"] == rupees(22000)


def test_completed_finance_stops_generating_reminders():
    world = build_world()
    result = make_finance(world, start=START)
    conn = world["conn"]
    with tx(conn):
        for _ in range(11):
            payments.record_cash_collection(conn, world["retailer"], result["finance_id"],
                                            rupees(2000))
    moved = sweep(world, _dt.date(2026, 6, 10))
    assert moved == {"DUE": [], "GRACE_PERIOD": [], "OVERDUE": []}
    assert lifecycle.due_reminders(conn, as_of=_dt.date(2026, 6, 10)) == []
