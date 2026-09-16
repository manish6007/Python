"""Customers, devices, finance accounts and EMI schedules."""
from __future__ import annotations

import calendar
import datetime as _dt
import json
import sqlite3
from typing import Any, Dict, List, Optional

from . import licensing
from .core import (
    Actor,
    assert_can_touch_retailer,
    audit,
    next_id,
    now,
    replay_idempotent,
    remember_idempotent,
    today,
)
from .errors import DuplicateDevice, NotFound, PermissionDenied, ValidationError

IMEI_LEN = 15
REQUIRED_CONSENTS = ("TERMS", "PRIVACY", "DEVICE_MANAGEMENT")


def valid_imei(imei: str) -> bool:
    """Length + Luhn check digit, the same validation a handset uses."""
    if not imei.isdigit() or len(imei) != IMEI_LEN:
        return False
    total = 0
    for idx, ch in enumerate(reversed(imei)):
        digit = int(ch)
        if idx % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def add_month(date: _dt.date, months: int) -> _dt.date:
    """Add months, clamping the day to the end of the target month.

    A finance started on the 31st must not silently skip February.
    """
    month_index = date.month - 1 + months
    year = date.year + month_index // 12
    month = month_index % 12 + 1
    day = min(date.day, calendar.monthrange(year, month)[1])
    return _dt.date(year, month, day)


