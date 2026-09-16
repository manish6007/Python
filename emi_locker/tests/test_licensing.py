"""License quota must never oversell, double-spend or outlive its validity."""
from __future__ import annotations

import datetime as _dt
import os
import sqlite3
import tempfile
import threading

import pytest

from emi_locker import licensing
from emi_locker.core import Actor, create_user, rupees
from emi_locker.db import connect, open_db, tx
from emi_locker.errors import (
    InsufficientQuota,
    LicenseInvalid,
    PermissionDenied,
)
from tests.helpers import build_world


def test_key_is_hashed_never_stored_in_clear():
    world = build_world()
    conn = world["conn"]
    row = conn.execute("SELECT key_hash, key_masked FROM licenses").fetchone()
    assert world["license_key"] not in row["key_hash"]
    assert row["key_hash"] == licensing.hash_key(world["license_key"])
    assert row["key_masked"].startswith("*")
    assert row["key_masked"].endswith(world["license_key"].split("-")[-1])


def test_key_is_not_a_predictable_serial():
    keys = set()
    conn = open_db()
    with tx(conn):
        admin = Actor(create_user(conn, "SUPER_ADMIN", "Admin"), "SUPER_ADMIN")
        plan = licensing.create_plan(conn, admin, "P", 10, rupees(100), 365)
        for _ in range(50):
            keys.add(licensing.generate_license(conn, admin, plan, "RETAILER")["key"])
    assert len(keys) == 50


def test_key_cannot_be_redeemed_twice():
    world = build_world()
    conn = world["conn"]
    with tx(conn):
        other = create_user(conn, "DISTRIBUTOR", "Dist2", actor=world["admin"])
    with pytest.raises(LicenseInvalid):
        with tx(conn):
            licensing.redeem_license(conn, Actor(other, "DISTRIBUTOR"), world["license_key"])


def test_allocation_is_idempotent_under_retry():
    world = build_world(quota=0)
    conn = world["conn"]
    for _ in range(3):
        with tx(conn):
            licensing.allocate_quota(conn, world["dist"], world["retailer_id"], 25,
                                     idempotency_key="same-request")
    assert licensing.wallet(conn, world["retailer_id"])["available"] == 25


def test_distributor_cannot_allocate_beyond_its_balance():
    world = build_world(quota=0)
    conn = world["conn"]
    available = licensing.wallet(conn, world["dist_id"])["available"]
    with pytest.raises(InsufficientQuota):
        with tx(conn):
            licensing.allocate_quota(conn, world["dist"], world["retailer_id"], available + 1)
    assert licensing.wallet(conn, world["dist_id"])["available"] == available


def test_distributor_cannot_touch_another_distributors_retailer():
    world = build_world()
    conn = world["conn"]
    with tx(conn):
        rival_id = create_user(conn, "DISTRIBUTOR", "Rival", actor=world["admin"])
        plan = licensing.create_plan(conn, world["admin"], "RivalPlan", 10, rupees(1), 365)
        key = licensing.generate_license(conn, world["admin"], plan, "DISTRIBUTOR",
                                         owner_id=rival_id)
    rival = Actor(rival_id, "DISTRIBUTOR")
    assert key["quota"] > 0  # the rival genuinely has stock; the denial is about scope
    with pytest.raises(PermissionDenied):
        with tx(conn):
            licensing.allocate_quota(conn, rival, world["retailer_id"], 1)


def test_retailer_cannot_allocate_quota_to_itself():
    world = build_world()
    with pytest.raises(PermissionDenied):
        with tx(world["conn"]):
            licensing.allocate_quota(world["conn"], world["retailer"], world["retailer_id"], 10)


def test_expired_license_stops_new_activations():
    world = build_world()
    conn = world["conn"]
    yesterday = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    conn.execute("UPDATE licenses SET valid_to = ?", (yesterday,))
    with tx(conn):
        expired = licensing.expire_due_licenses(conn, world["admin"])
    assert expired
    with pytest.raises(LicenseInvalid):
        with tx(conn):
            licensing.consume_activation(conn, world["retailer"], world["retailer_id"])


def test_suspended_license_stops_new_activations():
    world = build_world()
    conn = world["conn"]
    with tx(conn):
        licensing.set_license_status(conn, world["admin"], world["license_id"],
                                     "SUSPENDED", reason="payment reversed")
    with pytest.raises(LicenseInvalid):
        with tx(conn):
            licensing.consume_activation(conn, world["retailer"], world["retailer_id"])


