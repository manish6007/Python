"""Everything the Customer app calls."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from emi_locker import finance as finance_mod
from emi_locker import lifecycle
from emi_locker.core import Actor

from ..access import own_customer_id
from ..deps import current_actor, get_conn

router = APIRouter(prefix="/me", tags=["customer"])


@router.get("/finances")
def my_finances(actor: Actor = Depends(current_actor),
                conn: sqlite3.Connection = Depends(get_conn)):
    customer_id = own_customer_id(conn, actor)
    rows = conn.execute(
        "SELECT f.id finance_id, f.status, f.principal, f.emi_amount, f.tenure_months,"
        " f.start_date, d.imei, d.model, d.status device_status,"
        " (SELECT COALESCE(SUM(amount_paise),0) FROM emi_schedules e"
        "   WHERE e.finance_id = f.id AND e.status NOT IN ('PAID','WAIVED')) outstanding_paise,"
        " (SELECT COUNT(*) FROM emi_schedules e"
        "   WHERE e.finance_id = f.id AND e.status = 'PAID') paid_count"
        " FROM finance_accounts f LEFT JOIN devices d ON d.id = f.device_id"
        " WHERE f.customer_id = ? ORDER BY f.created_at DESC",
        (customer_id,),
    ).fetchall()
    out = []
    for row in rows:
        next_due = conn.execute(
            "SELECT id, seq, amount_paise, due_date, status FROM emi_schedules"
            " WHERE finance_id = ? AND status NOT IN ('PAID','WAIVED') ORDER BY seq LIMIT 1",
            (row["finance_id"],)).fetchone()
        out.append(dict(row, next_due=dict(next_due) if next_due else None))
    return {"customer_id": customer_id, "finances": out}


@router.get("/payments")
def my_payments(actor: Actor = Depends(current_actor),
                conn: sqlite3.Connection = Depends(get_conn)):
    customer_id = own_customer_id(conn, actor)
    rows = conn.execute(
        "SELECT p.id payment_id, p.amount_paise, p.method, p.status, p.updated_at,"
        " p.finance_id, e.seq emi_seq, r.number receipt_number"
        " FROM payment_transactions p"
        " JOIN finance_accounts f ON f.id = p.finance_id"
        " LEFT JOIN emi_schedules e ON e.id = p.emi_id"
        " LEFT JOIN receipts r ON r.payment_id = p.id"
        " WHERE f.customer_id = ? AND p.status IN ('SUCCESS','FAILED')"
        " ORDER BY p.updated_at DESC LIMIT 100",
        (customer_id,),
    ).fetchall()
    return {"payments": [dict(r) for r in rows]}


@router.get("/reminders")
def my_reminders(actor: Actor = Depends(current_actor),
                 conn: sqlite3.Connection = Depends(get_conn)):
    """What the app would have received as a push notification."""
    customer_id = own_customer_id(conn, actor)
    rows = lifecycle.due_reminders(conn)
    mine = [r for r in rows if conn.execute(
        "SELECT customer_id FROM finance_accounts WHERE id = ?",
        (r["finance_id"],)).fetchone()["customer_id"] == customer_id]
    return {"reminders": mine}


@router.get("/closure/{finance_id}")
def closure(finance_id: str, actor: Actor = Depends(current_actor),
            conn: sqlite3.Connection = Depends(get_conn)):
    from ..access import assert_can_view_finance

    assert_can_view_finance(conn, actor, finance_id)
    return lifecycle.closure_certificate(conn, finance_id)


@router.get("/profile")
def my_profile(actor: Actor = Depends(current_actor),
               conn: sqlite3.Connection = Depends(get_conn)):
    customer_id = own_customer_id(conn, actor)
    row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    retailer = conn.execute(
        "SELECT name, mobile FROM users WHERE id = ?", (row["retailer_id"],)).fetchone()
    out = dict(row)
    out["retailer"] = dict(retailer) if retailer else None
    out["missing_consents"] = finance_mod.missing_consents(conn, customer_id)
    return out
