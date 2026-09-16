"""Data scoping between distributors/retailers, and the audit trail itself."""
from __future__ import annotations

import sqlite3

import pytest

from emi_locker import finance, licensing, reports
from emi_locker.core import Actor, create_user, rupees
from emi_locker.db import tx
from emi_locker.errors import PermissionDenied
from tests.helpers import OTHER_IMEI, build_world, make_finance


def two_networks():
    """Two distributors, each with a retailer and one live finance."""
    world = build_world()
    conn = world["conn"]
    with tx(conn):
        d2 = create_user(conn, "DISTRIBUTOR", "Dist2", actor=world["admin"])
        r2 = create_user(conn, "RETAILER", "Retailer2", parent_id=d2, actor=world["admin"])
        plan = licensing.create_plan(conn, world["admin"], "P2", 50, rupees(1), 365)
        issued = licensing.generate_license(conn, world["admin"], plan, "DISTRIBUTOR",
                                            owner_id=d2, quota=50)
        licensing.allocate_quota(conn, Actor(d2, "DISTRIBUTOR"), r2, 20,
                                 license_id=issued["license_id"])
    world["d2"] = Actor(d2, "DISTRIBUTOR")
    world["r2_id"] = r2
    world["r2"] = Actor(r2, "RETAILER", parent_id=d2)

    world["fin1"] = make_finance(world)
    with tx(conn):
        cid = finance.create_customer(conn, world["r2"], r2, "Other Customer", "9111111111")
        for consent in finance.REQUIRED_CONSENTS:
            finance.record_consent(conn, world["r2"], cid, consent, "v1")
    with tx(conn):
        world["fin2"] = finance.create_finance(
            conn, world["r2"], cid, imei=OTHER_IMEI, product_price=rupees(20000),
            down_payment=rupees(5000), tenure_months=5)
    return world


def test_retailer_cannot_read_another_retailers_finance():
    world = two_networks()
    with pytest.raises(PermissionDenied):
        finance.finance_summary(world["conn"], world["retailer"], world["fin2"]["finance_id"])


def test_distributor_cannot_read_another_networks_finance():
    world = two_networks()
    with pytest.raises(PermissionDenied):
        finance.finance_summary(world["conn"], world["dist"], world["fin2"]["finance_id"])


def test_distributor_sees_only_its_own_retailers_in_reports():
    world = two_networks()
    rows = reports.retailer_performance(world["conn"], world["dist"])
    assert {r["retailer_id"] for r in rows} == {world["retailer_id"]}

    rows2 = reports.retailer_performance(world["conn"], world["d2"])
    assert {r["retailer_id"] for r in rows2} == {world["r2_id"]}


def test_admin_sees_the_whole_book():
    world = two_networks()
    rows = reports.retailer_performance(world["conn"], world["admin"])
    assert {r["retailer_id"] for r in rows} == {world["retailer_id"], world["r2_id"]}


def test_outstanding_report_is_scoped_too():
    world = two_networks()
    rows = reports.outstanding_report(world["conn"], world["retailer"])
    assert {r["retailer_id"] for r in rows} == {world["retailer_id"]}
    assert rows[0]["outstanding_paise"] == rupees(22000)


def test_retailer_cannot_create_a_customer_under_another_retailer():
    world = two_networks()
    with pytest.raises(PermissionDenied):
        with tx(world["conn"]):
            finance.create_customer(world["conn"], world["retailer"], world["r2_id"],
                                    "Poached", "9222222222")


def test_collection_staff_inherit_only_their_retailers_scope():
    world = two_networks()
    conn = world["conn"]
    with tx(conn):
        staff_id = create_user(conn, "STAFF", "Collector", parent_id=world["retailer_id"],
                               actor=world["admin"])
    staff = Actor(staff_id, "STAFF", parent_id=world["retailer_id"])
    summary = finance.finance_summary(conn, staff, world["fin1"]["finance_id"])
    assert summary["finance_id"] == world["fin1"]["finance_id"]
    with pytest.raises(PermissionDenied):
        finance.finance_summary(conn, staff, world["fin2"]["finance_id"])


def test_only_admin_reads_the_audit_trail():
    world = two_networks()
    with pytest.raises(PermissionDenied):
        reports.audit_trail(world["conn"], world["retailer"], world["fin1"]["finance_id"])
    rows = reports.audit_trail(world["conn"], world["admin"], world["fin1"]["finance_id"])
    assert any(r["action"] == "finance.create" for r in rows)


def test_audit_rows_cannot_be_updated_or_deleted():
    world = build_world()
    conn = world["conn"]
    make_finance(world)
    row_id = conn.execute("SELECT id FROM audit_logs LIMIT 1").fetchone()["id"]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE audit_logs SET action = 'tampered' WHERE id = ?", (row_id,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM audit_logs WHERE id = ?", (row_id,))


def test_every_license_movement_is_audited():
    world = build_world(quota=5)
    conn = world["conn"]
    make_finance(world)
    actions = {r["action"] for r in conn.execute(
        "SELECT DISTINCT action FROM audit_logs").fetchall()}
    for expected in ("license.generate", "license.redeem", "license.allocate",
                     "license.activate", "finance.create"):
        assert expected in actions, expected


def test_suspended_user_cannot_act():
    world = build_world()
    conn = world["conn"]
    conn.execute("UPDATE users SET status = 'SUSPENDED' WHERE id = ?", (world["retailer_id"],))
    with pytest.raises(PermissionDenied):
        Actor.load(conn, world["retailer_id"])
