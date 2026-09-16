"""Schedule arithmetic, IMEI rules, consent gating and transactional integrity."""
from __future__ import annotations

import datetime as _dt

import pytest

from emi_locker import finance, licensing
from emi_locker.core import rupees
from emi_locker.db import tx
from emi_locker.errors import (
    DuplicateDevice,
    PermissionDenied,
    ValidationError,
)
from tests.helpers import OTHER_IMEI, VALID_IMEI, build_world, make_customer, make_finance


def test_worked_example_from_the_blueprint():
    """Rs.30,000 - Rs.8,000 down = Rs.22,000 over 11 months = Rs.2,000 a month."""
    world = build_world()
    result = make_finance(world)
    assert result["principal"] == rupees(22000)
    assert result["emi_amount"] == rupees(2000)
    assert len(result["schedule"]) == 11
    assert all(r["amount_paise"] == rupees(2000) for r in result["schedule"])


@pytest.mark.parametrize("principal,tenure", [
    (rupees(22000), 11),
    (rupees(9999), 7),
    (rupees(12345), 9),
    (rupees(100), 3),
    (rupees(31337), 13),
])
def test_schedule_always_sums_to_the_financed_amount(principal, tenure):
    rows = finance.build_schedule(principal, tenure, _dt.date(2026, 1, 15))
    assert len(rows) == tenure
    assert sum(r["amount_paise"] for r in rows) == principal
    assert all(r["amount_paise"] > 0 for r in rows)


def test_odd_amounts_put_the_remainder_on_the_last_instalment():
    rows = finance.build_schedule(rupees(10000), 3, _dt.date(2026, 1, 10))
    assert [r["amount_paise"] for r in rows] == [rupees(3333), rupees(3333), rupees(3334)]


def test_month_end_due_dates_do_not_skip_february():
    rows = finance.build_schedule(rupees(3000), 3, _dt.date(2026, 1, 31))
    assert [r["due_date"].isoformat() for r in rows] == [
        "2026-02-28", "2026-03-31", "2026-04-30"
    ]


@pytest.mark.parametrize("imei,ok", [
    ("490154203237518", True),
    ("356938035643809", True),
    ("490154203237519", False),   # bad check digit
    ("49015420323751", False),    # too short
    ("49015420323751A", False),   # not numeric
])
def test_imei_luhn_validation(imei, ok):
    assert finance.valid_imei(imei) is ok


def test_duplicate_live_imei_is_blocked():
    world = build_world()
    make_finance(world)
    second = make_customer(world, name="Second", mobile="9000000001")
    with pytest.raises(DuplicateDevice):
        make_finance(world, customer_id=second, imei=VALID_IMEI)


def test_imei_is_reusable_once_the_earlier_finance_completes():
    world = build_world()
    first = make_finance(world)
    conn = world["conn"]
    conn.execute("UPDATE devices SET status = 'COMPLETED' WHERE id = ?", (first["device_id"],))
    second = make_customer(world, name="Second", mobile="9000000002")
    again = make_finance(world, customer_id=second, imei=VALID_IMEI)
    assert again["finance_id"] != first["finance_id"]


def test_failed_activation_leaves_no_device_row_and_no_lost_quota():
    """The whole registration is one transaction: it lands or it does not."""
    world = build_world(quota=1)
    conn = world["conn"]
    make_finance(world)
    assert licensing.wallet(conn, world["retailer_id"])["available"] == 0

    second = make_customer(world, name="Second", mobile="9000000003")
    before_devices = conn.execute("SELECT COUNT(*) c FROM devices").fetchone()["c"]
    with pytest.raises(Exception):
        make_finance(world, customer_id=second, imei=OTHER_IMEI)
    assert conn.execute("SELECT COUNT(*) c FROM devices").fetchone()["c"] == before_devices
    assert conn.execute(
        "SELECT COUNT(*) c FROM finance_accounts").fetchone()["c"] == 1
    assert licensing.wallet(conn, world["retailer_id"])["used"] == 1


def test_finance_cannot_activate_without_consent():
    world = build_world()
    cid = make_customer(world, consents=False)
    with pytest.raises(PermissionDenied) as exc:
        make_finance(world, customer_id=cid)
    assert "consent" in str(exc.value).lower()


def test_down_payment_must_be_below_price():
    world = build_world()
    cid = make_customer(world)
    with pytest.raises(ValidationError):
        make_finance(world, customer_id=cid, price=20000, down=20000)


def test_retry_of_the_same_request_creates_one_finance():
    world = build_world()
    conn, retailer = world["conn"], world["retailer"]
    cid = make_customer(world)
    results = []
    for _ in range(2):
        with tx(conn):
            results.append(finance.create_finance(
                conn, retailer, cid, imei=VALID_IMEI, product_price=rupees(30000),
                down_payment=rupees(8000), tenure_months=11,
                idempotency_key="client-retry-1",
            ))
    assert results[0]["finance_id"] == results[1]["finance_id"]
    assert conn.execute("SELECT COUNT(*) c FROM finance_accounts").fetchone()["c"] == 1
    assert licensing.wallet(conn, world["retailer_id"])["used"] == 1


def test_one_activation_per_finance_is_enforced_by_the_database():
    world = build_world()
    result = make_finance(world)
    rows = world["conn"].execute(
        "SELECT COUNT(*) c FROM license_activations WHERE finance_id = ? AND status = 'CONSUMED'",
        (result["finance_id"],),
    ).fetchone()["c"]
    assert rows == 1


def test_agreement_records_the_priced_terms():
    world = build_world()
    result = make_finance(world)
    row = world["conn"].execute(
        "SELECT terms_json, doc_version FROM finance_agreements WHERE finance_id = ?",
        (result["finance_id"],),
    ).fetchone()
    import json

    terms = json.loads(row["terms_json"])
    assert terms["financed_amount"] == rupees(22000)
    assert terms["tenure_months"] == 11
    assert row["doc_version"] == "v1"
