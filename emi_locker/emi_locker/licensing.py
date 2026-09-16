"""License plans, keys, wallets, allocation and activation consumption.

This module implements the rules listed under "Developer Rules - Must Have"
in the reseller workflow document:

* the backend is the only source of truth for a license balance;
* quota deduction is atomic and idempotent;
* expired/suspended licenses cannot create new activations;
* a distributor cannot touch another distributor's retailers;
* every license movement writes an audit event.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import secrets
import sqlite3
from typing import Any, Dict, List, Optional

from .core import (
    Actor,
    assert_can_touch_retailer,
    audit,
    next_id,
    now,
    remember_idempotent,
    replay_idempotent,
    today,
)
from .errors import (
    InsufficientQuota,
    LicenseInvalid,
    NotFound,
    PermissionDenied,
    ValidationError,
)

KEY_GROUPS = 4
KEY_GROUP_LEN = 5


def _generate_key() -> str:
    """Cryptographically random key, e.g. ``7KQ2M-XT9RD-...``.

    Deliberately not a predictable serial: section 14 of the reseller
    document calls that out, and a guessable key is free inventory for
    whoever guesses it.
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I/O/0/1 lookalikes
    groups = [
        "".join(secrets.choice(alphabet) for _ in range(KEY_GROUP_LEN))
        for _ in range(KEY_GROUPS)
    ]
    return "-".join(groups)


def hash_key(raw_key: str, pepper: str = "") -> str:
    return hashlib.sha256((pepper + raw_key.strip().upper()).encode()).hexdigest()


def mask_key(raw_key: str) -> str:
    groups = raw_key.split("-")
    return "-".join(["*" * len(g) for g in groups[:-1]] + [groups[-1]])


def create_plan(
    conn: sqlite3.Connection,
    actor: Actor,
    name: str,
    quota: int,
    price_paise: int,
    validity_days: int,
) -> str:
    actor.require_role("SUPER_ADMIN")
    if quota <= 0:
        raise ValidationError("quota must be positive")
    plan_id = next_id(conn, "plan")
    conn.execute(
        "INSERT INTO license_plans(id, name, quota, price_paise, validity_days, active)"
        " VALUES (?,?,?,?,?,1)",
        (plan_id, name, quota, price_paise, validity_days),
    )
    audit(conn, actor, "plan.create", "license_plan", plan_id,
          after={"name": name, "quota": quota, "price_paise": price_paise})
    return plan_id


def generate_license(
    conn: sqlite3.Connection,
    actor: Actor,
    plan_id: str,
    owner_type: str,
    owner_id: Optional[str] = None,
    quota: Optional[int] = None,
    validity_days: Optional[int] = None,
    pepper: str = "",
) -> Dict[str, Any]:
    """Admin mints a license key. The raw key is returned exactly once."""
    actor.require_role("SUPER_ADMIN")
    plan = conn.execute("SELECT * FROM license_plans WHERE id = ?", (plan_id,)).fetchone()
    if plan is None:
        raise NotFound("plan %s" % plan_id)
    if owner_type not in ("DISTRIBUTOR", "RETAILER", "DIRECT"):
        raise ValidationError("bad owner_type %s" % owner_type)

    quota = quota or plan["quota"]
    days = validity_days or plan["validity_days"]
    raw_key = _generate_key()
    license_id = next_id(conn, "license")
    valid_from = today()
    valid_to = valid_from + _dt.timedelta(days=days)
    status = "ACTIVE" if owner_id else "AVAILABLE"

    conn.execute(
        "INSERT INTO licenses(id, key_hash, key_masked, plan_id, quota, owner_type,"
        " owner_id, status, valid_from, valid_to, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (license_id, hash_key(raw_key, pepper), mask_key(raw_key), plan_id, quota,
         owner_type, owner_id, status, valid_from.isoformat(), valid_to.isoformat(), now()),
    )
    if owner_id:
        _credit_wallet(conn, owner_id, quota)
    audit(conn, actor, "license.generate", "license", license_id,
          after={"plan_id": plan_id, "quota": quota, "owner_id": owner_id,
                 "valid_to": valid_to.isoformat(), "status": status})
    # The raw key leaves the system here and nowhere else; storage keeps the hash.
    return {
        "license_id": license_id,
        "key": raw_key,
        "key_masked": mask_key(raw_key),
        "quota": quota,
        "valid_to": valid_to.isoformat(),
        "status": status,
    }


