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
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional, Protocol

from .core import Actor, audit, next_id, now
from .errors import NotFound, PermissionDenied, ValidationError

RESTRICTIVE = ("RESTRICT",)


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


def eligibility_for_restriction(conn: sqlite3.Connection, device_id: str) -> Dict[str, Any]:
    """Is this device actually past the agreed grace period, with money owed?"""
    row = conn.execute(
        "SELECT f.id finance_id, f.status, f.grace_days,"
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
    return {
        "eligible": True,
        "finance_id": row["finance_id"],
        "overdue_count": row["overdue_count"],
        "outstanding": row["outstanding"],
    }


def request_command(
    conn: sqlite3.Connection,
    actor: Optional[Actor],
    device_id: str,
    command: str,
    reason: str,
    auto_approve: bool = False,
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
        check = eligibility_for_restriction(conn, device_id)
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
) -> Dict[str, Any]:
    """Dispatch an approved command and record the provider's answer."""
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
        check = eligibility_for_restriction(conn, cmd["device_id"])
        if not check["eligible"]:
            conn.execute(
                "UPDATE device_commands SET status = 'REJECTED', updated_at = ? WHERE id = ?",
                (now(), command_id),
            )
            _log(conn, command_id, "rejected_at_dispatch", check["reason"])
            audit(conn, actor, "device.command_reject", "device_command", command_id,
                  after={"reason": check["reason"]})
            return {"command_id": command_id, "status": "REJECTED", "reason": check["reason"]}

    result = provider.send(device["imei"], cmd["command"], {"device_id": device["id"]})
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
    audit(conn, actor, "device.command_dispatch", "device_command", command_id,
          after={"status": status, "provider": provider.name})
    return {"command_id": command_id, "status": status, "provider": provider.name,
            "detail": result.get("detail")}


def restore_on_payment(
    conn: sqlite3.Connection,
    actor: Optional[Actor],
    finance_id: str,
    provider: Optional[DeviceProvider] = None,
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
    return send_to_provider(conn, actor, cmd["command_id"], provider)


def command_history(conn: sqlite3.Connection, device_id: str):
    rows = conn.execute(
        "SELECT * FROM device_commands WHERE device_id = ? ORDER BY created_at", (device_id,)
    ).fetchall()
    return [dict(r) for r in rows]
