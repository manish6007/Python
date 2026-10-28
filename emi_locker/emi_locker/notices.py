"""Getting restriction notices to the customer.

``lifecycle.issue_restriction_notices`` decides that a notice is due. This
module delivers it and records that it arrived. The distinction matters
legally: a notice the customer never received gave them no chance to pay, so
it does not count towards a restriction, and the time it gives runs from the
day it was delivered, not the day it was written.

The channel is passed in, so this works with any of the backend's message
channels (console, MSG91, WhatsApp, a generic HTTP provider) and with a fake
in tests. A channel needs one method::

    send_notice(mobile, text, variables) -> {"delivered": bool, "channel": str, ...}

and raises on failure. ``variables`` carries the same values as ``text`` for
providers that fill a registered template themselves (DLT in India requires
the text to match a registered template exactly).
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
from typing import Any, Dict, List, Optional

from .core import Actor, audit, format_inr, today
from .settings_store import get_setting

# Draft wording. The final text must come from the lawyer and be registered
# as a DLT template character for character before MSG91 will send it.
TEMPLATES = {
    "FIRST": (
        "{business}: Your EMI of {amount} for {model} is {days} days overdue. "
        "Please pay by {pay_by} to avoid restriction of some phone features. "
        "Calls, internet and SOS will keep working. Pay in the EMI Locker app "
        "or at {retailer}."
    ),
    "SECOND": (
        "{business}: FINAL NOTICE. Your EMI of {amount} for {model} is {days} "
        "days overdue. If unpaid by {pay_by}, some phone features may be "
        "restricted. Calls, internet and SOS will keep working. Pay in the EMI "
        "Locker app or at {retailer}."
    ),
}

_WINDOW_SETTING = {
    "FIRST": "restriction.first_notice_window_days",
    "SECOND": "restriction.second_notice_window_days",
}


def _pending(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT n.*, c.mobile, c.name customer_name, d.model, u.name retailer_name,"
        " e.status emi_status,"
        " (SELECT COALESCE(SUM(x.amount_paise),0) FROM emi_schedules x"
        "   WHERE x.finance_id = n.finance_id AND x.status = 'OVERDUE') overdue_paise"
        " FROM restriction_notices n"
        " JOIN finance_accounts f ON f.id = n.finance_id"
        " JOIN customers c ON c.id = f.customer_id"
        " JOIN users u ON u.id = f.retailer_id"
        " JOIN emi_schedules e ON e.id = n.emi_id"
        " LEFT JOIN devices d ON d.id = f.device_id"
        " WHERE n.delivered_at IS NULL AND COALESCE(n.delivery_channel, '') != 'skipped'"
        " ORDER BY n.created_at",
    ).fetchall()


def deliver_pending_notices(
    conn: sqlite3.Connection,
    channel: Any,
    actor: Optional[Actor] = None,
    as_of: Optional[_dt.date] = None,
    business: str = "EMI Locker",
) -> Dict[str, List[str]]:
    """Send every notice not yet delivered. Safe to run as often as you like.

    A failed send is recorded and retried on the next run. A notice whose
    instalment was paid before it went out is skipped, not sent: telling a
    customer who has paid that their phone may be restricted is wrong.
    """
    as_of = as_of or today()
    result: Dict[str, List[str]] = {"delivered": [], "failed": [], "skipped": []}
    for row in _pending(conn):
        if row["emi_status"] != "OVERDUE":
            conn.execute(
                "UPDATE restriction_notices SET delivery_channel = 'skipped',"
                " delivery_error = 'instalment paid before delivery' WHERE id = ?",
                (row["id"],))
            result["skipped"].append(row["id"])
            continue

        # The customer gets the full window from the day it reaches them.
        window = get_setting(conn, _WINDOW_SETTING[row["kind"]])
        pay_by = max(row["pay_by"], (as_of + _dt.timedelta(days=window)).isoformat())
        variables = {
            "business": business,
            "amount": format_inr(row["overdue_paise"]),
            "model": row["model"] or "your phone",
            "days": row["days_past_due"],
            "pay_by": _dt.date.fromisoformat(pay_by).strftime("%d %b %Y"),
            "retailer": row["retailer_name"],
        }
        text = TEMPLATES[row["kind"]].format(**variables)
        try:
            sent = channel.send_notice(row["mobile"], text, variables)
        except Exception as exc:  # any provider failure: record it, retry next run
            conn.execute(
                "UPDATE restriction_notices SET delivery_error = ? WHERE id = ?",
                (str(exc)[:300], row["id"]))
            result["failed"].append(row["id"])
            continue

        conn.execute(
            "UPDATE restriction_notices SET delivered_at = ?, delivery_channel = ?,"
            " delivery_error = NULL, pay_by = ? WHERE id = ?",
            (as_of.isoformat(), sent.get("channel", "unknown"), pay_by, row["id"]))
        audit(conn, actor, "finance.restriction_notice_delivered", "restriction_notice",
              row["id"], after={"kind": row["kind"], "channel": sent.get("channel"),
                                "pay_by": pay_by})
        result["delivered"].append(row["id"])
    return result


def active_notice(conn: sqlite3.Connection, finance_id: str) -> Optional[Dict[str, Any]]:
    """The latest delivered notice for the default the customer is in now."""
    from .devices import oldest_overdue

    anchor = oldest_overdue(conn, finance_id)
    if anchor is None:
        return None
    row = conn.execute(
        "SELECT kind, issued_on, delivered_at, pay_by, days_past_due"
        " FROM restriction_notices WHERE emi_id = ? AND delivered_at IS NOT NULL"
        " ORDER BY CASE kind WHEN 'SECOND' THEN 0 ELSE 1 END LIMIT 1",
        (anchor["id"],),
    ).fetchone()
    if row is None:
        return None
    overdue = conn.execute(
        "SELECT COALESCE(SUM(amount_paise),0) s FROM emi_schedules"
        " WHERE finance_id = ? AND status = 'OVERDUE'", (finance_id,)).fetchone()["s"]
    return dict(row, overdue_paise=overdue)
