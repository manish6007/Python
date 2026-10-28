"""Device-management command queue.

Scope boundary, stated plainly because it decides the project plan:

This module records *intent* - who asked for a device action, why, who
approved it, what was sent and what came back. It does not lock phones and
cannot. On Android, restricting a device is performed by a Device Policy
Controller running in Device Owner mode, provisioned at setup time (QR /
zero-touch / EMM token) and driven through the Android Management API or an
EMM provider. An ordinary app installed from the Play Store has no such
capability, and the blueprint says the same in section 8.

So ``send_to_provider`` takes an adapter. ``NullProvider`` is the default and
records that no provider is wired up; a real deployment supplies an adapter
backed by whichever authorised EMM the business contracts with.

Restriction timing follows the RBI draft amendment of May 2026 (Commercial
Banks - Responsible Business Conduct): no restriction before 90 days past due,
and only after two notices have each run out; the phone keeps incoming calls,
internet, emergency SOS and government alerts; and it is unlocked within an
hour of the arrears being paid, or the customer is owed compensation. The
numbers live in settings_store with those values as hard floors.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
from typing import Any, Dict, List, Optional, Protocol

from .core import Actor, audit, next_id, now, today
from .errors import NotFound, PermissionDenied, ValidationError
from .settings_store import get_setting

RESTRICTIVE = ("RESTRICT",)
UNLOCKING = ("RESTORE", "RELEASE")

# Sent with every RESTRICT. A provider adapter must map this to its own
# partial-lock policy and refuse a full lock: these keep working regardless.
RESTRICTION_PROFILE = {
    "mode": "PARTIAL",
    "keep_working": ["incoming_calls", "internet", "emergency_sos", "government_alerts",
                     "emi_payment_app"],
    "read_device_data": False,
}


class DeviceProvider(Protocol):  # pragma: no cover - interface only
    name: str

    def send(self, device_imei: str, command: str, context: Dict[str, Any]) -> Dict[str, Any]:
        ...


class NullProvider:
    """Default adapter: queues the command and reports that nothing was sent."""

    name = "none"

    def send(self, device_imei: str, command: str, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "delivered": False,
            "provider_ref": None,
            "detail": "no device-management provider configured",
        }


def _log(conn: sqlite3.Connection, command_id: str, event: str, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO device_command_logs(command_id, event, detail, created_at) VALUES (?,?,?,?)",
        (command_id, event, detail, now()),
    )


def oldest_overdue(conn: sqlite3.Connection, finance_id: str) -> Optional[sqlite3.Row]:
    """The instalment that days-past-due and the notices are counted from."""
    return conn.execute(
        "SELECT id, due_date FROM emi_schedules WHERE finance_id = ? AND status = 'OVERDUE'"
        " ORDER BY due_date, seq LIMIT 1",
        (finance_id,),
    ).fetchone()


def eligibility_for_restriction(
    conn: sqlite3.Connection, device_id: str, as_of: Optional[_dt.date] = None
) -> Dict[str, Any]:
    """May this phone be restricted today? Every rule must pass, in this order.

    Checked when a restriction is requested and again just before it is sent,
    so nobody - retailer, admin or a queued job - can restrict early.
    """
    as_of = as_of or today()
    row = conn.execute(
        "SELECT f.id finance_id, f.customer_id,"
        " (SELECT COUNT(*) FROM emi_schedules e WHERE e.finance_id = f.id"
        "   AND e.status = 'OVERDUE') overdue_count,"
        " (SELECT COALESCE(SUM(amount_paise),0) FROM emi_schedules e WHERE e.finance_id = f.id"
        "   AND e.status NOT IN ('PAID','WAIVED')) outstanding"
        " FROM finance_accounts f WHERE f.device_id = ?"
        " AND f.status NOT IN ('COMPLETED','CANCELLED')",
        (device_id,),
    ).fetchone()
    if row is None:
        return {"eligible": False, "reason": "no open finance for this device"}
    if row["overdue_count"] <= 0:
        return {"eligible": False, "reason": "no instalment is past its grace period"}
    if row["outstanding"] <= 0:
        return {"eligible": False, "reason": "nothing outstanding"}

    consented = conn.execute(
        "SELECT 1 FROM customer_consents WHERE customer_id = ?"
        " AND consent_type = 'DEVICE_MANAGEMENT' LIMIT 1",
        (row["customer_id"],),
    ).fetchone()
    if consented is None:
        return {"eligible": False,
                "reason": "the customer has no recorded consent to device management"}

    anchor = oldest_overdue(conn, row["finance_id"])
    days_past_due = (as_of - _dt.date.fromisoformat(anchor["due_date"])).days
    min_days = get_setting(conn, "restriction.min_days_past_due")
    if days_past_due < min_days:
        return {"eligible": False,
                "reason": "only %d days past due; restriction needs %d"
                          % (days_past_due, min_days)}

    second = conn.execute(
        "SELECT pay_by, delivered_at FROM restriction_notices"
        " WHERE emi_id = ? AND kind = 'SECOND'",
        (anchor["id"],),
    ).fetchone()
    if second is None:
        return {"eligible": False, "reason": "the second notice has not been issued"}
    if second["delivered_at"] is None:
        return {"eligible": False,
                "reason": "the second notice has not reached the customer yet"}
    if as_of <= _dt.date.fromisoformat(second["pay_by"]):
        return {"eligible": False,
                "reason": "the second notice gives the customer until %s to pay"
                          % second["pay_by"]}

    return {
        "eligible": True,
        "finance_id": row["finance_id"],
        "overdue_count": row["overdue_count"],
        "outstanding": row["outstanding"],
        "days_past_due": days_past_due,
    }


def request_command(
    conn: sqlite3.Connection,
    actor: Optional[Actor],
    device_id: str,
    command: str,
    reason: str,
    auto_approve: bool = False,
    as_of: Optional[_dt.date] = None,
) -> Dict[str, Any]:
    """Raise a device action. Restrictive actions need a separate approver."""
    if command not in ("ENROLL", "REMIND", "RESTRICT", "RESTORE", "RELEASE"):
        raise ValidationError("unknown command %s" % command)
    device = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if device is None:
        raise NotFound("device %s" % device_id)
    if not reason:
        raise ValidationError("a reason is required for every device action")

    if command in RESTRICTIVE:
        check = eligibility_for_restriction(conn, device_id, as_of)
        if not check["eligible"]:
            raise PermissionDenied("device not eligible for restriction: %s" % check["reason"])

    cmd_id = next_id(conn, "command")
    status = "APPROVED" if auto_approve or command not in RESTRICTIVE else "PENDING_APPROVAL"
    conn.execute(
        "INSERT INTO device_commands(id, device_id, command, reason, requested_by, approved_by,"
        " status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (cmd_id, device_id, command, reason,
         actor.user_id if actor else None,
         actor.user_id if (auto_approve and actor) else None,
         status, now(), now()),
    )
    _log(conn, cmd_id, "requested", reason)
    audit(conn, actor, "device.command_request", "device_command", cmd_id,
          after={"device_id": device_id, "command": command, "status": status, "reason": reason})
    return {"command_id": cmd_id, "status": status, "command": command}


def approve_command(conn: sqlite3.Connection, actor: Actor, command_id: str) -> Dict[str, Any]:
    """Four-eyes rule: the requester cannot approve their own restriction."""
    actor.require_role("SUPER_ADMIN")
    cmd = conn.execute(
        "SELECT * FROM device_commands WHERE id = ?", (command_id,)
    ).fetchone()
    if cmd is None:
        raise NotFound("command %s" % command_id)
    if cmd["status"] != "PENDING_APPROVAL":
        raise ValidationError("command %s is %s" % (command_id, cmd["status"]))
    if cmd["requested_by"] is not None and cmd["requested_by"] == actor.user_id:
        raise PermissionDenied(
            "a restriction must be approved by someone other than its requester")
    conn.execute(
        "UPDATE device_commands SET status = 'APPROVED', approved_by = ?, updated_at = ?"
        " WHERE id = ?",
        (actor.user_id, now(), command_id),
    )
    _log(conn, command_id, "approved", actor.user_id)
    audit(conn, actor, "device.command_approve", "device_command", command_id,
          before={"status": "PENDING_APPROVAL"}, after={"status": "APPROVED"})
    return {"command_id": command_id, "status": "APPROVED"}


def send_to_provider(
    conn: sqlite3.Connection,
    actor: Optional[Actor],
    command_id: str,
    provider: Optional[DeviceProvider] = None,
    as_of: Optional[_dt.date] = None,
    at: Optional[_dt.datetime] = None,
) -> Dict[str, Any]:
    """Dispatch an approved command and record the provider's answer.

    ``at`` is when the provider confirmed; it times an unlock against the
    one-hour limit. Tests pass it; in service it is the current time.
    """
    provider = provider or NullProvider()
    cmd = conn.execute("SELECT * FROM device_commands WHERE id = ?", (command_id,)).fetchone()
    if cmd is None:
        raise NotFound("command %s" % command_id)
    if cmd["status"] != "APPROVED":
        raise ValidationError("command %s is %s, not APPROVED" % (command_id, cmd["status"]))

    device = conn.execute(
        "SELECT * FROM devices WHERE id = ?", (cmd["device_id"],)
    ).fetchone()

    # Re-check right before dispatch: the customer may have paid in the
    # minutes between approval and the worker picking the job up.
    if cmd["command"] in RESTRICTIVE:
        check = eligibility_for_restriction(conn, cmd["device_id"], as_of)
        if not check["eligible"]:
            conn.execute(
                "UPDATE device_commands SET status = 'REJECTED', updated_at = ? WHERE id = ?",
                (now(), command_id),
            )
            _log(conn, command_id, "rejected_at_dispatch", check["reason"])
            audit(conn, actor, "device.command_reject", "device_command", command_id,
                  after={"reason": check["reason"]})
            return {"command_id": command_id, "status": "REJECTED", "reason": check["reason"]}

    context: Dict[str, Any] = {"device_id": device["id"]}
    if cmd["command"] in RESTRICTIVE:
        context["profile"] = dict(RESTRICTION_PROFILE)
    result = provider.send(device["imei"], cmd["command"], context)
    status = "ACKED" if result.get("delivered") else "FAILED"
    conn.execute(
        "UPDATE device_commands SET status = ?, provider = ?, provider_ref = ?, updated_at = ?"
        " WHERE id = ?",
        (status, provider.name, result.get("provider_ref"), now(), command_id),
    )
    _log(conn, command_id, "dispatch_%s" % status.lower(), str(result.get("detail", "")))

    if status == "ACKED":
        new_device_status = {
            "RESTRICT": "RESTRICTED",
            "RESTORE": "RESTORED",
            "RELEASE": "COMPLETED",
            "ENROLL": "ACTIVE",
        }.get(cmd["command"])
        if new_device_status:
            conn.execute(
                "UPDATE devices SET status = ? WHERE id = ?",
                (new_device_status, cmd["device_id"]),
            )
        if cmd["command"] in UNLOCKING:
            confirm_unlock(conn, actor, command_id, at)
    audit(conn, actor, "device.command_dispatch", "device_command", command_id,
          after={"status": status, "provider": provider.name})
    return {"command_id": command_id, "status": status, "provider": provider.name,
            "detail": result.get("detail")}


def restore_on_payment(
    conn: sqlite3.Connection,
    actor: Optional[Actor],
    finance_id: str,
    provider: Optional[DeviceProvider] = None,
    at: Optional[_dt.datetime] = None,
) -> Optional[Dict[str, Any]]:
    """After a successful payment, lift a restriction if nothing is overdue."""
    fin = conn.execute(
        "SELECT device_id FROM finance_accounts WHERE id = ?", (finance_id,)
    ).fetchone()
    if fin is None or not fin["device_id"]:
        return None
    device = conn.execute(
        "SELECT status FROM devices WHERE id = ?", (fin["device_id"],)
    ).fetchone()
    if device["status"] != "RESTRICTED":
        return None
    still_overdue = conn.execute(
        "SELECT COUNT(*) c FROM emi_schedules WHERE finance_id = ? AND status = 'OVERDUE'",
        (finance_id,),
    ).fetchone()["c"]
    if still_overdue:
        return None
    cmd = request_command(conn, actor, fin["device_id"], "RESTORE",
                          reason="payment received, no instalment overdue", auto_approve=True)
    open_unlock_obligation(conn, cmd["command_id"], at)
    return send_to_provider(conn, actor, cmd["command_id"], provider, at=at)


# ------------------------------------------------------------ unlock timing


def _parse(ts: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(ts)


def _late_compensation(conn: sqlite3.Connection, due_by: str, end: _dt.datetime) -> int:
    """Compensation for each started hour past the deadline; zero if on time."""
    late_seconds = (end - _parse(due_by)).total_seconds()
    if late_seconds <= 0:
        return 0
    hours = -(-int(late_seconds) // 3600)
    return hours * get_setting(conn, "restriction.late_unlock_compensation_paise_per_hour")


def open_unlock_obligation(
    conn: sqlite3.Connection, command_id: str, at: Optional[_dt.datetime] = None
) -> str:
    """Start the clock on an unlock the customer is owed.

    Raised the moment the arrears clear, before the provider is even asked,
    so a provider outage counts against the deadline rather than hiding it.
    """
    cmd = conn.execute(
        "SELECT c.device_id, f.id finance_id FROM device_commands c"
        " JOIN finance_accounts f ON f.device_id = c.device_id WHERE c.id = ?",
        (command_id,),
    ).fetchone()
    if cmd is None:
        raise NotFound("command %s" % command_id)
    # A retry after a failed send is the same unlock, not a new one: point the
    # open obligation at the new command and keep the original deadline.
    pending = conn.execute(
        "SELECT id FROM unlock_obligations WHERE device_id = ? AND confirmed_at IS NULL",
        (cmd["device_id"],),
    ).fetchone()
    if pending is not None:
        conn.execute("UPDATE unlock_obligations SET command_id = ? WHERE id = ?",
                     (command_id, pending["id"]))
        return pending["id"]
    start = at or _parse(now())
    minutes = get_setting(conn, "restriction.unlock_limit_minutes")
    obligation_id = next_id(conn, "unlock")
    conn.execute(
        "INSERT INTO unlock_obligations(id, device_id, finance_id, command_id,"
        " triggered_at, due_by) VALUES (?,?,?,?,?,?)",
        (obligation_id, cmd["device_id"], cmd["finance_id"], command_id,
         start.isoformat(), (start + _dt.timedelta(minutes=minutes)).isoformat()),
    )
    return obligation_id


def confirm_unlock(
    conn: sqlite3.Connection, actor: Optional[Actor], command_id: str,
    at: Optional[_dt.datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Close the obligation and fix what, if anything, is owed for lateness."""
    row = conn.execute(
        "SELECT * FROM unlock_obligations WHERE command_id = ? AND confirmed_at IS NULL",
        (command_id,),
    ).fetchone()
    if row is None:
        return None
    end = at or _parse(now())
    owed = _late_compensation(conn, row["due_by"], end)
    conn.execute(
        "UPDATE unlock_obligations SET confirmed_at = ?, compensation_paise = ? WHERE id = ?",
        (end.isoformat(), owed, row["id"]),
    )
    if owed:
        audit(conn, actor, "device.unlock_late", "unlock_obligation", row["id"],
              after={"due_by": row["due_by"], "confirmed_at": end.isoformat(),
                     "compensation_paise": owed})
    return {"obligation_id": row["id"], "compensation_paise": owed}


