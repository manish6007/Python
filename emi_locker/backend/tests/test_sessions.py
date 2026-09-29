"""Session length, and the ability to end a session before it expires."""
from __future__ import annotations

import os
import tempfile

import jwt
import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.seed import (
    ADMIN_MOBILE,
    CUSTOMER_MOBILE,
    DISTRIBUTOR_MOBILE,
    RETAILER_MOBILE,
    seed,
)


@pytest.fixture()
def client():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    seed(path)
    with TestClient(create_app(path)) as c:
        yield c
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.unlink(path + suffix)


def login(client, mobile):
    code = client.post("/auth/send-otp", json={"mobile": mobile}).json()["dev_otp"]
    return client.post("/auth/verify-otp",
                       json={"mobile": mobile, "code": code}).json()


def auth(session):
    return {"Authorization": "Bearer %s" % session["token"]}


THIRTY_DAYS_MIN = 30 * 24 * 60
TWELVE_HOURS_MIN = 12 * 60


# ------------------------------------------------------------ session length


def test_app_users_get_a_long_session(client):
    """The OTP bill is driven by how often people sign in again."""
    for mobile in (CUSTOMER_MOBILE, RETAILER_MOBILE, DISTRIBUTOR_MOBILE):
        session = login(client, mobile)
        assert session["session_minutes"] == THIRTY_DAYS_MIN, mobile


def test_the_admin_panel_gets_a_short_one(client):
    session = login(client, ADMIN_MOBILE)
    assert session["session_minutes"] == TWELVE_HOURS_MIN


def test_the_expiry_in_the_token_matches_what_was_advertised(client):
    session = login(client, CUSTOMER_MOBILE)
    claims = jwt.decode(session["token"], Settings().jwt_secret, algorithms=["HS256"])
    assert (claims["exp"] - claims["iat"]) == THIRTY_DAYS_MIN * 60


def test_session_lengths_are_configurable(monkeypatch):
    monkeypatch.setenv("EMI_APP_SESSION_MIN", "1440")
    monkeypatch.setenv("EMI_ADMIN_SESSION_MIN", "60")
    settings = Settings()
    assert settings.session_minutes_for("CUSTOMER") == 1440
    assert settings.session_minutes_for("SUPER_ADMIN") == 60


# --------------------------------------------------------------- revocation


def test_a_customer_can_end_every_session_after_losing_a_handset(client):
    stolen = login(client, CUSTOMER_MOBILE)
    assert client.get("/me/finances", headers=auth(stolen)).status_code == 200

    # Signing in elsewhere and ending all sessions kills the stolen one.
    replacement = login(client, CUSTOMER_MOBILE)
    out = client.post("/auth/sign-out-everywhere", headers=auth(replacement))
    assert out.status_code == 200

    blocked = client.get("/me/finances", headers=auth(stolen))
    assert blocked.status_code == 403
    assert "sign in again" in blocked.json()["message"]

    # The token used to do it is ended too, so there is no session left behind.
    assert client.get("/me/finances", headers=auth(replacement)).status_code == 403

    # And signing in afresh works normally.
    assert client.get("/me/finances",
                      headers=auth(login(client, CUSTOMER_MOBILE))).status_code == 200


def test_suspending_an_account_does_not_leave_revivable_tokens(client):
    """Suspension already blocked a live token. Reactivating used to revive it.

    With month-long sessions that would hand a dismissed retailer their access
    back the moment the account was re-enabled for any reason.
    """
    retailer = login(client, RETAILER_MOBILE)
    assert client.get("/retailer/dashboard", headers=auth(retailer)).status_code == 200

    admin = auth(login(client, ADMIN_MOBILE))
    network = client.get("/admin/network", headers=admin).json()
    sharma = next(r for r in network["distributors"][0]["retailers"]
                  if r["name"] == "Sharma Mobiles")

    client.post("/admin/users/%s/status" % sharma["id"], headers=admin,
                json={"status": "SUSPENDED", "reason": "cash reconciliation"})
    assert client.get("/retailer/dashboard", headers=auth(retailer)).status_code == 403

    client.post("/admin/users/%s/status" % sharma["id"], headers=admin,
                json={"status": "ACTIVE", "reason": "resolved"})

    # The old token stays dead; they have to sign in again.
    revived = client.get("/retailer/dashboard", headers=auth(retailer))
    assert revived.status_code == 403
    assert client.get("/retailer/dashboard",
                      headers=auth(login(client, RETAILER_MOBILE))).status_code == 200


def test_a_forged_epoch_does_not_survive_the_signature(client):
    session = login(client, CUSTOMER_MOBILE)
    claims = jwt.decode(session["token"], Settings().jwt_secret, algorithms=["HS256"])
    claims["epoch"] = 99
    forged = jwt.encode(claims, "not-the-real-secret", algorithm="HS256")
    assert client.get("/me/finances",
                      headers={"Authorization": "Bearer %s" % forged}).status_code == 403


def test_sign_out_everywhere_needs_a_session_of_its_own(client):
    assert client.post("/auth/sign-out-everywhere").status_code == 403


# ---------------------------------------------------------------- migration


def test_an_older_database_gains_the_new_column_on_open():
    """CREATE TABLE IF NOT EXISTS leaves existing databases behind."""
    from emi_locker.db import connect, file_db, init_schema

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    try:
        conn = connect(path)
        init_schema(conn)
        conn.execute("ALTER TABLE users DROP COLUMN session_epoch")
        assert "session_epoch" not in {
            r[1] for r in conn.execute("PRAGMA table_info(users)")}
        conn.close()

        migrated = file_db(path)
        assert "session_epoch" in {
            r[1] for r in migrated.execute("PRAGMA table_info(users)")}
        migrated.close()
    finally:
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(path + suffix):
                os.unlink(path + suffix)
