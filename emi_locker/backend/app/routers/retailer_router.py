"""Everything the Retailer app calls."""
from __future__ import annotations

import datetime as _dt
import sqlite3

from fastapi import APIRouter, Depends, Header

from emi_locker import finance as finance_mod
from emi_locker import licensing, lifecycle
from emi_locker.core import Actor, assert_can_touch_retailer
from emi_locker.db import tx
from emi_locker.errors import NotFound

from ..access import assert_can_view_finance
from ..deps import current_actor, get_conn, require_roles, retailer_scope_of
from ..schemas import ConsentIn, CustomerIn, FinanceIn, QuoteIn

router = APIRouter(tags=["retailer"])
RetailerActor = require_roles("RETAILER", "STAFF", "SUPER_ADMIN")


@router.get("/retailer/dashboard")
def dashboard(actor: Actor = Depends(RetailerActor),
              conn: sqlite3.Connection = Depends(get_conn)):
    retailer_id = retailer_scope_of(actor)
    one = lambda sql, args=(): conn.execute(sql, args).fetchone()[0]  # noqa: E731
    today = finance_mod.today().isoformat()
    return {
        "retailer_id": retailer_id,
        "customers": one("SELECT COUNT(*) FROM customers WHERE retailer_id = ?", (retailer_id,)),
        "active_finance": one(
            "SELECT COUNT(*) FROM finance_accounts WHERE retailer_id = ? AND status = 'ACTIVE'",
            (retailer_id,)),
        "overdue_finance": one(
            "SELECT COUNT(*) FROM finance_accounts WHERE retailer_id = ? AND status = 'OVERDUE'",
            (retailer_id,)),
        "completed_finance": one(
            "SELECT COUNT(*) FROM finance_accounts WHERE retailer_id = ?"
            " AND status = 'COMPLETED'", (retailer_id,)),
        "outstanding_paise": one(
            "SELECT COALESCE(SUM(e.amount_paise), 0) FROM emi_schedules e"
            " JOIN finance_accounts f ON f.id = e.finance_id"
            " WHERE f.retailer_id = ? AND e.status NOT IN ('PAID','WAIVED')", (retailer_id,)),
        "due_today_paise": one(
            "SELECT COALESCE(SUM(e.amount_paise), 0) FROM emi_schedules e"
            " JOIN finance_accounts f ON f.id = e.finance_id"
            " WHERE f.retailer_id = ? AND e.due_date = ? AND e.status NOT IN ('PAID','WAIVED')",
            (retailer_id, today)),
        "collected_today_paise": one(
            "SELECT COALESCE(SUM(p.amount_paise), 0) FROM payment_transactions p"
            " JOIN finance_accounts f ON f.id = p.finance_id"
            " WHERE f.retailer_id = ? AND p.status = 'SUCCESS' AND p.updated_at LIKE ?",
            (retailer_id, today + "%")),
        "wallet": licensing.wallet(conn, retailer_id),
    }


@router.get("/retailer/customers")
def list_customers(q: str = "", actor: Actor = Depends(RetailerActor),
                   conn: sqlite3.Connection = Depends(get_conn)):
    retailer_id = retailer_scope_of(actor)
    like = "%%%s%%" % q.strip()
    rows = conn.execute(
        "SELECT c.id, c.name, c.mobile, c.kyc_status, c.created_at,"
        " (SELECT COUNT(*) FROM finance_accounts f WHERE f.customer_id = c.id) finance_count,"
        " (SELECT COALESCE(SUM(e.amount_paise),0) FROM emi_schedules e"
        "   JOIN finance_accounts f ON f.id = e.finance_id"
        "   WHERE f.customer_id = c.id AND e.status NOT IN ('PAID','WAIVED')) outstanding_paise"
        " FROM customers c WHERE c.retailer_id = ?"
        "   AND (? = '' OR c.name LIKE ? OR c.mobile LIKE ?)"
        " ORDER BY c.created_at DESC LIMIT 200",
        (retailer_id, q.strip(), like, like),
    ).fetchall()
    return {"customers": [dict(r) for r in rows]}


@router.post("/retailer/customers", status_code=201)
def create_customer(body: CustomerIn, actor: Actor = Depends(RetailerActor),
                    conn: sqlite3.Connection = Depends(get_conn)):
    retailer_id = retailer_scope_of(actor)
    with tx(conn):
        cid = finance_mod.create_customer(
            conn, actor, retailer_id, body.name, body.mobile, body.address)
    return {"customer_id": cid}


@router.get("/retailer/customers/{customer_id}")
def customer_detail(customer_id: str, actor: Actor = Depends(RetailerActor),
                    conn: sqlite3.Connection = Depends(get_conn)):
    row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if row is None:
        raise NotFound("customer %s" % customer_id)
    assert_can_touch_retailer(conn, actor, row["retailer_id"])
    finances = conn.execute(
        "SELECT id, status, principal, emi_amount, tenure_months, created_at"
        " FROM finance_accounts WHERE customer_id = ? ORDER BY created_at DESC",
        (customer_id,),
    ).fetchall()
    out = dict(row)
    out["missing_consents"] = finance_mod.missing_consents(conn, customer_id)
    out["required_consents"] = list(finance_mod.REQUIRED_CONSENTS)
    out["finances"] = [dict(r) for r in finances]
    return out


