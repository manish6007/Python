"""Read-side queries for the admin, distributor and retailer dashboards.

Every report is scoped through the caller's Actor: a distributor sees its own
retailers and nothing else (section 16), a retailer sees only its own book.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List

from .core import Actor, scope_of


def _retailer_filter(conn: sqlite3.Connection, actor: Actor):
    scope = scope_of(conn, actor)
    if scope["all"]:
        return "", ()
    retailers = sorted(scope["retailers"] or {"__none__"})
    return (" AND f.retailer_id IN (%s)" % ",".join("?" * len(retailers))), tuple(retailers)


def outstanding_report(conn: sqlite3.Connection, actor: Actor) -> List[Dict[str, Any]]:
    clause, params = _retailer_filter(conn, actor)
    rows = conn.execute(
        "SELECT f.retailer_id, COUNT(DISTINCT f.id) accounts,"
        " COALESCE(SUM(CASE WHEN e.status NOT IN ('PAID','WAIVED') THEN e.amount_paise END), 0)"
        "   outstanding_paise,"
        " COALESCE(SUM(CASE WHEN e.status = 'OVERDUE' THEN e.amount_paise END), 0) overdue_paise"
        " FROM finance_accounts f LEFT JOIN emi_schedules e ON e.finance_id = f.id"
        " WHERE f.status IN ('ACTIVE','OVERDUE')" + clause +
        " GROUP BY f.retailer_id ORDER BY outstanding_paise DESC",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def collection_report(conn: sqlite3.Connection, actor: Actor, date_from: str, date_to: str):
    clause, params = _retailer_filter(conn, actor)
    rows = conn.execute(
        "SELECT f.retailer_id, p.method, COUNT(*) txns, SUM(p.amount_paise) amount_paise"
        " FROM payment_transactions p JOIN finance_accounts f ON f.id = p.finance_id"
        " WHERE p.status = 'SUCCESS' AND p.updated_at >= ? AND p.updated_at <= ?" + clause +
        " GROUP BY f.retailer_id, p.method ORDER BY f.retailer_id",
        (date_from, date_to) + params,
    ).fetchall()
    return [dict(r) for r in rows]


def retailer_performance(conn: sqlite3.Connection, actor: Actor) -> List[Dict[str, Any]]:
    clause, params = _retailer_filter(conn, actor)
    rows = conn.execute(
        "SELECT f.retailer_id, u.name retailer_name,"
        " COUNT(DISTINCT f.id) finance_count,"
        " COUNT(DISTINCT f.customer_id) customers,"
        " SUM(CASE WHEN f.status = 'COMPLETED' THEN 1 ELSE 0 END) completed,"
        " SUM(CASE WHEN f.status = 'OVERDUE' THEN 1 ELSE 0 END) overdue_accounts,"
        " SUM(f.principal) financed_paise"
        " FROM finance_accounts f JOIN users u ON u.id = f.retailer_id"
        " WHERE 1 = 1" + clause + " GROUP BY f.retailer_id ORDER BY financed_paise DESC",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def license_utilisation(conn: sqlite3.Connection, actor: Actor) -> List[Dict[str, Any]]:
    actor.require_role("SUPER_ADMIN", "DISTRIBUTOR")
    if actor.is_admin:
        rows = conn.execute(
            "SELECT w.owner_id, u.name, u.role, w.total_quota, w.used_quota,"
            " w.total_quota - w.used_quota - w.reserved_quota available"
            " FROM license_wallets w JOIN users u ON u.id = w.owner_id ORDER BY u.role, u.name"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT w.owner_id, u.name, u.role, w.total_quota, w.used_quota,"
            " w.total_quota - w.used_quota - w.reserved_quota available"
            " FROM license_wallets w JOIN users u ON u.id = w.owner_id"
            " WHERE w.owner_id = ? OR u.parent_id = ? ORDER BY u.role, u.name",
            (actor.user_id, actor.user_id),
        ).fetchall()
    return [dict(r) for r in rows]


def admin_dashboard(conn: sqlite3.Connection, actor: Actor) -> Dict[str, Any]:
    actor.require_role("SUPER_ADMIN")
    one = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    return {
        "customers": one("SELECT COUNT(*) FROM customers"),
        "retailers": one("SELECT COUNT(*) FROM users WHERE role = 'RETAILER'"),
        "distributors": one("SELECT COUNT(*) FROM users WHERE role = 'DISTRIBUTOR'"),
        "active_finance": one("SELECT COUNT(*) FROM finance_accounts WHERE status = 'ACTIVE'"),
        "overdue_finance": one("SELECT COUNT(*) FROM finance_accounts WHERE status = 'OVERDUE'"),
        "completed_finance": one(
            "SELECT COUNT(*) FROM finance_accounts WHERE status = 'COMPLETED'"),
        "devices_restricted": one("SELECT COUNT(*) FROM devices WHERE status = 'RESTRICTED'"),
        "collected_paise": one(
            "SELECT COALESCE(SUM(amount_paise),0) FROM payment_transactions"
            " WHERE status = 'SUCCESS'"),
        "outstanding_paise": one(
            "SELECT COALESCE(SUM(amount_paise),0) FROM emi_schedules"
            " WHERE status NOT IN ('PAID','WAIVED')"),
        "activations_used": one("SELECT COALESCE(SUM(used_quota),0) FROM license_wallets"),
        "activations_available": one(
            "SELECT COALESCE(SUM(total_quota - used_quota - reserved_quota),0)"
            " FROM license_wallets"),
    }


def audit_trail(conn: sqlite3.Connection, actor: Actor, entity_id: str) -> List[Dict[str, Any]]:
    actor.require_role("SUPER_ADMIN")
    rows = conn.execute(
        "SELECT * FROM audit_logs WHERE entity_id = ? ORDER BY id", (entity_id,)
    ).fetchall()
    return [dict(r) for r in rows]
