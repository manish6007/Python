"""Everything the Distributor app calls.

Scope is the whole point of this router: a distributor sees its own retailers
and nothing else. Every query here filters on ``parent_id = actor``, and the
shared helpers in ``emi_locker.core`` refuse cross-network access even if a
query here were ever written carelessly.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Header

from emi_locker import licensing, lifecycle, reports
from emi_locker.core import Actor, assert_can_touch_retailer
from emi_locker.db import tx
from emi_locker.errors import NotFound

from ..deps import get_conn, require_roles
from ..schemas import AllocateIn, RedeemIn

router = APIRouter(prefix="/distributor", tags=["distributor"])
DistributorActor = require_roles("DISTRIBUTOR", "SUPER_ADMIN")


def _retailer_ids(conn: sqlite3.Connection, actor: Actor):
    rows = conn.execute(
        "SELECT id FROM users WHERE role = 'RETAILER' AND parent_id = ?",
        (actor.user_id,),
    ).fetchall()
    return [r["id"] for r in rows]


@router.get("/dashboard")
def dashboard(actor: Actor = Depends(DistributorActor),
              conn: sqlite3.Connection = Depends(get_conn)):
    retailers = _retailer_ids(conn, actor)
    placeholders = ",".join("?" * len(retailers)) if retailers else "NULL"

    def one(sql, args=()):
        return conn.execute(sql, args).fetchone()[0]

    wallet = licensing.wallet(conn, actor.user_id)
    allocated = one(
        "SELECT COALESCE(SUM(quota), 0) FROM license_allocations WHERE from_owner = ?",
        (actor.user_id,))

    if retailers:
        active = one(
            "SELECT COUNT(*) FROM finance_accounts WHERE status = 'ACTIVE'"
            " AND retailer_id IN (%s)" % placeholders, tuple(retailers))
        overdue = one(
            "SELECT COUNT(*) FROM finance_accounts WHERE status = 'OVERDUE'"
            " AND retailer_id IN (%s)" % placeholders, tuple(retailers))
        outstanding = one(
            "SELECT COALESCE(SUM(e.amount_paise), 0) FROM emi_schedules e"
            " JOIN finance_accounts f ON f.id = e.finance_id"
            " WHERE e.status NOT IN ('PAID','WAIVED') AND f.retailer_id IN (%s)"
            % placeholders, tuple(retailers))
        customers = one(
            "SELECT COUNT(*) FROM customers WHERE retailer_id IN (%s)" % placeholders,
            tuple(retailers))
        downstream_used = one(
            "SELECT COALESCE(SUM(used_quota), 0) FROM license_wallets"
            " WHERE owner_id IN (%s)" % placeholders, tuple(retailers))
    else:
        active = overdue = outstanding = customers = downstream_used = 0

    return {
        "distributor_id": actor.user_id,
        "retailers": len(retailers),
        "customers": customers,
        "active_finance": active,
        "overdue_finance": overdue,
        "outstanding_paise": outstanding,
        "wallet": wallet,
        "allocated_to_retailers": allocated,
        "activations_used_downstream": downstream_used,
    }


@router.get("/retailers")
def list_retailers(actor: Actor = Depends(DistributorActor),
                   conn: sqlite3.Connection = Depends(get_conn)):
    """Each retailer with the two numbers a distributor actually acts on:
    how much stock they have left, and how much money is outstanding."""
    rows = conn.execute(
        "SELECT u.id, u.name, u.mobile, u.status, u.created_at,"
        " COALESCE(w.total_quota, 0) total_quota,"
        " COALESCE(w.used_quota, 0) used_quota,"
        " COALESCE(w.total_quota - w.used_quota - w.reserved_quota, 0) available_quota,"
        " (SELECT COUNT(*) FROM customers c WHERE c.retailer_id = u.id) customers,"
        " (SELECT COUNT(*) FROM finance_accounts f"
        "    WHERE f.retailer_id = u.id AND f.status = 'ACTIVE') active_finance,"
        " (SELECT COUNT(*) FROM finance_accounts f"
        "    WHERE f.retailer_id = u.id AND f.status = 'OVERDUE') overdue_finance,"
        " (SELECT COALESCE(SUM(e.amount_paise), 0) FROM emi_schedules e"
        "    JOIN finance_accounts f ON f.id = e.finance_id"
        "    WHERE f.retailer_id = u.id AND e.status NOT IN ('PAID','WAIVED'))"
        "   outstanding_paise"
        " FROM users u LEFT JOIN license_wallets w ON w.owner_id = u.id"
        " WHERE u.role = 'RETAILER' AND u.parent_id = ?"
        " ORDER BY outstanding_paise DESC",
        (actor.user_id,),
    ).fetchall()
    return {"retailers": [dict(r) for r in rows]}


@router.get("/retailers/{retailer_id}")
def retailer_detail(retailer_id: str, actor: Actor = Depends(DistributorActor),
                    conn: sqlite3.Connection = Depends(get_conn)):
    assert_can_touch_retailer(conn, actor, retailer_id)
    user = conn.execute(
        "SELECT id, name, mobile, status, created_at FROM users WHERE id = ?",
        (retailer_id,)).fetchone()
    if user is None:
        raise NotFound("retailer %s" % retailer_id)
    finances = conn.execute(
        "SELECT f.id, f.status, f.principal, f.emi_amount, f.tenure_months,"
        " f.created_at, c.name customer_name,"
        " (SELECT COALESCE(SUM(e.amount_paise),0) FROM emi_schedules e"
        "    WHERE e.finance_id = f.id AND e.status NOT IN ('PAID','WAIVED'))"
        "   outstanding_paise"
        " FROM finance_accounts f JOIN customers c ON c.id = f.customer_id"
        " WHERE f.retailer_id = ? ORDER BY f.created_at DESC LIMIT 100",
        (retailer_id,)).fetchall()
    allocations = conn.execute(
        "SELECT id, quota, created_at FROM license_allocations"
        " WHERE to_owner = ? ORDER BY created_at DESC LIMIT 20",
        (retailer_id,)).fetchall()
    return {
        "retailer": dict(user),
        "wallet": licensing.wallet(conn, retailer_id),
        "finances": [dict(r) for r in finances],
        "allocations": [dict(r) for r in allocations],
    }


@router.post("/allocate", status_code=201)
def allocate(body: AllocateIn, actor: Actor = Depends(DistributorActor),
             conn: sqlite3.Connection = Depends(get_conn),
             idempotency_key: str = Header(default="")):
    """Push activation quota down to one of my retailers."""
    with tx(conn):
        return licensing.allocate_quota(
            conn, actor, body.to_owner, body.quota, body.license_id,
            idempotency_key=idempotency_key or None)


@router.post("/redeem")
def redeem(body: RedeemIn, actor: Actor = Depends(DistributorActor),
           conn: sqlite3.Connection = Depends(get_conn)):
    """Claim an activation pack bought from the admin."""
    with tx(conn):
        return licensing.redeem_license(conn, actor, body.key)


@router.get("/licenses")
def my_licenses(actor: Actor = Depends(DistributorActor),
                conn: sqlite3.Connection = Depends(get_conn)):
    rows = conn.execute(
        "SELECT l.id, l.key_masked, l.quota, l.status, l.valid_from, l.valid_to,"
        " p.name plan_name,"
        " (SELECT COUNT(*) FROM license_activations a"
        "    WHERE a.license_id = l.id AND a.status = 'CONSUMED') consumed"
        " FROM licenses l JOIN license_plans p ON p.id = l.plan_id"
        " WHERE l.owner_id = ? ORDER BY l.valid_to DESC",
        (actor.user_id,)).fetchall()
    return {"licenses": [dict(r) for r in rows]}


@router.get("/outstanding")
def outstanding(actor: Actor = Depends(DistributorActor),
                conn: sqlite3.Connection = Depends(get_conn)):
    return {"rows": reports.outstanding_report(conn, actor)}


@router.get("/overdue")
def overdue(actor: Actor = Depends(DistributorActor),
            conn: sqlite3.Connection = Depends(get_conn)):
    """Overdue accounts across my retailers only."""
    mine = set(_retailer_ids(conn, actor))
    rows = [r for r in lifecycle.overdue_report(conn) if r["retailer_id"] in mine]
    names = {
        r["id"]: r["name"]
        for r in conn.execute("SELECT id, name FROM users").fetchall()
    }
    return {
        "rows": [dict(r, retailer_name=names.get(r["retailer_id"], "-")) for r in rows],
        "total_paise": sum(r["overdue_amount"] for r in rows),
    }


@router.get("/commission")
def commission(actor: Actor = Depends(DistributorActor),
               conn: sqlite3.Connection = Depends(get_conn)):
    return reports.commission_report(conn, actor)
