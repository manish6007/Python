"""EMI due/grace/overdue transitions, reminders and finance closure.

State model from section 8 of the blueprint:

    PENDING_ENROLLMENT -> ACTIVE -> PAYMENT_DUE -> GRACE_PERIOD
        -> OVERDUE -> RESTRICTED -> RESTORED -> COMPLETED
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
from typing import Any, Dict, List, Optional

from .core import Actor, audit, now, today
from .errors import NotFound

REMINDER_OFFSETS_DAYS = (7, 3, 1)


def run_daily_status_sweep(
    conn: sqlite3.Connection, actor: Optional[Actor] = None, as_of: Optional[_dt.date] = None
) -> Dict[str, List[str]]:
    """Advance every open instalment to the state its due date implies.

    Written to be idempotent: running it twice on the same day produces the
    same states and no duplicate side effects, which is what lets it be a
    plain cron job instead of a carefully-once-scheduled task.
    """
    as_of = as_of or today()
    moved: Dict[str, List[str]] = {"DUE": [], "GRACE_PERIOD": [], "OVERDUE": []}

    rows = conn.execute(
        "SELECT e.id, e.finance_id, e.due_date, e.status, f.grace_days"
        " FROM emi_schedules e JOIN finance_accounts f ON f.id = e.finance_id"
        " WHERE e.status IN ('UPCOMING','DUE','GRACE_PERIOD')"
        "   AND f.status IN ('ACTIVE','OVERDUE')",
    ).fetchall()

    for row in rows:
        due = _dt.date.fromisoformat(row["due_date"])
        grace_end = due + _dt.timedelta(days=row["grace_days"])
        if as_of > grace_end:
            target = "OVERDUE"
        elif as_of > due:
            target = "GRACE_PERIOD"
        elif as_of == due:
            target = "DUE"
        else:
            continue
        if target == row["status"]:
            continue
        conn.execute("UPDATE emi_schedules SET status = ? WHERE id = ?", (target, row["id"]))
        moved[target].append(row["id"])
        audit(conn, actor, "emi.status_change", "emi_schedule", row["id"],
              before={"status": row["status"]}, after={"status": target, "as_of": as_of.isoformat()})

    # Roll the finance and its device up to the worst state among instalments.
    for finance_id in {r["finance_id"] for r in rows}:
        _sync_account_state(conn, actor, finance_id)

    notices = issue_restriction_notices(conn, actor, as_of)
    moved["NOTICE_FIRST"] = notices["FIRST"]
    moved["NOTICE_SECOND"] = notices["SECOND"]
    return moved


def issue_restriction_notices(
    conn: sqlite3.Connection, actor: Optional[Actor] = None, as_of: Optional[_dt.date] = None
) -> Dict[str, List[str]]:
    """Raise the two notices a restriction must wait out (RBI draft, May 2026).

    First notice once the oldest unpaid instalment is 60 days past due, giving
    21 days to pay. Second notice only after that runs out, giving 7 more.
    Idempotent like the rest of the sweep: one notice of each kind per
    instalment, ever. Delivery (SMS, WhatsApp, push) is a separate worker that
    stamps ``delivered_at``.
    """
    from .devices import oldest_overdue
    from .settings_store import get_setting

    as_of = as_of or today()
    first_at = get_setting(conn, "restriction.first_notice_days_past_due")
    first_window = get_setting(conn, "restriction.first_notice_window_days")
    second_window = get_setting(conn, "restriction.second_notice_window_days")
    issued: Dict[str, List[str]] = {"FIRST": [], "SECOND": []}

    finances = conn.execute(
        "SELECT DISTINCT f.id FROM finance_accounts f JOIN emi_schedules e"
        " ON e.finance_id = f.id WHERE e.status = 'OVERDUE'"
        " AND f.status NOT IN ('COMPLETED','CANCELLED')",
    ).fetchall()
    for fin in finances:
        anchor = oldest_overdue(conn, fin["id"])
        days_past_due = (as_of - _dt.date.fromisoformat(anchor["due_date"])).days
        existing = {
            r["kind"]: r for r in conn.execute(
                "SELECT kind, pay_by FROM restriction_notices WHERE emi_id = ?",
                (anchor["id"],))
        }
        if "FIRST" not in existing:
            if days_past_due >= first_at:
                issued["FIRST"].append(
                    _issue_notice(conn, actor, fin["id"], anchor["id"], "FIRST",
                                  days_past_due, as_of, first_window))
        elif "SECOND" not in existing:
            if as_of > _dt.date.fromisoformat(existing["FIRST"]["pay_by"]):
                issued["SECOND"].append(
                    _issue_notice(conn, actor, fin["id"], anchor["id"], "SECOND",
                                  days_past_due, as_of, second_window))
    return issued


def _issue_notice(
    conn: sqlite3.Connection, actor: Optional[Actor], finance_id: str, emi_id: str,
    kind: str, days_past_due: int, as_of: _dt.date, window_days: int,
) -> str:
    from .core import next_id

    notice_id = next_id(conn, "notice")
    pay_by = (as_of + _dt.timedelta(days=window_days)).isoformat()
    conn.execute(
        "INSERT INTO restriction_notices(id, finance_id, emi_id, kind, days_past_due,"
        " issued_on, pay_by, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (notice_id, finance_id, emi_id, kind, days_past_due, as_of.isoformat(), pay_by, now()),
    )
    audit(conn, actor, "finance.restriction_notice", "restriction_notice", notice_id,
          after={"finance_id": finance_id, "kind": kind, "days_past_due": days_past_due,
                 "pay_by": pay_by})
    return notice_id


def _sync_account_state(
    conn: sqlite3.Connection, actor: Optional[Actor], finance_id: str
) -> None:
    worst = conn.execute(
        "SELECT status FROM emi_schedules WHERE finance_id = ? AND status IN"
        " ('OVERDUE','GRACE_PERIOD','DUE') ORDER BY CASE status"
        " WHEN 'OVERDUE' THEN 0 WHEN 'GRACE_PERIOD' THEN 1 ELSE 2 END LIMIT 1",
        (finance_id,),
    ).fetchone()
    fin = conn.execute(
        "SELECT status, device_id FROM finance_accounts WHERE id = ?", (finance_id,)
    ).fetchone()
    if fin is None or fin["status"] in ("COMPLETED", "CANCELLED"):
        return

    account_status = "OVERDUE" if worst and worst["status"] == "OVERDUE" else "ACTIVE"
    if account_status != fin["status"]:
        conn.execute(
            "UPDATE finance_accounts SET status = ? WHERE id = ?", (account_status, finance_id)
        )
        audit(conn, actor, "finance.status_change", "finance_account", finance_id,
              before={"status": fin["status"]}, after={"status": account_status})

    if fin["device_id"]:
        device_status = {
            "OVERDUE": "OVERDUE",
            "GRACE_PERIOD": "GRACE_PERIOD",
            "DUE": "PAYMENT_DUE",
        }.get(worst["status"] if worst else None, "ACTIVE")
        current = conn.execute(
            "SELECT status FROM devices WHERE id = ?", (fin["device_id"],)
        ).fetchone()["status"]
        # Never quietly downgrade a device an operator explicitly restricted.
        if current not in ("RESTRICTED", "COMPLETED", "CANCELLED") and current != device_status:
            conn.execute(
                "UPDATE devices SET status = ? WHERE id = ?", (device_status, fin["device_id"])
            )
            audit(conn, actor, "device.status_change", "device", fin["device_id"],
                  before={"status": current}, after={"status": device_status})


def due_reminders(
    conn: sqlite3.Connection, as_of: Optional[_dt.date] = None
) -> List[Dict[str, Any]]:
    """Section 9: 7 / 3 / 1 days before, plus the due-date notice."""
    as_of = as_of or today()
    wanted = {
        (as_of + _dt.timedelta(days=d)).isoformat(): "T-%d" % d for d in REMINDER_OFFSETS_DAYS
    }
    wanted[as_of.isoformat()] = "DUE_TODAY"
    rows = conn.execute(
        "SELECT e.id, e.finance_id, e.seq, e.amount_paise, e.due_date, c.mobile, c.name"
        " FROM emi_schedules e"
        " JOIN finance_accounts f ON f.id = e.finance_id"
        " JOIN customers c ON c.id = f.customer_id"
        " WHERE e.status IN ('UPCOMING','DUE') AND e.due_date IN (%s)"
        % ",".join("?" * len(wanted)),
        tuple(wanted.keys()),
    ).fetchall()
    return [dict(r, kind=wanted[r["due_date"]]) for r in rows]


def overdue_report(conn: sqlite3.Connection, as_of: Optional[_dt.date] = None):
    as_of = as_of or today()
    rows = conn.execute(
        "SELECT f.id finance_id, f.retailer_id, f.customer_id, f.device_id,"
        " COUNT(e.id) overdue_count, SUM(e.amount_paise) overdue_amount,"
        " MIN(e.due_date) oldest_due"
        " FROM finance_accounts f JOIN emi_schedules e ON e.finance_id = f.id"
        " WHERE e.status = 'OVERDUE' GROUP BY f.id ORDER BY oldest_due",
    ).fetchall()
    out = []
    for r in rows:
        days = (as_of - _dt.date.fromisoformat(r["oldest_due"])).days
        out.append(dict(r, days_past_due=days))
    return out


def settle_finance_if_complete(
    conn: sqlite3.Connection, actor: Optional[Actor], finance_id: str
) -> Dict[str, Any]:
    """Close the account once nothing is outstanding (section 15)."""
    remaining = conn.execute(
        "SELECT COALESCE(SUM(amount_paise), 0) due FROM emi_schedules"
        " WHERE finance_id = ? AND status NOT IN ('PAID','WAIVED')",
        (finance_id,),
    ).fetchone()["due"]
    if remaining > 0:
        _sync_account_state(conn, actor, finance_id)
        return {"completed": False, "outstanding": remaining}

    fin = conn.execute(
        "SELECT status, device_id FROM finance_accounts WHERE id = ?", (finance_id,)
    ).fetchone()
    if fin is None:
        raise NotFound("finance %s" % finance_id)
    if fin["status"] == "COMPLETED":
        return {"completed": True, "outstanding": 0}

    conn.execute(
        "UPDATE finance_accounts SET status = 'COMPLETED' WHERE id = ?", (finance_id,)
    )
    if fin["device_id"]:
        # Closure must lift any restriction; an unlock request is queued for
        # the device-management provider rather than assumed to have happened.
        prior = conn.execute(
            "SELECT status FROM devices WHERE id = ?", (fin["device_id"],)
        ).fetchone()["status"]
        conn.execute(
            "UPDATE devices SET status = 'COMPLETED' WHERE id = ?", (fin["device_id"],)
        )
        if prior == "RESTRICTED":
            from .devices import open_unlock_obligation, request_command

            cmd = request_command(conn, actor, fin["device_id"], "RELEASE",
                                  reason="finance completed", auto_approve=True)
            open_unlock_obligation(conn, cmd["command_id"])
    audit(conn, actor, "finance.completed", "finance_account", finance_id,
          before={"status": fin["status"]}, after={"status": "COMPLETED"})
    return {"completed": True, "outstanding": 0}


def closure_certificate(conn: sqlite3.Connection, finance_id: str) -> Dict[str, Any]:
    fin = conn.execute(
        "SELECT f.*, c.name customer_name, c.mobile customer_mobile, d.imei"
        " FROM finance_accounts f JOIN customers c ON c.id = f.customer_id"
        " LEFT JOIN devices d ON d.id = f.device_id WHERE f.id = ?",
        (finance_id,),
    ).fetchone()
    if fin is None:
        raise NotFound("finance %s" % finance_id)
    paid = conn.execute(
        "SELECT COALESCE(SUM(amount_paise), 0) p FROM payment_transactions"
        " WHERE finance_id = ? AND status = 'SUCCESS'",
        (finance_id,),
    ).fetchone()["p"]
    return {
        "finance_id": finance_id,
        "customer": fin["customer_name"],
        "mobile": fin["customer_mobile"],
        "imei": fin["imei"],
        "financed_amount": fin["principal"],
        "total_collected": paid,
        "status": fin["status"],
        "no_dues": fin["status"] == "COMPLETED",
        "issued_at": now(),
    }