def unlock_monitor(
    conn: sqlite3.Connection, at: Optional[_dt.datetime] = None, warn_after_minutes: int = 30
) -> List[Dict[str, Any]]:
    """Unconfirmed unlocks that need a person now. Run every few minutes.

    Lists each one past ``warn_after_minutes`` - well inside the hour, so
    there is time to act - with the compensation owed if it ended now.
    """
    end = at or _parse(now())
    rows = conn.execute(
        "SELECT o.*, d.imei FROM unlock_obligations o JOIN devices d ON d.id = o.device_id"
        " WHERE o.confirmed_at IS NULL ORDER BY o.triggered_at",
    ).fetchall()
    out = []
    for r in rows:
        waited = (end - _parse(r["triggered_at"])).total_seconds() / 60
        if waited < warn_after_minutes:
            continue
        out.append({
            "obligation_id": r["id"],
            "device_id": r["device_id"],
            "imei": r["imei"],
            "finance_id": r["finance_id"],
            "command_id": r["command_id"],
            "minutes_waiting": int(waited),
            "due_by": r["due_by"],
            "overdue": end > _parse(r["due_by"]),
            "compensation_so_far_paise": _late_compensation(conn, r["due_by"], end),
        })
    return out


def command_history(conn: sqlite3.Connection, device_id: str):
    rows = conn.execute(
        "SELECT * FROM device_commands WHERE device_id = ? ORDER BY created_at", (device_id,)
    ).fetchall()
    return [dict(r) for r in rows]
