"""Payment initiation, gateway webhook verification, receipts and collections.

Section 10 of the blueprint states the rule this module exists to enforce:
an EMI is never marked paid from a client-side success response. The only
path from INITIATED to SUCCESS runs through ``handle_webhook``, which checks
the signature, the amount and the replay table before it touches the ledger.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from typing import Any, Dict, Optional

from .core import Actor, assert_can_touch_retailer, audit, next_id, now
from .errors import (
    NotFound,
    PaymentVerificationError,
    ReplayedEvent,
    ValidationError,
)


def sign_payload(secret: str, raw_body: bytes) -> str:
    """HMAC-SHA256 over the exact bytes the gateway sent."""
    return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, raw_body: bytes, signature: str) -> bool:
    expected = sign_payload(secret, raw_body)
    return hmac.compare_digest(expected, (signature or "").strip())


def _next_receipt_number(conn: sqlite3.Connection) -> str:
    conn.execute(
        "INSERT INTO counters(name, value) VALUES ('receipt_no', 1) "
        "ON CONFLICT(name) DO UPDATE SET value = value + 1"
    )
    value = conn.execute("SELECT value FROM counters WHERE name = 'receipt_no'").fetchone()[0]
    return "AE/%s/%06d" % (now()[:4], value)


def _next_unpaid_emi(conn: sqlite3.Connection, finance_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM emi_schedules WHERE finance_id = ? AND status NOT IN ('PAID','WAIVED')"
        " ORDER BY seq LIMIT 1",
        (finance_id,),
    ).fetchone()


def initiate_payment(
    conn: sqlite3.Connection,
    actor: Actor,
    finance_id: str,
    amount_paise: int,
    emi_id: Optional[str] = None,
    gateway_order: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an INITIATED transaction. Carries no ledger effect by itself."""
    fin = conn.execute("SELECT * FROM finance_accounts WHERE id = ?", (finance_id,)).fetchone()
    if fin is None:
        raise NotFound("finance %s" % finance_id)
    if amount_paise <= 0:
        raise ValidationError("amount must be positive")
    if emi_id is None:
        emi = _next_unpaid_emi(conn, finance_id)
        if emi is None:
            raise ValidationError("finance %s has no unpaid instalment" % finance_id)
        emi_id = emi["id"]

    pay_id = next_id(conn, "payment")
    conn.execute(
        "INSERT INTO payment_transactions(id, finance_id, emi_id, amount_paise, method,"
        " gateway_order, status, created_at, updated_at)"
        " VALUES (?,?,?,?, 'ONLINE', ?, 'INITIATED', ?, ?)",
        (pay_id, finance_id, emi_id, amount_paise, gateway_order, now(), now()),
    )
    audit(conn, actor, "payment.initiate", "payment_transaction", pay_id,
          after={"finance_id": finance_id, "emi_id": emi_id, "amount_paise": amount_paise})
    return {"payment_id": pay_id, "emi_id": emi_id, "amount_paise": amount_paise,
            "status": "INITIATED"}


def _apply_success(
    conn: sqlite3.Connection,
    actor: Optional[Actor],
    payment: sqlite3.Row,
    gateway_txn_id: Optional[str],
) -> Dict[str, Any]:
    """Move one payment to SUCCESS, mark its EMI paid and cut a receipt."""
    cur = conn.execute(
        "UPDATE payment_transactions SET status = 'SUCCESS', gateway_txn_id = ?, updated_at = ?"
        " WHERE id = ? AND status = 'INITIATED'",
        (gateway_txn_id, now(), payment["id"]),
    )
    if cur.rowcount == 0:
        # Already applied by a concurrent delivery of the same event.
        existing = conn.execute(
            "SELECT r.number FROM receipts r WHERE r.payment_id = ?", (payment["id"],)
        ).fetchone()
        return {"payment_id": payment["id"], "status": "SUCCESS", "duplicate": True,
                "receipt_number": existing["number"] if existing else None}

    emi_id = payment["emi_id"]
    if emi_id:
        conn.execute(
            "UPDATE emi_schedules SET status = 'PAID', paid_at = ? WHERE id = ?",
            (now(), emi_id),
        )

    receipt_id = next_id(conn, "receipt")
    number = _next_receipt_number(conn)
    conn.execute(
        "INSERT INTO receipts(id, payment_id, number, created_at) VALUES (?,?,?,?)",
        (receipt_id, payment["id"], number, now()),
    )

    finance_id = payment["finance_id"]
    from .lifecycle import settle_finance_if_complete  # local import: avoids a cycle

    completion = settle_finance_if_complete(conn, actor, finance_id)
    audit(conn, actor, "payment.success", "payment_transaction", payment["id"],
          after={"emi_id": emi_id, "receipt": number, "gateway_txn_id": gateway_txn_id})
    return {
        "payment_id": payment["id"],
        "status": "SUCCESS",
        "emi_id": emi_id,
        "receipt_id": receipt_id,
        "receipt_number": number,
        "finance_completed": completion["completed"],
        "outstanding": completion["outstanding"],
    }


