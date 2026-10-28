"""Restriction notices only count once the customer has them.

Same fixture dates as test_devices: first EMI due 10 Feb 2026, first notice
due 11 Apr (60 days past due).
"""
from __future__ import annotations

import datetime as _dt

from emi_locker import devices, lifecycle, notices, payments
from emi_locker.db import tx
from tests.test_devices import (
    FIRST_DUE,
    FIRST_NOTICE_DAY,
    InboxChannel,
    base_world,
    device_id,
    refusal,
    sweep,
)


class BrokenChannel:
    def send_notice(self, mobile, text, variables):
        raise RuntimeError("provider timeout")


def deliver(world, channel, as_of):
    with tx(world["conn"]):
        return notices.deliver_pending_notices(world["conn"], channel, as_of=as_of,
                                               business="Ashish Enterprises")


def notice_rows(world):
    return [dict(r) for r in world["conn"].execute(
        "SELECT kind, issued_on, delivered_at, pay_by, delivery_channel, delivery_error"
        " FROM restriction_notices ORDER BY created_at")]


def test_the_notice_text_says_what_is_owed_by_when_and_what_keeps_working():
    world = base_world()
    sweep(world, FIRST_NOTICE_DAY, deliver=False)
    inbox = InboxChannel()
    deliver(world, inbox, FIRST_NOTICE_DAY)
    mobile, text = inbox.sent[0]
    assert mobile
    assert "Ashish Enterprises" in text
    assert "Rs.4,000.00" in text            # EMIs 1 and 2 are overdue
    assert "60 days overdue" in text
    assert "02 May 2026" in text
    assert "Calls, internet and SOS will keep working" in text


def test_a_late_delivery_gives_the_customer_the_full_window_from_delivery():
    world = base_world()
    sweep(world, FIRST_NOTICE_DAY, deliver=False)
    # The SMS provider was down for five days.
    deliver(world, InboxChannel(), FIRST_NOTICE_DAY + _dt.timedelta(days=5))
    assert notice_rows(world)[0]["pay_by"] == "2026-05-07"   # 16 Apr + 21 days


def test_a_failed_delivery_is_recorded_and_retried():
    world = base_world()
    sweep(world, FIRST_NOTICE_DAY, deliver=False)
    out = deliver(world, BrokenChannel(), FIRST_NOTICE_DAY)
    assert len(out["failed"]) == 1
    row = notice_rows(world)[0]
    assert row["delivered_at"] is None
    assert "provider timeout" in row["delivery_error"]

    out = deliver(world, InboxChannel(), FIRST_NOTICE_DAY + _dt.timedelta(days=1))
    assert len(out["delivered"]) == 1
    row = notice_rows(world)[0]
    assert row["delivered_at"] == "2026-04-12"
    assert row["delivery_error"] is None


def test_the_second_notice_waits_for_the_first_to_be_delivered():
    world = base_world()
    sweep(world, FIRST_NOTICE_DAY, deliver=False)
    # Weeks later the first notice has still not reached the customer.
    moved = sweep(world, _dt.date(2026, 5, 20), deliver=False)
    assert moved["NOTICE_SECOND"] == []


def test_an_undelivered_second_notice_blocks_a_restriction():
    world = base_world()
    sweep(world, FIRST_NOTICE_DAY)
    sweep(world, _dt.date(2026, 5, 3), deliver=False)    # second issued, not sent
    late = FIRST_DUE + _dt.timedelta(days=120)
    sweep(world, late, deliver=False)
    assert "second notice has not reached the customer" in refusal(world, late)


def test_a_notice_for_an_instalment_paid_before_delivery_is_not_sent():
    world = base_world()
    sweep(world, FIRST_NOTICE_DAY, deliver=False)
    conn = world["conn"]
    with tx(conn):
        for emi in conn.execute(
            "SELECT id, amount_paise FROM emi_schedules WHERE finance_id = ?"
            " AND status = 'OVERDUE' ORDER BY seq", (world["finance"]["finance_id"],)
        ).fetchall():
            payments.record_cash_collection(conn, world["retailer"],
                                            world["finance"]["finance_id"],
                                            emi["amount_paise"], emi_id=emi["id"])
    inbox = InboxChannel()
    out = deliver(world, inbox, FIRST_NOTICE_DAY)
    assert inbox.sent == []
    assert len(out["skipped"]) == 1
    # Skipped notices are not picked up again.
    assert deliver(world, inbox, FIRST_NOTICE_DAY)["skipped"] == []


def test_the_customer_sees_the_latest_delivered_notice_until_the_arrears_clear():
    world = base_world()
    conn = world["conn"]
    finance_id = world["finance"]["finance_id"]
    assert notices.active_notice(conn, finance_id) is None

    sweep(world, FIRST_NOTICE_DAY)
    first = notices.active_notice(conn, finance_id)
    assert first["kind"] == "FIRST" and first["pay_by"] == "2026-05-02"

    sweep(world, _dt.date(2026, 5, 3))
    assert notices.active_notice(conn, finance_id)["kind"] == "SECOND"

    with tx(conn):
        for emi in conn.execute(
            "SELECT id, amount_paise FROM emi_schedules WHERE finance_id = ?"
            " AND status = 'OVERDUE' ORDER BY seq", (finance_id,)
        ).fetchall():
            payments.record_cash_collection(conn, world["retailer"], finance_id,
                                            emi["amount_paise"], emi_id=emi["id"])
    assert notices.active_notice(conn, finance_id) is None
    assert devices.eligibility_for_restriction(
        conn, device_id(world), _dt.date(2026, 5, 20))["eligible"] is False
