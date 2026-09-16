"""Payments, the verified webhook, cash collections and receipts.

The local mock gateway matters more than it looks. It signs a payload with the
real webhook secret and hands it to the *same* ``handle_webhook`` the
production gateway will call. So even on your laptop, an EMI is only ever
marked paid by a verified server-side callback - never by the app saying the
payment worked. If you later swap in a real gateway, nothing about the ledger
path changes.
"""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, Header, Request, Response

from emi_locker import payments as payments_mod
from emi_locker.core import Actor
from emi_locker.db import tx
from emi_locker.errors import NotFound, PermissionDenied, ReplayedEvent

from ..access import assert_can_pay_finance, assert_can_view_finance
from ..config import settings
from ..deps import current_actor, get_conn, require_roles
from ..schemas import CollectionIn, MockPayIn, PaymentIn

router = APIRouter(tags=["payments"])


@router.post("/payments/create", status_code=201)
def create_payment(body: PaymentIn, actor: Actor = Depends(current_actor),
                   conn: sqlite3.Connection = Depends(get_conn)):
    assert_can_pay_finance(conn, actor, body.finance_id)
    with tx(conn):
        out = payments_mod.initiate_payment(
            conn, actor, body.finance_id, body.amount_paise, body.emi_id)
    # A real integration returns the gateway's order id and checkout parameters
    # here; the app opens the gateway SDK with them.
    out["gateway"] = {"provider": "mock" if settings.is_local else "configured",
                      "checkout_url": "/mock-gateway/pay" if settings.is_local else None}
    return out


@router.post("/payments/webhook")
async def webhook(request: Request, response: Response,
                  x_signature: str = Header(default=""),
                  conn: sqlite3.Connection = Depends(get_conn)):
    """Called by the payment gateway. Never by the app."""
    raw = await request.body()
    try:
        with tx(conn):
            result = payments_mod.handle_webhook(conn, raw, x_signature,
                                                 settings.webhook_secret)
    except ReplayedEvent as exc:
        # 200 so the gateway stops retrying an event we have already applied.
        return {"status": "IGNORED", "reason": str(exc)}
    return result


@router.post("/mock-gateway/pay")
def mock_gateway_pay(body: MockPayIn, actor: Actor = Depends(current_actor),
                     conn: sqlite3.Connection = Depends(get_conn)):
    """Local only: stand in for the customer completing checkout.

    Builds a correctly signed callback and feeds it through the real webhook
    handler, so the local flow exercises signature verification, replay
    protection and amount matching exactly as production will.
    """
    if not settings.is_local:
        raise PermissionDenied("the mock gateway is disabled outside local mode")

    payment = conn.execute(
        "SELECT * FROM payment_transactions WHERE id = ?", (body.payment_id,)).fetchone()
    if payment is None:
        raise NotFound("payment %s" % body.payment_id)
    assert_can_pay_finance(conn, actor, payment["finance_id"])

    event = {
        "event_id": "mock-%s" % body.payment_id,
        "payment_id": body.payment_id,
        "status": body.outcome,
        "amount_paise": payment["amount_paise"],
        "gateway_txn_id": "mockpay_%s" % body.payment_id.replace("-", "").lower(),
    }
    raw = json.dumps(event).encode()
    signature = payments_mod.sign_payload(settings.webhook_secret, raw)
    try:
        with tx(conn):
            return payments_mod.handle_webhook(conn, raw, signature, settings.webhook_secret)
    except ReplayedEvent as exc:
        return {"status": "IGNORED", "reason": str(exc)}


@router.post("/collections", status_code=201)
def create_collection(body: CollectionIn,
                      actor: Actor = Depends(require_roles("RETAILER", "STAFF", "SUPER_ADMIN")),
                      conn: sqlite3.Connection = Depends(get_conn),
                      idempotency_key: str = Header(default="")):
    # record_cash_collection does its own retailer-scope check.
    with tx(conn):
        return payments_mod.record_cash_collection(
            conn, actor, body.finance_id, body.amount_paise, body.emi_id, body.mode,
            idempotency_key=idempotency_key or None)


@router.get("/receipts/{payment_id}")
def receipt(payment_id: str, actor: Actor = Depends(current_actor),
            conn: sqlite3.Connection = Depends(get_conn)):
    row = payments_mod.receipt_for(conn, payment_id)
    assert_can_view_finance(conn, actor, row["finance_id"])
    finance = conn.execute(
        "SELECT f.*, c.name customer_name, c.mobile customer_mobile, u.name retailer_name"
        " FROM finance_accounts f JOIN customers c ON c.id = f.customer_id"
        " JOIN users u ON u.id = f.retailer_id WHERE f.id = ?",
        (row["finance_id"],)).fetchone()
    emi = conn.execute(
        "SELECT seq FROM emi_schedules WHERE id = ?", (row["emi_id"],)).fetchone()
    return {
        "receipt_number": row["number"],
        "issued_at": row["created_at"],
        "amount_paise": row["amount_paise"],
        "method": row["method"],
        "finance_id": row["finance_id"],
        "emi_seq": emi["seq"] if emi else None,
        "customer_name": finance["customer_name"],
        "customer_mobile": finance["customer_mobile"],
        "retailer_name": finance["retailer_name"],
    }