def test_activation_rollback_returns_the_unit():
    world = build_world(quota=5)
    conn = world["conn"]
    with tx(conn):
        act = licensing.consume_activation(conn, world["retailer"], world["retailer_id"])
    assert licensing.wallet(conn, world["retailer_id"])["available"] == 4
    with tx(conn):
        licensing.rollback_activation(conn, world["admin"], act["activation_id"],
                                      reason="finance cancelled")
    assert licensing.wallet(conn, world["retailer_id"])["available"] == 5


def test_transfer_moves_only_unused_quota_and_needs_admin_approval():
    world = build_world(quota=1)
    conn = world["conn"]
    with tx(conn):
        target = create_user(conn, "RETAILER", "Target", parent_id=world["dist_id"],
                             actor=world["admin"])
    with pytest.raises(PermissionDenied):
        with tx(conn):
            licensing.transfer_license(conn, world["admin"], world["license_id"], target,
                                       approved_by_admin=False)
    with tx(conn):
        moved = licensing.transfer_license(conn, world["admin"], world["license_id"], target,
                                           approved_by_admin=True)
    assert moved["moved"] > 0
    assert licensing.wallet(conn, target)["available"] == moved["moved"]


def test_renewal_extends_validity_from_the_later_of_expiry_or_today():
    world = build_world()
    conn = world["conn"]
    old = conn.execute("SELECT valid_to FROM licenses WHERE id = ?",
                       (world["license_id"],)).fetchone()["valid_to"]
    with tx(conn):
        out = licensing.renew_license(conn, world["admin"], world["license_id"], extra_days=365)
    assert out["old_expiry"] == old
    assert _dt.date.fromisoformat(out["new_expiry"]) > _dt.date.fromisoformat(old)


def test_renewal_can_burn_unused_quota_when_policy_says_so():
    world = build_world(quota=10)
    conn = world["conn"]
    with tx(conn):
        licensing.consume_activation(conn, world["retailer"], world["retailer_id"])
    with tx(conn):
        licensing.renew_license(conn, world["admin"], world["license_id"], 30,
                                carry_forward_unused=False)
    assert licensing.wallet(conn, world["dist_id"])["available"] == 0


def _worker(db_path, owner_id, actor_id, results, index):
    conn = connect(db_path)
    try:
        with tx(conn):
            licensing.consume_activation(conn, Actor(actor_id, "RETAILER"), owner_id)
        results[index] = "ok"
    except InsufficientQuota:
        results[index] = "rejected"
    except sqlite3.OperationalError as exc:  # pragma: no cover - lock timeout
        results[index] = "locked:%s" % exc
    finally:
        conn.close()


def test_concurrent_activations_cannot_oversell_the_wallet():
    """20 simultaneous activations against a balance of 5 must yield exactly 5."""
    quota = 5
    threads_count = 20
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(db_path)
    try:
        conn = connect(db_path)
        from emi_locker.db import init_schema

        init_schema(conn)
        with tx(conn):
            admin = Actor(create_user(conn, "SUPER_ADMIN", "Admin"), "SUPER_ADMIN")
            dist_id = create_user(conn, "DISTRIBUTOR", "Dist", actor=admin)
            retailer_id = create_user(conn, "RETAILER", "Retailer", parent_id=dist_id,
                                      actor=admin)
            plan = licensing.create_plan(conn, admin, "P", 500, rupees(1), 365)
            issued = licensing.generate_license(conn, admin, plan, "DISTRIBUTOR",
                                                owner_id=dist_id, quota=500)
            licensing.allocate_quota(conn, Actor(dist_id, "DISTRIBUTOR"), retailer_id, quota,
                                     license_id=issued["license_id"])
        conn.close()

        results = [None] * threads_count
        barrier = threading.Barrier(threads_count)

        def run(i):
            barrier.wait()
            _worker(db_path, retailer_id, retailer_id, results, i)

        threads = [threading.Thread(target=run, args=(i,)) for i in range(threads_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(r is not None for r in results), results
        assert not [r for r in results if str(r).startswith("locked")], results
        assert results.count("ok") == quota, results
        assert results.count("rejected") == threads_count - quota

        check = connect(db_path)
        wallet = licensing.wallet(check, retailer_id)
        assert wallet["used"] == quota
        assert wallet["available"] == 0
        consumed = check.execute(
            "SELECT COUNT(*) c FROM license_activations WHERE status = 'CONSUMED'"
        ).fetchone()["c"]
        assert consumed == quota
        check.close()
    finally:
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(db_path + suffix):
                os.unlink(db_path + suffix)
