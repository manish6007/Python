"""Access checks that span both app audiences.

The core's ``assert_can_touch_retailer`` answers "may this staff member act on
this retailer's book?". The customer app needs the other question: "is this
finance mine?". A customer has no retailer scope at all, so without this they
would be denied access to their own EMI schedule.
"""
from __future__ import annotations

import sqlite3

from emi_locker.core import Actor, assert_can_touch_retailer
from emi_locker.errors import NotFound, PermissionDenied


def finance_row(conn: sqlite3.Connection, finance_id: str):
    row = conn.execute(
        "SELECT f.*, c.user_id customer_user_id FROM finance_accounts f"
        " JOIN customers c ON c.id = f.customer_id WHERE f.id = ?",
        (finance_id,),
    ).fetchone()
    if row is None:
        raise NotFound("finance %s" % finance_id)
    return row


def assert_can_view_finance(conn: sqlite3.Connection, actor: Actor, finance_id: str):
    """Customers see their own accounts; everyone else goes by retailer scope."""
    row = finance_row(conn, finance_id)
    if actor.role == "CUSTOMER":
        if row["customer_user_id"] != actor.user_id:
            raise PermissionDenied("this finance account does not belong to you")
        return row
    assert_can_touch_retailer(conn, actor, row["retailer_id"])
    return row


def assert_can_pay_finance(conn: sqlite3.Connection, actor: Actor, finance_id: str):
    """Paying is viewing plus the rule that only the borrower pays online."""
    row = assert_can_view_finance(conn, actor, finance_id)
    if row["status"] in ("COMPLETED", "CANCELLED"):
        raise PermissionDenied("this finance account is %s" % row["status"].lower())
    return row


def own_customer_id(conn: sqlite3.Connection, actor: Actor) -> str:
    row = conn.execute(
        "SELECT id FROM customers WHERE user_id = ?", (actor.user_id,)
    ).fetchone()
    if row is None:
        raise PermissionDenied("this account is not linked to a customer record")
    return row["id"]
