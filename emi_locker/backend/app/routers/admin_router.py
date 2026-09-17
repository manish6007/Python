"""Admin dashboard, reports and device actions.

There is no admin app in this build - these back the reports the Super Admin
web panel will call, and give you a way to inspect state while testing.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from emi_locker import devices as devices_mod
from emi_locker import licensing, lifecycle, reports, settings_store
from emi_locker.core import Actor
from emi_locker.core import audit as audit_log
from emi_locker.core import create_user
from emi_locker.db import tx
from emi_locker.errors import NotFound, PermissionDenied

from ..deps import current_actor, get_conn, require_roles
from ..schemas import (
    CreateUserIn,
    DeviceActionIn,
    GenerateLicenseIn,
    LicenseStatusIn,
    PlanIn,
    SettingIn,
    UserStatusIn,
)

router = APIRouter(tags=["admin"])
AdminActor = require_roles("SUPER_ADMIN")


@router.get("/reports/dashboard")
def dashboard(actor: Actor = Depends(AdminActor),
              conn: sqlite3.Connection = Depends(get_conn)):
    return reports.admin_dashboard(conn, actor)


@router.get("/reports/outstanding")
def outstanding(actor: Actor = Depends(current_actor),
                conn: sqlite3.Connection = Depends(get_conn)):
    return {"rows": reports.outstanding_report(conn, actor)}


@router.get("/reports/overdue")
def overdue(actor: Actor = Depends(current_actor),
            conn: sqlite3.Connection = Depends(get_conn)):
    return {"rows": lifecycle.overdue_report(conn)}


@router.get("/reports/retailers")
def retailers(actor: Actor = Depends(current_actor),
              conn: sqlite3.Connection = Depends(get_conn)):
    return {"rows": reports.retailer_performance(conn, actor)}


@router.get("/reports/licenses")
def licenses(actor: Actor = Depends(require_roles("SUPER_ADMIN", "DISTRIBUTOR")),
             conn: sqlite3.Connection = Depends(get_conn)):
    return {"rows": reports.license_utilisation(conn, actor)}


@router.post("/device-actions", status_code=201)
def device_action(body: DeviceActionIn, actor: Actor = Depends(AdminActor),
                  conn: sqlite3.Connection = Depends(get_conn)):
    with tx(conn):
        return devices_mod.request_command(
            conn, actor, body.device_id, body.command, body.reason)


@router.post("/device-actions/{command_id}/approve")
def approve_action(command_id: str, actor: Actor = Depends(AdminActor),
                   conn: sqlite3.Connection = Depends(get_conn)):
    with tx(conn):
        approval = devices_mod.approve_command(conn, actor, command_id)
        # The default provider sends nothing: no EMM is wired up. See
        # FEASIBILITY.md section 3.1.
        dispatch = devices_mod.send_to_provider(conn, actor, command_id)
    return {"approval": approval, "dispatch": dispatch}


@router.get("/devices/{device_id}/commands")
def device_commands(device_id: str, actor: Actor = Depends(AdminActor),
                    conn: sqlite3.Connection = Depends(get_conn)):
    return {"commands": devices_mod.command_history(conn, device_id)}


@router.get("/audit/{entity_id}")
def audit(entity_id: str, actor: Actor = Depends(AdminActor),
          conn: sqlite3.Connection = Depends(get_conn)):
    return {"events": reports.audit_trail(conn, actor, entity_id)}


@router.post("/admin/run-daily-sweep")
def run_sweep(actor: Actor = Depends(AdminActor),
              conn: sqlite3.Connection = Depends(get_conn)):
    with tx(conn):
        moved = lifecycle.run_daily_status_sweep(conn, actor)
    return {"moved": {k: len(v) for k, v in moved.items()}}


# ---------------------------------------------------------------- the network


@router.get("/admin/network")
def network(actor: Actor = Depends(AdminActor),
            conn: sqlite3.Connection = Depends(get_conn)):
    """Distributors with their retailers, as the panel's tree view."""
    rows = conn.execute(
        "SELECT u.id, u.name, u.mobile, u.role, u.parent_id, u.status, u.created_at,"
        " COALESCE(w.total_quota, 0) total_quota,"
        " COALESCE(w.used_quota, 0) used_quota,"
        " COALESCE(w.total_quota - w.used_quota - w.reserved_quota, 0) available_quota"
        " FROM users u LEFT JOIN license_wallets w ON w.owner_id = u.id"
        " WHERE u.role IN ('DISTRIBUTOR','RETAILER','STAFF')"
        " ORDER BY u.role, u.name"
    ).fetchall()
    people = [dict(r) for r in rows]
    by_parent: Dict[str, List[Dict[str, Any]]] = {}
    for person in people:
        by_parent.setdefault(person["parent_id"] or "", []).append(person)
    distributors = [p for p in people if p["role"] == "DISTRIBUTOR"]
    for distributor in distributors:
        distributor["retailers"] = by_parent.get(distributor["id"], [])
    return {
        "distributors": distributors,
        "unassigned_retailers": [
            p for p in by_parent.get("", []) if p["role"] == "RETAILER"
        ],
    }


