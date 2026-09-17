"""Business settings an admin can change without a code deploy.

Commission is the reason this exists. The blueprint (reseller document §16)
lists *possible* commission logic but does not fix any rate, because that is a
commercial decision. So the rates live here, default to zero, and every report
that shows money earned says plainly when no rule has been configured - rather
than the software inventing a percentage nobody agreed to.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict

from .core import Actor, audit, now
from .errors import ValidationError

# key -> (default, human description)
KNOWN_SETTINGS: Dict[str, Any] = {
    "commission.distributor_per_activation_paise": (
        0, "Paid to the distributor for each device its retailers activate"),
    "commission.retailer_per_activation_paise": (
        0, "Paid to the retailer for each device it activates"),
    "commission.distributor_percent_of_financed_bp": (
        0, "Paid to the distributor as basis points of the financed amount "
           "(100 bp = 1%)"),
    "finance.default_grace_days": (5, "Days after the due date before an EMI is overdue"),
    "finance.default_late_fee_paise": (0, "Late fee applied once an EMI is overdue"),
    "business.name": ("Ashish Enterprises", "Shown on receipts and certificates"),
    "business.support_mobile": ("", "Support number shown in the apps"),
}


def get_setting(conn: sqlite3.Connection, key: str) -> Any:
    if key not in KNOWN_SETTINGS:
        raise ValidationError("unknown setting %s" % key)
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return KNOWN_SETTINGS[key][0]
    try:
        return json.loads(row["value"])
    except ValueError:  # pragma: no cover - a hand-edited row
        return row["value"]


def all_settings(conn: sqlite3.Connection) -> Dict[str, Dict[str, Any]]:
    return {
        key: {
            "value": get_setting(conn, key),
            "default": default,
            "description": description,
        }
        for key, (default, description) in KNOWN_SETTINGS.items()
    }


def set_setting(conn: sqlite3.Connection, actor: Actor, key: str, value: Any) -> Any:
    actor.require_role("SUPER_ADMIN")
    if key not in KNOWN_SETTINGS:
        raise ValidationError("unknown setting %s" % key)
    default = KNOWN_SETTINGS[key][0]
    if isinstance(default, int) and not isinstance(default, bool):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationError("%s expects a number" % key)
        value = int(value)
        if value < 0:
            raise ValidationError("%s cannot be negative" % key)
    elif isinstance(default, str) and not isinstance(value, str):
        raise ValidationError("%s expects text" % key)

    before = get_setting(conn, key)
    conn.execute(
        "INSERT INTO settings(key, value, updated_at) VALUES (?,?,?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
        " updated_at = excluded.updated_at",
        (key, json.dumps(value), now()),
    )
    audit(conn, actor, "settings.change", "setting", key,
          before={"value": before}, after={"value": value})
    return value


def commission_rules(conn: sqlite3.Connection) -> Dict[str, int]:
    rules = {
        "distributor_per_activation_paise": get_setting(
            conn, "commission.distributor_per_activation_paise"),
        "retailer_per_activation_paise": get_setting(
            conn, "commission.retailer_per_activation_paise"),
        "distributor_percent_of_financed_bp": get_setting(
            conn, "commission.distributor_percent_of_financed_bp"),
    }
    rules["configured"] = any(v > 0 for v in rules.values())
    return rules