def handle_webhook(
    conn: sqlite3.Connection,
    raw_body: bytes,
    signature: str,
    secret: str,
    provider: str = "gateway",
) -> Dict[str, Any]:
    """The only authority on whether money actually arrived.

    Order of checks matters: signature first (so an unsigned body never gets
    parsed into a ledger write), then replay, then the amount.

    Raises for anything that must not be persisted at all (bad signature,
    unparseable body, unknown payment). Returns a ``REJECTED`` result for a
    well-formed event this system refuses to honour, so that the refusal and
    its audit row commit together.
    """
    if not verify_signature(secret, raw_body, signature):
        raise PaymentVerificationError("webhook signature mismatch")

    try:
        event = json.loads(raw_body.decode())
    except (ValueError, UnicodeDecodeError):
        raise PaymentVerificationError("webhook body is not valid JSON")

    event_id = event.get("event_id")
    if not event_id:
        raise PaymentVerificationError("webhook is missing event_id")

    try:
        conn.execute(
            "INSERT INTO webhook_events(event_id, provider, body_sha256, received_at)"
            " VALUES (?,?,?,?)",
            (event_id, provider, hashlib.sha256(raw_body).hexdigest(), now()),
        )
    except sqlite3.IntegrityError:
        raise ReplayedEvent("event %s already processed" % event_id)

    payment_id = event.get("payment_id")
    payment = conn.execute(
        "SELECT * FROM payment_transactions WHERE id = ?", (payment_id,)
    ).fetchone()
    if payment is None:
        raise PaymentVerificationError("unknown payment %s" % payment_id)

    status = (event.get("status") or "").upper()
    if status == "FAILED":
        conn.execute(
            "UPDATE payment_transactions SET status = 'FAILED', updated_at = ?"
            " WHERE id = ? AND status = 'INITIATED'",
            (now(), payment_id),
        )
        audit(conn, None, "payment.failed", "payment_transaction", payment_id,
              after={"event_id": event_id})
        return {"payment_id": payment_id, "status": "FAILED"}

    if status != "SUCCESS":
        raise PaymentVerificationError("unsupported webhook status %r" % status)

    amount = event.get("amount_paise")
    if not isinstance(amount, int) or amount != payment["amount_paise"]:
        # A gateway reporting a different figure than the one we priced is a
        # reconciliation incident, not a payment. It is returned rather than
        # raised on purpose: raising would roll the caller's transaction back
        # and take this audit row with it, and an incident nobody can see
        # afterwards is worse than the mismatch itself. The EMI stays unpaid.
        audit(conn, None, "payment.amount_mismatch", "payment_transaction", payment_id,
              before={"expected": payment["amount_paise"]}, after={"received": amount})
        return {
            "payment_id": payment_id,
            "status": "REJECTED",
            "reason": "amount mismatch: expected %s, webhook reported %s"
                      % (payment["amount_paise"], amount),
        }

    return _apply_success(conn, None, payment, event.get("gateway_txn_id"))


def record_cash_collection(
    conn: sqlite3.Connection,
    actor: Actor,
    finance_id: str,
    amount_paise: int,
    emi_id: Optional[str] = None,
    mode: str = "CASH",
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Offline collection by a retailer or collection staff (section 12)."""
    actor.require_role("SUPER_ADMIN", "DISTRIBUTOR", "RETAILER", "STAFF")
    from .core import replay_idempotent, remember_idempotent

    cached = replay_idempotent(conn, "collection.record", idempotency_key)
    if cached is not None:
        return cached

    fin = conn.execute("SELECT * FROM finance_accounts WHERE id = ?", (finance_id,)).fetchone()
    if fin is None:
        raise NotFound("finance %s" % finance_id)
    assert_can_touch_retailer(conn, actor, fin["retailer_id"])

    if emi_id is None:
        emi = _next_unpaid_emi(conn, finance_id)
        if emi is None:
            raise ValidationError("finance %s has no unpaid instalment" % finance_id)
        emi_id = emi["id"]
    emi_row = conn.execute("SELECT * FROM emi_schedules WHERE id = ?", (emi_id,)).fetchone()
    if emi_row is None:
        raise NotFound("emi %s" % emi_id)
    if emi_row["status"] == "PAID":
        raise ValidationError("instalment %s is already paid" % emi_id)
    if amount_paise != emi_row["amount_paise"]:
        raise ValidationError(
            "cash collection must match the instalment amount (%s)" % emi_row["amount_paise"]
        )

    pay_id = next_id(conn, "payment")
    conn.execute(
        "INSERT INTO payment_transactions(id, finance_id, emi_id, amount_paise, method,"
        " status, created_at, updated_at) VALUES (?,?,?,?,?, 'INITIATED', ?, ?)",
        (pay_id, finance_id, emi_id, amount_paise, mode, now(), now()),
    )
    payment = conn.execute(
        "SELECT * FROM payment_transactions WHERE id = ?", (pay_id,)
    ).fetchone()
    applied = _apply_success(conn, actor, payment, None)

    col_id = next_id(conn, "collection")
    conn.execute(
        "INSERT INTO collections(id, finance_id, emi_id, collected_by, payment_id,"
        " amount_paise, mode, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (col_id, finance_id, emi_id, actor.user_id, pay_id, amount_paise, mode, now()),
    )
    audit(conn, actor, "collection.record", "collection", col_id,
          after={"finance_id": finance_id, "emi_id": emi_id, "amount_paise": amount_paise})
    applied["collection_id"] = col_id
    if idempotency_key:
        remember_idempotent(conn, "collection.record", idempotency_key, applied)
    return applied


def receipt_for(conn: sqlite3.Connection, payment_id: str) -> Dict[str, Any]:
    row = conn.execute(
        "SELECT r.id, r.number, r.created_at, p.amount_paise, p.finance_id, p.emi_id, p.method"
        " FROM receipts r JOIN payment_transactions p ON p.id = r.payment_id"
        " WHERE r.payment_id = ?",
        (payment_id,),
    ).fetchone()
    if row is None:
        raise NotFound("receipt for payment %s" % payment_id)
    return dict(row)
