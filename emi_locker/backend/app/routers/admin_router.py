"""Admin dashboard, reports and device actions.

There is no admin app in this build - these back the reports the Super Admin
web panel will call, and give you a way to inspect state while testing.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from emi_locker import devices as devices_mod
from emi_locker import lifecycle, reports
from emi_locker.core import Actor
from emi_locker.db import tx

from ..deps import current_actor, get_conn, require_roles
from ..schemas import DeviceActionIn

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
