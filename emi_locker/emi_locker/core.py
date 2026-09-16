"""Identity, money, audit and access-control primitives."""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from typing import Any, Dict, Optional

from .errors import PermissionDenied, ValidationError

# Blueprint section 23: every important entity carries a readable unique id.
ID_PREFIXES = {
    "user": "USR",
    "customer": "CUS",
    "finance": "FIN",
    "device": "DEV",
    "emi": "EMI",
    "payment": "PAY",
    "receipt": "REC",
    "agreement": "AGR",
    "license": "LIC",
    "plan": "PLN",
    "order": "ORD",
    "allocation": "ALC",
    "activation": "ACT",
    "renewal": "RNW",
    "consent": "CNS",
    "collection": "COL",
    "command": "CMD",
}


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def today() -> _dt.date:
    return _dt.datetime.now(_dt.timezone.utc).date()


def next_id(conn: sqlite3.Connection, kind: str) -> str:
    """Sequential, zero-padded id such as ``CUS-0000125``.

    Called inside the caller's transaction so the counter moves atomically
    with the row it labels.
    """
    prefix = ID_PREFIXES[kind]
    conn.execute(
        "INSERT INTO counters(name, value) VALUES (?, 1) "
        "ON CONFLICT(name) DO UPDATE SET value = value + 1",
        (kind,),
    )
    value = conn.execute("SELECT value FROM counters WHERE name = ?", (kind,)).fetchone()[0]
    return "%s-%07d" % (prefix, value)


def rupees(amount: float) -> int:
    """Rupees -> paise. All arithmetic downstream is integer paise."""
    return int(round(amount * 100))


def format_inr(paise: int) -> str:
    return "Rs.%s" % ("{:,.2f}".format(paise / 100.0))


class Actor:
    """The authenticated principal performing an operation."""

    def __init__(self, user_id: str, role: str, parent_id: Optional[str] = None):
        self.user_id = user_id
        self.role = role
        self.parent_id = parent_id

    @classmethod
    def load(cls, conn: sqlite3.Connection, user_id: str) -> "Actor":
        row = conn.execute(
            "SELECT id, role, parent_id, status FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None:
            raise PermissionDenied("unknown actor %s" % user_id)
        if row["status"] != "ACTIVE":
            raise PermissionDenied("actor %s is %s" % (user_id, row["status"]))
        return cls(row["id"], row["role"], row["parent_id"])

    @property
    def is_admin(self) -> bool:
        return self.role == "SUPER_ADMIN"

    def require_role(self, *roles: str) -> None:
        if self.role not in roles:
            raise PermissionDenied(
                "role %s cannot perform this action (needs one of %s)"
                % (self.role, ", ".join(roles))
            )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Actor(%s, %s)" % (self.user_id, self.role)


def audit(
    conn: sqlite3.Connection,
    actor: Optional[Actor],
    action: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    before: Any = None,
    after: Any = None,
) -> None:
    """Append an immutable audit row. Must run inside the caller's transaction."""
    conn.execute(
        "INSERT INTO audit_logs(actor_id, actor_role, action, entity_type, entity_id,"
        " before_json, after_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            actor.user_id if actor else None,
            actor.role if actor else None,
            action,
            entity_type,
            entity_id,
            json.dumps(before) if before is not None else None,
            json.dumps(after) if after is not None else None,
            now(),
        ),
    )


def remember_idempotent(
    conn: sqlite3.Connection, scope: str, key: str, result: Dict[str, Any]
) -> None:
    conn.execute(
        "INSERT INTO idempotency_keys(scope, key, result_json, created_at) VALUES (?,?,?,?)",
        (scope, key, json.dumps(result), now()),
    )


def replay_idempotent(
    conn: sqlite3.Connection, scope: str, key: Optional[str]
) -> Optional[Dict[str, Any]]:
    if not key:
        return None
    row = conn.execute(
        "SELECT result_json FROM idempotency_keys WHERE scope = ? AND key = ?", (scope, key)
    ).fetchone()
    return json.loads(row["result_json"]) if row else None


def scope_of(conn: sqlite3.Connection, actor: Actor) -> Dict[str, Any]:
    """Which retailers this actor may act on. Section 16/21 of the blueprint."""
    if actor.is_admin:
        return {"all": True, "retailers": None}
    if actor.role == "DISTRIBUTOR":
        rows = conn.execute(
            "SELECT id FROM users WHERE role = 'RETAILER' AND parent_id = ?", (actor.user_id,)
        ).fetchall()
        return {"all": False, "retailers": {r["id"] for r in rows}}
    if actor.role in ("RETAILER", "STAFF"):
        owner = actor.user_id if actor.role == "RETAILER" else actor.parent_id
        return {"all": False, "retailers": {owner}}
    return {"all": False, "retailers": set()}


def assert_can_touch_retailer(conn: sqlite3.Connection, actor: Actor, retailer_id: str) -> None:
    scope = scope_of(conn, actor)
    if scope["all"]:
        return
    if retailer_id not in (scope["retailers"] or set()):
        raise PermissionDenied(
            "%s %s is not permitted to act on retailer %s"
            % (actor.role, actor.user_id, retailer_id)
        )


def create_user(
    conn: sqlite3.Connection,
    role: str,
    name: str,
    mobile: Optional[str] = None,
    parent_id: Optional[str] = None,
    status: str = "ACTIVE",
    actor: Optional[Actor] = None,
) -> str:
    if role not in ("SUPER_ADMIN", "DISTRIBUTOR", "RETAILER", "STAFF", "CUSTOMER"):
        raise ValidationError("unknown role %s" % role)
    if role == "RETAILER" and parent_id:
        parent = conn.execute("SELECT role FROM users WHERE id = ?", (parent_id,)).fetchone()
        if parent is None or parent["role"] != "DISTRIBUTOR":
            raise ValidationError("a retailer's parent must be a distributor")
    uid = next_id(conn, "user")
    conn.execute(
        "INSERT INTO users(id, role, name, mobile, parent_id, status, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (uid, role, name, mobile, parent_id, status, now()),
    )
    if role in ("DISTRIBUTOR", "RETAILER"):
        conn.execute(
            "INSERT OR IGNORE INTO license_wallets(owner_id, updated_at) VALUES (?,?)",
            (uid, now()),
        )
    audit(conn, actor, "user.create", "user", uid, after={"role": role, "name": name})
    return uid