@router.post("/retailer/customers/{customer_id}/consents", status_code=201)
def add_consent(customer_id: str, body: ConsentIn, actor: Actor = Depends(RetailerActor),
                conn: sqlite3.Connection = Depends(get_conn)):
    row = conn.execute(
        "SELECT retailer_id FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if row is None:
        raise NotFound("customer %s" % customer_id)
    assert_can_touch_retailer(conn, actor, row["retailer_id"])
    with tx(conn):
        consent_id = finance_mod.record_consent(
            conn, actor, customer_id, body.consent_type, body.doc_version,
            body.channel, body.meta)
    return {"consent_id": consent_id,
            "missing_consents": finance_mod.missing_consents(conn, customer_id)}


@router.post("/finance/quote")
def quote(body: QuoteIn, actor: Actor = Depends(RetailerActor)):
    """Price the plan for the agreement screen, before anything is committed."""
    principal = body.product_price - body.down_payment
    rows = finance_mod.build_schedule(principal, body.tenure_months, finance_mod.today())
    return {
        "product_price": body.product_price,
        "down_payment": body.down_payment,
        "financed_amount": principal,
        "tenure_months": body.tenure_months,
        "emi_amount": rows[0]["amount_paise"],
        "final_emi_amount": rows[-1]["amount_paise"],
        "total_payable": principal,
        "first_due_date": rows[0]["due_date"].isoformat(),
        "schedule": [
            {"seq": r["seq"], "amount_paise": r["amount_paise"],
             "due_date": r["due_date"].isoformat()} for r in rows
        ],
    }


@router.post("/finance", status_code=201)
def create_finance(body: FinanceIn, actor: Actor = Depends(RetailerActor),
                   conn: sqlite3.Connection = Depends(get_conn),
                   idempotency_key: str = Header(default="")):
    with tx(conn):
        return finance_mod.create_finance(
            conn, actor, body.customer_id, body.imei, body.product_price,
            body.down_payment, body.tenure_months, model=body.model,
            late_fee_paise=body.late_fee_paise, grace_days=body.grace_days,
            idempotency_key=idempotency_key or None)


@router.get("/finance/{finance_id}")
def finance_detail(finance_id: str, actor: Actor = Depends(current_actor),
                   conn: sqlite3.Connection = Depends(get_conn)):
    row = assert_can_view_finance(conn, actor, finance_id)
    paid = conn.execute(
        "SELECT COALESCE(SUM(amount_paise),0) p FROM emi_schedules"
        " WHERE finance_id = ? AND status = 'PAID'", (finance_id,)).fetchone()["p"]
    customer = conn.execute(
        "SELECT name, mobile FROM customers WHERE id = ?", (row["customer_id"],)).fetchone()
    device = conn.execute(
        "SELECT id, imei, model, status FROM devices WHERE id = ?",
        (row["device_id"],)).fetchone()
    next_due = conn.execute(
        "SELECT id, seq, amount_paise, due_date, status FROM emi_schedules"
        " WHERE finance_id = ? AND status NOT IN ('PAID','WAIVED') ORDER BY seq LIMIT 1",
        (finance_id,)).fetchone()
    return {
        "finance_id": finance_id,
        "status": row["status"],
        "customer": dict(customer) if customer else None,
        "customer_id": row["customer_id"],
        "device": dict(device) if device else None,
        "product_price": row["product_price"],
        "down_payment": row["down_payment"],
        "principal": row["principal"],
        "emi_amount": row["emi_amount"],
        "tenure_months": row["tenure_months"],
        "paid_paise": paid,
        "outstanding_paise": finance_mod.outstanding(conn, finance_id),
        "next_due": dict(next_due) if next_due else None,
        "start_date": row["start_date"],
    }


@router.get("/finance/{finance_id}/emi-schedule")
def emi_schedule(finance_id: str, actor: Actor = Depends(current_actor),
                 conn: sqlite3.Connection = Depends(get_conn)):
    assert_can_view_finance(conn, actor, finance_id)
    return {"finance_id": finance_id, "schedule": finance_mod.get_schedule(conn, finance_id)}


@router.get("/retailer/collections/pending")
def pending_collections(actor: Actor = Depends(RetailerActor),
                        conn: sqlite3.Connection = Depends(get_conn)):
    """Everything this retailer should be chasing, worst first."""
    retailer_id = retailer_scope_of(actor)
    rows = conn.execute(
        "SELECT e.id emi_id, e.seq, e.amount_paise, e.due_date, e.status,"
        " f.id finance_id, c.id customer_id, c.name customer_name, c.mobile"
        " FROM emi_schedules e"
        " JOIN finance_accounts f ON f.id = e.finance_id"
        " JOIN customers c ON c.id = f.customer_id"
        " WHERE f.retailer_id = ? AND e.status IN ('DUE','GRACE_PERIOD','OVERDUE')"
        " ORDER BY CASE e.status WHEN 'OVERDUE' THEN 0 WHEN 'GRACE_PERIOD' THEN 1 ELSE 2 END,"
        "          e.due_date",
        (retailer_id,),
    ).fetchall()
    today = finance_mod.today()
    out = []
    for r in rows:
        days = (today - _dt.date.fromisoformat(r["due_date"])).days
        out.append(dict(r, days_past_due=max(days, 0)))
    return {"pending": out,
            "total_paise": sum(r["amount_paise"] for r in out)}


@router.post("/retailer/run-daily-sweep")
def run_sweep(actor: Actor = Depends(RetailerActor),
              conn: sqlite3.Connection = Depends(get_conn)):
    """Local testing aid: advance instalment states without waiting for cron.

    In production this is a scheduled job, not an endpoint anyone can call.
    """
    with tx(conn):
        moved = lifecycle.run_daily_status_sweep(conn, actor)
    return {"moved": {k: len(v) for k, v in moved.items()}}