@router.post("/admin/users", status_code=201)
def create_network_user(body: CreateUserIn, actor: Actor = Depends(AdminActor),
                        conn: sqlite3.Connection = Depends(get_conn)):
    with tx(conn):
        user_id = create_user(conn, body.role, body.name, body.mobile,
                              parent_id=body.parent_id, actor=actor)
    return {"user_id": user_id, "role": body.role}


@router.post("/admin/users/{user_id}/status")
def set_user_status(user_id: str, body: UserStatusIn, actor: Actor = Depends(AdminActor),
                    conn: sqlite3.Connection = Depends(get_conn)):
    """Suspending an account takes effect on the next request, not the next login.

    ``actor_from_token`` reloads the user on every call, so an already-issued
    token stops working immediately.
    """
    row = conn.execute("SELECT status, role FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise NotFound("user %s" % user_id)
    if row["role"] == "SUPER_ADMIN":
        raise PermissionDenied("an admin account cannot be suspended from here")
    with tx(conn):
        conn.execute("UPDATE users SET status = ? WHERE id = ?", (body.status, user_id))
        audit_log(conn, actor, "user.status_change", "user", user_id,
                  before={"status": row["status"]},
                  after={"status": body.status, "reason": body.reason})
    return {"user_id": user_id, "status": body.status}


# --------------------------------------------------------------- licence stock


@router.get("/admin/plans")
def list_plans(actor: Actor = Depends(AdminActor),
               conn: sqlite3.Connection = Depends(get_conn)):
    rows = conn.execute(
        "SELECT p.*, (SELECT COUNT(*) FROM licenses l WHERE l.plan_id = p.id) issued"
        " FROM license_plans p ORDER BY p.quota"
    ).fetchall()
    return {"plans": [dict(r) for r in rows]}


@router.post("/admin/plans", status_code=201)
def create_plan(body: PlanIn, actor: Actor = Depends(AdminActor),
                conn: sqlite3.Connection = Depends(get_conn)):
    with tx(conn):
        plan_id = licensing.create_plan(conn, actor, body.name, body.quota,
                                        body.price_paise, body.validity_days)
    return {"plan_id": plan_id}


@router.get("/admin/licenses")
def list_licenses(status: str = "", actor: Actor = Depends(AdminActor),
                  conn: sqlite3.Connection = Depends(get_conn)):
    rows = conn.execute(
        "SELECT l.id, l.key_masked, l.quota, l.status, l.owner_type, l.owner_id,"
        " l.valid_from, l.valid_to, l.created_at, p.name plan_name,"
        " u.name owner_name,"
        " (SELECT COUNT(*) FROM license_activations a"
        "    WHERE a.license_id = l.id AND a.status = 'CONSUMED') consumed"
        " FROM licenses l JOIN license_plans p ON p.id = l.plan_id"
        " LEFT JOIN users u ON u.id = l.owner_id"
        " WHERE (? = '' OR l.status = ?)"
        " ORDER BY l.created_at DESC LIMIT 300",
        (status, status),
    ).fetchall()
    return {"licenses": [dict(r) for r in rows]}


@router.post("/admin/licenses/generate", status_code=201)
def generate_license(body: GenerateLicenseIn, actor: Actor = Depends(AdminActor),
                     conn: sqlite3.Connection = Depends(get_conn)):
    """Mint a licence key. The raw key is returned once and never again."""
    with tx(conn):
        return licensing.generate_license(
            conn, actor, body.plan_id, body.owner_type, body.owner_id,
            body.quota, body.validity_days)


@router.post("/admin/licenses/{license_id}/status")
def set_license_status(license_id: str, body: LicenseStatusIn,
                       actor: Actor = Depends(AdminActor),
                       conn: sqlite3.Connection = Depends(get_conn)):
    with tx(conn):
        licensing.set_license_status(conn, actor, license_id, body.status, body.reason)
    return {"license_id": license_id, "status": body.status}


# ------------------------------------------------------------------- the book


@router.get("/admin/customers")
def list_customers(q: str = "", actor: Actor = Depends(AdminActor),
                   conn: sqlite3.Connection = Depends(get_conn)):
    like = "%%%s%%" % q.strip()
    rows = conn.execute(
        "SELECT c.id, c.name, c.mobile, c.kyc_status, c.created_at,"
        " u.name retailer_name, c.retailer_id,"
        " (SELECT COUNT(*) FROM finance_accounts f WHERE f.customer_id = c.id)"
        "   finance_count,"
        " (SELECT COALESCE(SUM(e.amount_paise),0) FROM emi_schedules e"
        "    JOIN finance_accounts f ON f.id = e.finance_id"
        "    WHERE f.customer_id = c.id AND e.status NOT IN ('PAID','WAIVED'))"
        "   outstanding_paise"
        " FROM customers c JOIN users u ON u.id = c.retailer_id"
        " WHERE (? = '' OR c.name LIKE ? OR c.mobile LIKE ?)"
        " ORDER BY c.created_at DESC LIMIT 300",
        (q.strip(), like, like),
    ).fetchall()
    return {"customers": [dict(r) for r in rows]}


@router.get("/admin/finances")
def list_finances(status: str = "", actor: Actor = Depends(AdminActor),
                  conn: sqlite3.Connection = Depends(get_conn)):
    rows = conn.execute(
        "SELECT f.id, f.status, f.principal, f.emi_amount, f.tenure_months,"
        " f.start_date, f.created_at, c.name customer_name, c.mobile,"
        " u.name retailer_name, d.imei, d.status device_status,"
        " (SELECT COALESCE(SUM(e.amount_paise),0) FROM emi_schedules e"
        "    WHERE e.finance_id = f.id AND e.status NOT IN ('PAID','WAIVED'))"
        "   outstanding_paise"
        " FROM finance_accounts f"
        " JOIN customers c ON c.id = f.customer_id"
        " JOIN users u ON u.id = f.retailer_id"
        " LEFT JOIN devices d ON d.id = f.device_id"
        " WHERE (? = '' OR f.status = ?)"
        " ORDER BY f.created_at DESC LIMIT 300",
        (status, status),
    ).fetchall()
    return {"finances": [dict(r) for r in rows]}


@router.get("/admin/devices")
def list_devices(status: str = "", actor: Actor = Depends(AdminActor),
                 conn: sqlite3.Connection = Depends(get_conn)):
    rows = conn.execute(
        "SELECT d.id, d.imei, d.model, d.status, d.created_at, d.finance_id,"
        " c.name customer_name, f.status finance_status"
        " FROM devices d JOIN customers c ON c.id = d.customer_id"
        " LEFT JOIN finance_accounts f ON f.id = d.finance_id"
        " WHERE (? = '' OR d.status = ?)"
        " ORDER BY d.created_at DESC LIMIT 300",
        (status, status),
    ).fetchall()
    return {"devices": [dict(r) for r in rows]}


@router.get("/admin/payments")
def list_payments(actor: Actor = Depends(AdminActor),
                  conn: sqlite3.Connection = Depends(get_conn)):
    rows = conn.execute(
        "SELECT p.id payment_id, p.amount_paise, p.method, p.status, p.updated_at,"
        " p.gateway_txn_id, c.name customer_name, u.name retailer_name,"
        " r.number receipt_number, e.seq emi_seq"
        " FROM payment_transactions p"
        " JOIN finance_accounts f ON f.id = p.finance_id"
        " JOIN customers c ON c.id = f.customer_id"
        " JOIN users u ON u.id = f.retailer_id"
        " LEFT JOIN receipts r ON r.payment_id = p.id"
        " LEFT JOIN emi_schedules e ON e.id = p.emi_id"
        " ORDER BY p.updated_at DESC LIMIT 200"
    ).fetchall()
    return {"payments": [dict(r) for r in rows]}


@router.get("/reports/commission")
def commission(actor: Actor = Depends(require_roles("SUPER_ADMIN", "DISTRIBUTOR")),
               conn: sqlite3.Connection = Depends(get_conn)):
    return reports.commission_report(conn, actor)


# -------------------------------------------------------- settings and audit


@router.get("/admin/settings")
def get_settings(actor: Actor = Depends(AdminActor),
                 conn: sqlite3.Connection = Depends(get_conn)):
    return {"settings": settings_store.all_settings(conn)}


@router.put("/admin/settings")
def put_setting(body: SettingIn, actor: Actor = Depends(AdminActor),
                conn: sqlite3.Connection = Depends(get_conn)):
    with tx(conn):
        value = settings_store.set_setting(conn, actor, body.key, body.value)
    return {"key": body.key, "value": value}


@router.get("/admin/audit")
def recent_audit(limit: int = 100, action: str = "",
                 actor: Actor = Depends(AdminActor),
                 conn: sqlite3.Connection = Depends(get_conn)):
    """The append-only trail, newest first. Read-only by construction."""
    rows = conn.execute(
        "SELECT a.*, u.name actor_name FROM audit_logs a"
        " LEFT JOIN users u ON u.id = a.actor_id"
        " WHERE (? = '' OR a.action LIKE ?)"
        " ORDER BY a.id DESC LIMIT ?",
        (action, "%%%s%%" % action, max(1, min(limit, 500))),
    ).fetchall()
    return {"events": [dict(r) for r in rows]}