def _credit_wallet(conn: sqlite3.Connection, owner_id: str, quota: int) -> None:
    conn.execute(
        "INSERT INTO license_wallets(owner_id, total_quota, updated_at) VALUES (?,?,?)"
        " ON CONFLICT(owner_id) DO UPDATE SET total_quota = total_quota + excluded.total_quota,"
        " updated_at = excluded.updated_at",
        (owner_id, quota, now()),
    )


def wallet(conn: sqlite3.Connection, owner_id: str) -> Dict[str, int]:
    row = conn.execute(
        "SELECT total_quota, used_quota, reserved_quota FROM license_wallets WHERE owner_id = ?",
        (owner_id,),
    ).fetchone()
    if row is None:
        raise NotFound("wallet for %s" % owner_id)
    return {
        "owner_id": owner_id,
        "total": row["total_quota"],
        "used": row["used_quota"],
        "reserved": row["reserved_quota"],
        "available": row["total_quota"] - row["used_quota"] - row["reserved_quota"],
    }


def _load_license_for_use(conn: sqlite3.Connection, license_id: str) -> sqlite3.Row:
    lic = conn.execute("SELECT * FROM licenses WHERE id = ?", (license_id,)).fetchone()
    if lic is None:
        raise NotFound("license %s" % license_id)
    if lic["status"] in ("SUSPENDED", "REVOKED"):
        raise LicenseInvalid("license %s is %s" % (license_id, lic["status"]))
    if _dt.date.fromisoformat(lic["valid_to"]) < today():
        raise LicenseInvalid("license %s expired on %s" % (license_id, lic["valid_to"]))
    return lic


def effective_license(conn: sqlite3.Connection, owner_id: str) -> Optional[sqlite3.Row]:
    """The license that currently backs this owner's activation balance.

    A retailer usually holds no license of its own: its balance was pushed
    down by a distributor, so validity has to be read from the distributor's
    license. Without this the wallet would outlive the subscription that
    paid for it.
    """
    own = conn.execute(
        "SELECT * FROM licenses WHERE owner_id = ? AND status = 'ACTIVE' AND valid_to >= ?"
        " ORDER BY valid_to DESC LIMIT 1",
        (owner_id, today().isoformat()),
    ).fetchone()
    if own is not None:
        return own
    return conn.execute(
        "SELECT l.* FROM license_allocations a JOIN licenses l ON l.id = a.license_id"
        " WHERE a.to_owner = ? AND l.status = 'ACTIVE' AND l.valid_to >= ?"
        " ORDER BY l.valid_to DESC LIMIT 1",
        (owner_id, today().isoformat()),
    ).fetchone()


def redeem_license(
    conn: sqlite3.Connection, actor: Actor, raw_key: str, pepper: str = ""
) -> Dict[str, Any]:
    """A distributor or retailer claims an unassigned key and gets its quota."""
    actor.require_role("DISTRIBUTOR", "RETAILER")
    row = conn.execute(
        "SELECT * FROM licenses WHERE key_hash = ?", (hash_key(raw_key, pepper),)
    ).fetchone()
    if row is None:
        # Same error for unknown and already-claimed keys: do not turn this
        # endpoint into an oracle that confirms which keys exist.
        raise LicenseInvalid("license key is not valid")
    if row["status"] != "AVAILABLE" or row["owner_id"] is not None:
        raise LicenseInvalid("license key is not valid")
    if _dt.date.fromisoformat(row["valid_to"]) < today():
        raise LicenseInvalid("license key has expired")
    if row["owner_type"] != "DIRECT" and row["owner_type"] != actor.role:
        raise LicenseInvalid("license key is not valid for this account type")

    conn.execute(
        "UPDATE licenses SET owner_id = ?, status = 'ACTIVE' WHERE id = ? AND status = 'AVAILABLE'",
        (actor.user_id, row["id"]),
    )
    if conn.total_changes == 0:  # pragma: no cover - belt and braces
        raise LicenseInvalid("license key is not valid")
    _credit_wallet(conn, actor.user_id, row["quota"])
    audit(conn, actor, "license.redeem", "license", row["id"],
          before={"status": "AVAILABLE"},
          after={"status": "ACTIVE", "owner_id": actor.user_id, "quota": row["quota"]})
    return {"license_id": row["id"], "quota": row["quota"], "wallet": wallet(conn, actor.user_id)}


