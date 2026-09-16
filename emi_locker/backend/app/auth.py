"""OTP login and bearer-token sessions.

The flow is the one in the blueprint: POST /auth/send-otp, then
POST /auth/verify-otp returns a token the apps put in the Authorization
header.

Two things are deliberately strict even in local mode, because they are the
bugs that get authentication systems broken into:

* the OTP is stored hashed, never in clear, and is single-use;
* attempts are counted and the code is destroyed after too many, so a
  six-digit code cannot be brute-forced.

``EMI_EXPOSE_OTP=1`` (local default) also returns the code in the response so
you can log in without an SMS provider. ``config.Settings.validate()``
refuses to start in production with that enabled.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import secrets
import sqlite3
from typing import Any, Dict, Optional

import jwt

from emi_locker.core import Actor
from emi_locker.errors import PermissionDenied, ValidationError

from .config import settings

OTP_LENGTH = 6
RESEND_COOLDOWN_SEC = 30


def _hash_code(mobile: str, code: str) -> str:
    return hashlib.sha256(("%s:%s:%s" % (settings.jwt_secret, mobile, code)).encode()).hexdigest()


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def normalise_mobile(mobile: str) -> str:
    digits = "".join(ch for ch in (mobile or "") if ch.isdigit())
    if len(digits) > 10:
        digits = digits[-10:]  # tolerate +91 / 0 prefixes
    if len(digits) != 10:
        raise ValidationError("enter a 10-digit mobile number")
    return digits


def send_otp(conn: sqlite3.Connection, mobile: str) -> Dict[str, Any]:
    """Issue a one-time code for a registered mobile number."""
    mobile = normalise_mobile(mobile)
    user = conn.execute(
        "SELECT id, role, name, status FROM users WHERE mobile = ?", (mobile,)
    ).fetchone()

    existing = conn.execute(
        "SELECT last_sent_at FROM auth_otps WHERE mobile = ?", (mobile,)
    ).fetchone()
    if existing:
        last = _dt.datetime.fromisoformat(existing["last_sent_at"])
        waited = (_utc_now() - last).total_seconds()
        if waited < RESEND_COOLDOWN_SEC:
            raise ValidationError(
                "please wait %d seconds before requesting another code"
                % int(RESEND_COOLDOWN_SEC - waited))

    # An unknown number gets the same answer as a known one. Otherwise this
    # endpoint tells anyone who asks which mobiles have accounts.
    if user is None or user["status"] != "ACTIVE":
        return {"sent": True, "mobile": mobile}

    code = "".join(secrets.choice("0123456789") for _ in range(OTP_LENGTH))
    expires = _utc_now() + _dt.timedelta(seconds=settings.otp_ttl_seconds)
    conn.execute(
        "INSERT INTO auth_otps(mobile, code_hash, expires_at, attempts, last_sent_at)"
        " VALUES (?,?,?,0,?)"
        " ON CONFLICT(mobile) DO UPDATE SET code_hash = excluded.code_hash,"
        " expires_at = excluded.expires_at, attempts = 0,"
        " last_sent_at = excluded.last_sent_at",
        (mobile, _hash_code(mobile, code), expires.isoformat(), _utc_now().isoformat()),
    )
    # Stands in for the SMS/WhatsApp provider until one is contracted.
    print("[OTP] %s -> %s (valid %ds)" % (mobile, code, settings.otp_ttl_seconds), flush=True)
    out: Dict[str, Any] = {"sent": True, "mobile": mobile}
    if settings.expose_otp:
        out["dev_otp"] = code
    return out


def verify_otp(conn: sqlite3.Connection, mobile: str, code: str) -> Dict[str, Any]:
    mobile = normalise_mobile(mobile)
    row = conn.execute("SELECT * FROM auth_otps WHERE mobile = ?", (mobile,)).fetchone()
    if row is None:
        raise PermissionDenied("request a code first")
    if _dt.datetime.fromisoformat(row["expires_at"]) < _utc_now():
        conn.execute("DELETE FROM auth_otps WHERE mobile = ?", (mobile,))
        raise PermissionDenied("this code has expired, request a new one")
    if row["attempts"] >= settings.otp_max_attempts:
        conn.execute("DELETE FROM auth_otps WHERE mobile = ?", (mobile,))
        raise PermissionDenied("too many attempts, request a new code")

    if not hmac.compare_digest(row["code_hash"], _hash_code(mobile, (code or "").strip())):
        conn.execute(
            "UPDATE auth_otps SET attempts = attempts + 1 WHERE mobile = ?", (mobile,))
        raise PermissionDenied("incorrect code")

    # Correct: burn it so the same code cannot be replayed.
    conn.execute("DELETE FROM auth_otps WHERE mobile = ?", (mobile,))

    user = conn.execute(
        "SELECT id, role, name, parent_id, status FROM users WHERE mobile = ?", (mobile,)
    ).fetchone()
    if user is None or user["status"] != "ACTIVE":
        raise PermissionDenied("this account is not active")

    return {
        "token": issue_token(user["id"], user["role"]),
        "user": profile_for(conn, user["id"]),
    }


def issue_token(user_id: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "iat": int(_utc_now().timestamp()),
        "exp": int((_utc_now() + _dt.timedelta(minutes=settings.token_ttl_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def actor_from_token(conn: sqlite3.Connection, token: str) -> Actor:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise PermissionDenied("session expired, please sign in again")
    except jwt.InvalidTokenError:
        raise PermissionDenied("invalid session token")
    # Reload from the database: a token issued before a suspension must not
    # keep working just because it has not expired yet.
    return Actor.load(conn, payload["sub"])


def profile_for(conn: sqlite3.Connection, user_id: str) -> Dict[str, Any]:
    user = conn.execute(
        "SELECT id, role, name, mobile, parent_id FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if user is None:
        raise PermissionDenied("unknown user")
    out = dict(user)
    if user["role"] == "CUSTOMER":
        cust = conn.execute(
            "SELECT id, retailer_id FROM customers WHERE user_id = ?", (user_id,)
        ).fetchone()
        out["customer_id"] = cust["id"] if cust else None
        out["retailer_id"] = cust["retailer_id"] if cust else None
    elif user["role"] in ("RETAILER", "STAFF"):
        out["retailer_id"] = user_id if user["role"] == "RETAILER" else user["parent_id"]
    return out


def resolve_customer_id(conn: sqlite3.Connection, actor: Actor) -> Optional[str]:
    row = conn.execute(
        "SELECT id FROM customers WHERE user_id = ?", (actor.user_id,)
    ).fetchone()
    return row["id"] if row else None