def build_schedule(principal_paise: int, tenure: int, start: _dt.date,
                   first_due_offset_months: int = 1) -> List[Dict[str, Any]]:
    """Split the financed amount into whole-rupee instalments.

    The remainder from the division lands on the final instalment so that the
    sum of the schedule equals the principal to the paise. Rounding leftovers
    that vanish are how ledgers end up with phantom dues.
    """
    if tenure <= 0:
        raise ValidationError("tenure must be positive")
    if principal_paise <= 0:
        raise ValidationError("financed amount must be positive")

    base = (principal_paise // tenure // 100) * 100  # round down to whole rupees
    if base <= 0:
        base = principal_paise // tenure
    rows = []
    allocated = 0
    for seq in range(1, tenure + 1):
        amount = base if seq < tenure else principal_paise - allocated
        allocated += amount
        rows.append({
            "seq": seq,
            "amount_paise": amount,
            "due_date": add_month(start, seq - 1 + first_due_offset_months),
        })
    assert sum(r["amount_paise"] for r in rows) == principal_paise
    return rows


def create_customer(
    conn: sqlite3.Connection,
    actor: Actor,
    retailer_id: str,
    name: str,
    mobile: str,
    address: Optional[str] = None,
) -> str:
    actor.require_role("SUPER_ADMIN", "DISTRIBUTOR", "RETAILER", "STAFF")
    assert_can_touch_retailer(conn, actor, retailer_id)
    if not mobile or not mobile.isdigit() or len(mobile) < 10:
        raise ValidationError("a valid mobile number is required")
    if conn.execute("SELECT 1 FROM users WHERE mobile = ?", (mobile,)).fetchone():
        raise ValidationError("mobile %s is already registered" % mobile)

    cid = next_id(conn, "customer")
    # Every customer gets a login identity of their own: the customer app
    # authenticates against users, and a customer with no user row could never
    # sign in to see their own schedule.
    from .core import create_user

    user_id = create_user(conn, "CUSTOMER", name, mobile=mobile, actor=actor)
    conn.execute(
        "INSERT INTO customers(id, retailer_id, user_id, name, mobile, address,"
        " kyc_status, created_at) VALUES (?,?,?,?,?,?, 'PENDING', ?)",
        (cid, retailer_id, user_id, name, mobile, address, now()),
    )
    audit(conn, actor, "customer.create", "customer", cid,
          after={"retailer_id": retailer_id, "name": name, "user_id": user_id})
    return cid


def record_consent(
    conn: sqlite3.Connection,
    actor: Actor,
    customer_id: str,
    consent_type: str,
    doc_version: str,
    channel: str = "APP",
    meta: Optional[Dict[str, Any]] = None,
) -> str:
    if consent_type not in REQUIRED_CONSENTS:
        raise ValidationError("unknown consent type %s" % consent_type)
    cid = next_id(conn, "consent")
    conn.execute(
        "INSERT INTO customer_consents(id, customer_id, consent_type, doc_version,"
        " accepted_at, channel, meta_json) VALUES (?,?,?,?,?,?,?)",
        (cid, customer_id, consent_type, doc_version, now(), channel,
         json.dumps(meta or {})),
    )
    audit(conn, actor, "customer.consent", "customer_consent", cid,
          after={"customer_id": customer_id, "type": consent_type, "version": doc_version})
    return cid


def missing_consents(conn: sqlite3.Connection, customer_id: str) -> List[str]:
    rows = conn.execute(
        "SELECT DISTINCT consent_type FROM customer_consents WHERE customer_id = ?",
        (customer_id,),
    ).fetchall()
    have = {r["consent_type"] for r in rows}
    return [c for c in REQUIRED_CONSENTS if c not in have]


def create_finance(
    conn: sqlite3.Connection,
    actor: Actor,
    customer_id: str,
    imei: str,
    product_price: int,
    down_payment: int,
    tenure_months: int,
    model: Optional[str] = None,
    start_date: Optional[_dt.date] = None,
    late_fee_paise: int = 0,
    grace_days: int = 5,
    agreement_version: str = "v1",
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Register device, price the finance, burn one activation, build the schedule.

    Everything here runs in the caller's single transaction: if the IMEI turns
    out to be taken, or the retailer is out of activations, nothing is left
    behind - no orphan device row, no leaked quota unit.
    """
    actor.require_role("SUPER_ADMIN", "DISTRIBUTOR", "RETAILER", "STAFF")

    cached = replay_idempotent(conn, "finance.create", idempotency_key)
    if cached is not None:
        return cached

    customer = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if customer is None:
        raise NotFound("customer %s" % customer_id)
    retailer_id = customer["retailer_id"]
    assert_can_touch_retailer(conn, actor, retailer_id)

    pending = missing_consents(conn, customer_id)
    if pending:
        raise PermissionDenied(
            "cannot activate finance before consent is captured: %s" % ", ".join(pending)
        )
    if not valid_imei(imei):
        raise ValidationError("IMEI %s failed format/checksum validation" % imei)
    if down_payment >= product_price:
        raise ValidationError("down payment must be less than the product price")
    if down_payment < 0:
        raise ValidationError("down payment cannot be negative")

    clash = conn.execute(
        "SELECT id, status FROM devices WHERE imei = ? AND status NOT IN ('COMPLETED','CANCELLED')",
        (imei,),
    ).fetchone()
    if clash is not None:
        raise DuplicateDevice(
            "IMEI %s is already on live finance (device %s, %s)"
            % (imei, clash["id"], clash["status"])
        )

    principal = product_price - down_payment
    start = start_date or today()
    schedule = build_schedule(principal, tenure_months, start)

    device_id = next_id(conn, "device")
    finance_id = next_id(conn, "finance")
    conn.execute(
        "INSERT INTO devices(id, imei, model, customer_id, finance_id, status, created_at)"
        " VALUES (?,?,?,?,?, 'PENDING_ENROLLMENT', ?)",
        (device_id, imei, model, customer_id, finance_id, now()),
    )
    conn.execute(
        "INSERT INTO finance_accounts(id, customer_id, retailer_id, device_id, product_price,"
        " down_payment, principal, tenure_months, emi_amount, late_fee_paise, grace_days,"
        " status, start_date, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?, 'DRAFT', ?, ?)",
        (finance_id, customer_id, retailer_id, device_id, product_price, down_payment,
         principal, tenure_months, schedule[0]["amount_paise"], late_fee_paise, grace_days,
         start.isoformat(), now()),
    )
    for row in schedule:
        conn.execute(
            "INSERT INTO emi_schedules(id, finance_id, seq, amount_paise, due_date, status)"
            " VALUES (?,?,?,?,?, 'UPCOMING')",
            (next_id(conn, "emi"), finance_id, row["seq"], row["amount_paise"],
             row["due_date"].isoformat()),
        )

    activation = licensing.consume_activation(
        conn, actor, owner_id=retailer_id, finance_id=finance_id, device_id=device_id,
        idempotency_key=("fin:%s" % finance_id),
    )

    agreement_id = next_id(conn, "agreement")
    terms = {
        "product_price": product_price,
        "down_payment": down_payment,
        "financed_amount": principal,
        "tenure_months": tenure_months,
        "emi_amount": schedule[0]["amount_paise"],
        "final_emi_amount": schedule[-1]["amount_paise"],
        "total_payable": principal,
        "late_fee_paise": late_fee_paise,
        "grace_days": grace_days,
        "first_due_date": schedule[0]["due_date"].isoformat(),
    }
    conn.execute(
        "INSERT INTO finance_agreements(id, finance_id, doc_version, terms_json, accepted_at,"
        " accepted_by, meta_json) VALUES (?,?,?,?,?,?,?)",
        (agreement_id, finance_id, agreement_version, json.dumps(terms), now(), customer_id,
         json.dumps({"captured_by": actor.user_id})),
    )
    conn.execute(
        "UPDATE finance_accounts SET status = 'ACTIVE' WHERE id = ?", (finance_id,)
    )
    conn.execute("UPDATE devices SET status = 'ACTIVE' WHERE id = ?", (device_id,))
    audit(conn, actor, "finance.create", "finance_account", finance_id,
          after={"customer_id": customer_id, "device_id": device_id, "principal": principal,
                 "tenure": tenure_months, "activation_id": activation["activation_id"]})

    result = {
        "finance_id": finance_id,
        "device_id": device_id,
        "agreement_id": agreement_id,
        "principal": principal,
        "emi_amount": schedule[0]["amount_paise"],
        "tenure_months": tenure_months,
        "activation": activation,
        "schedule": [
            {"seq": r["seq"], "amount_paise": r["amount_paise"],
             "due_date": r["due_date"].isoformat()}
            for r in schedule
        ],
    }
    if idempotency_key:
        remember_idempotent(conn, "finance.create", idempotency_key, result)
    return result


def get_schedule(conn: sqlite3.Connection, finance_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, seq, amount_paise, due_date, status, paid_at FROM emi_schedules"
        " WHERE finance_id = ? ORDER BY seq",
        (finance_id,),
    ).fetchall()
    if not rows:
        raise NotFound("schedule for %s" % finance_id)
    return [dict(r) for r in rows]


def outstanding(conn: sqlite3.Connection, finance_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_paise), 0) due FROM emi_schedules"
        " WHERE finance_id = ? AND status != 'PAID' AND status != 'WAIVED'",
        (finance_id,),
    ).fetchone()
    return row["due"]


def finance_summary(conn: sqlite3.Connection, actor: Actor, finance_id: str) -> Dict[str, Any]:
    fin = conn.execute("SELECT * FROM finance_accounts WHERE id = ?", (finance_id,)).fetchone()
    if fin is None:
        raise NotFound("finance %s" % finance_id)
    assert_can_touch_retailer(conn, actor, fin["retailer_id"])
    paid = conn.execute(
        "SELECT COALESCE(SUM(amount_paise), 0) p FROM emi_schedules"
        " WHERE finance_id = ? AND status = 'PAID'",
        (finance_id,),
    ).fetchone()["p"]
    return {
        "finance_id": finance_id,
        "customer_id": fin["customer_id"],
        "retailer_id": fin["retailer_id"],
        "device_id": fin["device_id"],
        "status": fin["status"],
        "principal": fin["principal"],
        "paid": paid,
        "outstanding": outstanding(conn, finance_id),
        "tenure_months": fin["tenure_months"],
        "emi_amount": fin["emi_amount"],
    }