def allocate_quota(
    conn: sqlite3.Connection,
    actor: Actor,
    to_owner: str,
    quota: int,
    license_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Distributor pushes part of its balance down to one of its retailers."""
    actor.require_role("SUPER_ADMIN", "DISTRIBUTOR")
    if quota <= 0:
        raise ValidationError("quota must be positive")

    cached = replay_idempotent(conn, "license.allocate", idempotency_key)
    if cached is not None:
        return cached

    target = conn.execute("SELECT * FROM users WHERE id = ?", (to_owner,)).fetchone()
    if target is None:
        raise NotFound("user %s" % to_owner)
    if target["role"] != "RETAILER":
        raise ValidationError("quota can only be allocated to a retailer")
    # Authorisation before inventory: a distributor reaching into another
    # distributor's retailer is denied for that reason, not for a stock level.
    if not actor.is_admin:
        assert_can_touch_retailer(conn, actor, to_owner)

    if license_id is not None:
        backing = _load_license_for_use(conn, license_id)
    else:
        backing = effective_license(conn, actor.user_id)
    if backing is None and not actor.is_admin:
        raise LicenseInvalid("no active, unexpired license backs %s" % actor.user_id)

    if not actor.is_admin:
        # Decrement the distributor's own balance under the write lock.
        cur = conn.execute(
            "UPDATE license_wallets SET used_quota = used_quota + ?, updated_at = ?"
            " WHERE owner_id = ?"
            "   AND total_quota - used_quota - reserved_quota >= ?",
            (quota, now(), actor.user_id, quota),
        )
        if cur.rowcount == 0:
            have = wallet(conn, actor.user_id)["available"]
            raise InsufficientQuota(
                "distributor %s has %d activations available, needs %d"
                % (actor.user_id, have, quota)
            )

    _credit_wallet(conn, to_owner, quota)
    alloc_id = next_id(conn, "allocation")
    conn.execute(
        "INSERT INTO license_allocations(id, license_id, from_owner, to_owner, quota, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (alloc_id, backing["id"] if backing is not None else None,
         actor.user_id, to_owner, quota, now()),
    )
    audit(conn, actor, "license.allocate", "license_allocation", alloc_id,
          after={"from": actor.user_id, "to": to_owner, "quota": quota})
    result = {
        "allocation_id": alloc_id,
        "to_owner": to_owner,
        "quota": quota,
        "license_id": backing["id"] if backing is not None else None,
        "wallet": wallet(conn, to_owner),
    }
    if idempotency_key:
        remember_idempotent(conn, "license.allocate", idempotency_key, result)
    return result


def consume_activation(
    conn: sqlite3.Connection,
    actor: Actor,
    owner_id: str,
    finance_id: Optional[str] = None,
    device_id: Optional[str] = None,
    license_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Burn exactly one activation unit. Must run inside a ``db.tx`` block.

    The single UPDATE with the ``available >= 1`` predicate is the whole
    concurrency story: SQLite evaluates the WHERE clause while holding the
    write lock, so two racing retailer requests cannot both see the last
    unit. ``rowcount == 0`` means somebody else took it.
    """
    cached = replay_idempotent(conn, "license.activate", idempotency_key)
    if cached is not None:
        return cached

    if license_id is not None:
        _load_license_for_use(conn, license_id)
    else:
        row = effective_license(conn, owner_id)
        if row is None:
            raise LicenseInvalid(
                "no active, unexpired license backs owner %s" % owner_id
            )
        license_id = row["id"]

    cur = conn.execute(
        "UPDATE license_wallets SET used_quota = used_quota + 1, updated_at = ?"
        " WHERE owner_id = ? AND total_quota - used_quota - reserved_quota >= 1",
        (now(), owner_id),
    )
    if cur.rowcount == 0:
        raise InsufficientQuota("no activation balance left for %s" % owner_id)

    activation_id = next_id(conn, "activation")
    conn.execute(
        "INSERT INTO license_activations(id, owner_id, license_id, finance_id, device_id,"
        " status, created_at) VALUES (?,?,?,?,?, 'CONSUMED', ?)",
        (activation_id, owner_id, license_id, finance_id, device_id, now()),
    )
    audit(conn, actor, "license.activate", "license_activation", activation_id,
          after={"owner_id": owner_id, "license_id": license_id, "finance_id": finance_id})
    result = {
        "activation_id": activation_id,
        "license_id": license_id,
        "wallet": wallet(conn, owner_id),
    }
    if idempotency_key:
        remember_idempotent(conn, "license.activate", idempotency_key, result)
    return result


def rollback_activation(
    conn: sqlite3.Connection, actor: Actor, activation_id: str, reason: str
) -> Dict[str, Any]:
    """Return a unit to the wallet when the finance it paid for did not stick."""
    row = conn.execute(
        "SELECT * FROM license_activations WHERE id = ?", (activation_id,)
    ).fetchone()
    if row is None:
        raise NotFound("activation %s" % activation_id)
    if row["status"] != "CONSUMED":
        return {"activation_id": activation_id, "status": row["status"]}
    conn.execute(
        "UPDATE license_activations SET status = 'ROLLED_BACK' WHERE id = ?", (activation_id,)
    )
    conn.execute(
        "UPDATE license_wallets SET used_quota = used_quota - 1, updated_at = ?"
        " WHERE owner_id = ? AND used_quota >= 1",
        (now(), row["owner_id"]),
    )
    audit(conn, actor, "license.activation_rollback", "license_activation", activation_id,
          before={"status": "CONSUMED"}, after={"status": "ROLLED_BACK", "reason": reason})
    return {"activation_id": activation_id, "status": "ROLLED_BACK",
            "wallet": wallet(conn, row["owner_id"])}


def renew_license(
    conn: sqlite3.Connection,
    actor: Actor,
    license_id: str,
    extra_days: int,
    order_id: Optional[str] = None,
    carry_forward_unused: bool = True,
) -> Dict[str, Any]:
    actor.require_role("SUPER_ADMIN")
    lic = conn.execute("SELECT * FROM licenses WHERE id = ?", (license_id,)).fetchone()
    if lic is None:
        raise NotFound("license %s" % license_id)
    if lic["status"] == "REVOKED":
        raise LicenseInvalid("revoked license cannot be renewed")
    old_expiry = _dt.date.fromisoformat(lic["valid_to"])
    base = max(old_expiry, today())
    new_expiry = base + _dt.timedelta(days=extra_days)
    conn.execute(
        "UPDATE licenses SET valid_to = ?, status = 'ACTIVE' WHERE id = ?",
        (new_expiry.isoformat(), license_id),
    )
    if not carry_forward_unused and lic["owner_id"]:
        # Business policy switch (section 11): burn the unused balance.
        conn.execute(
            "UPDATE license_wallets SET total_quota = used_quota + reserved_quota, updated_at = ?"
            " WHERE owner_id = ?",
            (now(), lic["owner_id"]),
        )
    renewal_id = next_id(conn, "renewal")
    conn.execute(
        "INSERT INTO license_renewals(id, license_id, order_id, old_expiry, new_expiry, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (renewal_id, license_id, order_id, old_expiry.isoformat(), new_expiry.isoformat(), now()),
    )
    audit(conn, actor, "license.renew", "license", license_id,
          before={"valid_to": old_expiry.isoformat()},
          after={"valid_to": new_expiry.isoformat(), "renewal_id": renewal_id})
    return {"license_id": license_id, "old_expiry": old_expiry.isoformat(),
            "new_expiry": new_expiry.isoformat(), "renewal_id": renewal_id}


def set_license_status(
    conn: sqlite3.Connection, actor: Actor, license_id: str, status: str, reason: str
) -> None:
    actor.require_role("SUPER_ADMIN")
    if status not in ("ACTIVE", "SUSPENDED", "REVOKED"):
        raise ValidationError("bad status %s" % status)
    lic = conn.execute("SELECT status FROM licenses WHERE id = ?", (license_id,)).fetchone()
    if lic is None:
        raise NotFound("license %s" % license_id)
    conn.execute("UPDATE licenses SET status = ? WHERE id = ?", (status, license_id))
    audit(conn, actor, "license.status_change", "license", license_id,
          before={"status": lic["status"]}, after={"status": status, "reason": reason})


def transfer_license(
    conn: sqlite3.Connection,
    actor: Actor,
    license_id: str,
    to_owner: str,
    approved_by_admin: bool,
) -> Dict[str, Any]:
    """Section 13: optional, admin-approved, and used units never move."""
    if not approved_by_admin:
        raise PermissionDenied("license transfer requires explicit admin approval")
    actor.require_role("SUPER_ADMIN")
    lic = _load_license_for_use(conn, license_id)
    target = conn.execute("SELECT role FROM users WHERE id = ?", (to_owner,)).fetchone()
    if target is None:
        raise NotFound("user %s" % to_owner)
    from_owner = lic["owner_id"]
    if from_owner is None:
        raise LicenseInvalid("unclaimed license has no owner to transfer from")

    used_here = conn.execute(
        "SELECT COUNT(*) c FROM license_activations WHERE license_id = ? AND status = 'CONSUMED'",
        (license_id,),
    ).fetchone()["c"]
    # Units already activated stay where they were spent, and units the owner
    # has pushed down to its retailers are no longer theirs to move either.
    movable = min(lic["quota"] - used_here, wallet(conn, from_owner)["available"])
    if movable <= 0:
        raise LicenseInvalid("license has no unused quota to transfer")

    cur = conn.execute(
        "UPDATE license_wallets SET total_quota = total_quota - ?, updated_at = ?"
        " WHERE owner_id = ? AND total_quota - used_quota - reserved_quota >= ?",
        (movable, now(), from_owner, movable),
    )
    if cur.rowcount == 0:
        raise InsufficientQuota("source wallet no longer holds %d free units" % movable)
    _credit_wallet(conn, to_owner, movable)
    conn.execute("UPDATE licenses SET owner_id = ? WHERE id = ?", (to_owner, license_id))
    conn.execute(
        "INSERT INTO license_allocations(id, license_id, from_owner, to_owner, quota, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (next_id(conn, "allocation"), license_id, from_owner, to_owner, movable, now()),
    )
    audit(conn, actor, "license.transfer", "license", license_id,
          before={"owner_id": from_owner}, after={"owner_id": to_owner, "moved": movable})
    return {"license_id": license_id, "from": from_owner, "to": to_owner, "moved": movable}


def expire_due_licenses(conn: sqlite3.Connection, actor: Optional[Actor] = None) -> List[str]:
    """Nightly job: flip elapsed licenses to EXPIRED so activations stop."""
    rows = conn.execute(
        "SELECT id FROM licenses WHERE status = 'ACTIVE' AND valid_to < ?",
        (today().isoformat(),),
    ).fetchall()
    for row in rows:
        conn.execute("UPDATE licenses SET status = 'EXPIRED' WHERE id = ?", (row["id"],))
        audit(conn, actor, "license.expire", "license", row["id"], after={"status": "EXPIRED"})
    return [r["id"] for r in rows]


def verify_key(conn: sqlite3.Connection, raw_key: str, pepper: str = "") -> bool:
    """Constant-time-ish existence check used by rate-limited lookup endpoints."""
    digest = hash_key(raw_key, pepper)
    row = conn.execute("SELECT key_hash FROM licenses WHERE key_hash = ?", (digest,)).fetchone()
    return row is not None and hmac.compare_digest(row["key_hash"], digest)
