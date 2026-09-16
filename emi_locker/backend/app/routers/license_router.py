"""License wallet, key redemption and allocation."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Header

from emi_locker import licensing
from emi_locker.core import Actor
from emi_locker.db import tx

from ..deps import current_actor, get_conn, require_roles

router = APIRouter(prefix="/licenses", tags=["licenses"])


@router.get("/wallet")
def wallet(actor: Actor = Depends(require_roles("RETAILER", "DISTRIBUTOR", "SUPER_ADMIN")),
           conn: sqlite3.Connection = Depends(get_conn)):
    return licensing.wallet(conn, actor.user_id)


@router.post("/redeem")
def redeem(body: dict, actor: Actor = Depends(require_roles("RETAILER", "DISTRIBUTOR")),
           conn: sqlite3.Connection = Depends(get_conn)):
    with tx(conn):
        return licensing.redeem_license(conn, actor, body.get("key", ""))


@router.post("/allocate")
def allocate(body: dict,
             actor: Actor = Depends(require_roles("DISTRIBUTOR", "SUPER_ADMIN")),
             conn: sqlite3.Connection = Depends(get_conn),
             idempotency_key: str = Header(default="")):
    with tx(conn):
        return licensing.allocate_quota(
            conn, actor, body["to_owner"], int(body["quota"]), body.get("license_id"),
            idempotency_key=idempotency_key or None)


@router.get("/history")
def history(actor: Actor = Depends(current_actor),
            conn: sqlite3.Connection = Depends(get_conn)):
    rows = conn.execute(
        "SELECT a.id, a.created_at, a.finance_id, a.device_id, a.status, l.id license_id"
        " FROM license_activations a LEFT JOIN licenses l ON l.id = a.license_id"
        " WHERE a.owner_id = ? ORDER BY a.created_at DESC LIMIT 100",
        (actor.user_id,),
    ).fetchall()
    return {"activations": [dict(r) for r in rows]}
