"""Regressions for defects found reviewing the money path.

Each test here failed before the fix it guards. They are grouped separately
from the happy-path tests because these are the ones that cost money.
"""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.seed import (
    ADMIN_MOBILE,
    CUSTOMER_MOBILE,
    DISTRIBUTOR_MOBILE,
    RETAILER_MOBILE,
    seed,
)
from emi_locker.core import rupees


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


def tok(client, mobile):
    code = client.post("/auth/send-otp", json={"mobile": mobile}).json()["dev_otp"]
    out = client.post("/auth/verify-otp", json={"mobile": mobile, "code": code})
    return {"Authorization": "Bearer %s" % out.json()["token"]}


def my_finance(client, headers):
    return client.get("/me/finances", headers=headers).json()["finances"][0]


def schedule(client, headers, finance_id):
    return client.get("/finance/%s/emi-schedule" % finance_id,
                      headers=headers).json()["schedule"]


# --------------------------------------------------- underpayment (critical)


def test_a_rupee_cannot_clear_a_two_thousand_rupee_instalment(client):
    h = tok(client, CUSTOMER_MOBILE)
    finance_id = my_finance(client, h)["finance_id"]

    refused = client.post("/payments/create", headers=h,
                          json={"finance_id": finance_id, "amount_paise": 100})
    assert refused.status_code == 422
    assert "full instalment" in refused.json()["message"]

    assert schedule(client, h, finance_id)[0]["status"] == "UPCOMING"
    assert client.get("/finance/%s" % finance_id,
                      headers=h).json()["outstanding_paise"] == rupees(22000)


def test_overpaying_is_refused_too(client):
    h = tok(client, CUSTOMER_MOBILE)
    finance_id = my_finance(client, h)["finance_id"]
    refused = client.post("/payments/create", headers=h,
                          json={"finance_id": finance_id, "amount_paise": rupees(5000)})
    assert refused.status_code == 422


def test_cash_collection_keeps_the_same_rule(client):
    retailer = tok(client, RETAILER_MOBILE)
    customer = tok(client, CUSTOMER_MOBILE)
    finance_id = my_finance(client, customer)["finance_id"]
    refused = client.post("/collections", headers=retailer,
                          json={"finance_id": finance_id, "amount_paise": rupees(1500)})
    assert refused.status_code == 422
    assert "full instalment" in refused.json()["message"]


# ------------------------------------------- cross-account payment (critical)


def test_a_customer_cannot_settle_another_customers_instalment(client):
    """Quoting a foreign instalment id used to mark that instalment paid."""
    customer = tok(client, CUSTOMER_MOBILE)
    admin = tok(client, ADMIN_MOBILE)
    mine = my_finance(client, customer)["finance_id"]

    others = [f for f in client.get("/admin/finances", headers=admin).json()["finances"]
              if f["id"] != mine]
    assert others, "seed should carry a second finance account"
    foreign = others[0]
    foreign_emi = schedule(client, admin, foreign["id"])[0]["id"]

    refused = client.post("/payments/create", headers=customer, json={
        "finance_id": mine, "emi_id": foreign_emi, "amount_paise": rupees(2000)})
    assert refused.status_code == 422
    assert "does not belong to finance" in refused.json()["message"]

    assert schedule(client, admin, foreign["id"])[0]["status"] == "UPCOMING"


def test_an_instalment_cannot_be_charged_for_twice(client):
    h = tok(client, CUSTOMER_MOBILE)
    finance_id = my_finance(client, h)["finance_id"]
    first = schedule(client, h, finance_id)[0]

    created = client.post("/payments/create", headers=h, json={
        "finance_id": finance_id, "emi_id": first["id"],
        "amount_paise": first["amount_paise"]})
    client.post("/mock-gateway/pay", headers=h,
                json={"payment_id": created.json()["payment_id"]})
    assert schedule(client, h, finance_id)[0]["status"] == "PAID"

    again = client.post("/payments/create", headers=h, json={
        "finance_id": finance_id, "emi_id": first["id"],
        "amount_paise": first["amount_paise"]})
    assert again.status_code == 422
    assert "already paid" in again.json()["message"]


# ------------------------------------------------------ device restore wiring


def test_paying_the_arrears_raises_a_restore_command(client):
    """Section 14: a successful payment re-checks the balance and lifts the
    restriction. The payment path has to raise that command itself - it used
    to exist only as a function nothing called.

    The device is put into RESTRICTED directly, standing in for an EMM that
    acknowledged the restrict command. With no provider configured the default
    adapter reports failure and never sets that status, so there is no way to
    reach this state through the API alone.
    """
    admin = tok(client, ADMIN_MOBILE)
    customer = tok(client, CUSTOMER_MOBILE)
    finance_id = my_finance(client, customer)["finance_id"]
    device_id = client.get("/finance/%s" % finance_id,
                           headers=customer).json()["device"]["id"]

    from emi_locker.db import file_db, tx
    conn = file_db(client.app.state.db_path, same_thread=False)
    with tx(conn):
        conn.execute("UPDATE devices SET status = 'RESTRICTED' WHERE id = ?",
                     (device_id,))
    conn.close()

    before = client.get("/devices/%s/commands" % device_id, headers=admin).json()["commands"]
    assert [c for c in before if c["command"] in ("RESTORE", "RELEASE")] == []

    # One instalment is enough: the balance is re-checked on every payment.
    due = client.get("/finance/%s" % finance_id, headers=customer).json()["next_due"]
    created = client.post("/payments/create", headers=customer, json={
        "finance_id": finance_id, "emi_id": due["id"],
        "amount_paise": due["amount_paise"]})
    applied = client.post("/mock-gateway/pay", headers=customer,
                          json={"payment_id": created.json()["payment_id"]})
    assert applied.json()["status"] == "SUCCESS"

    after = client.get("/devices/%s/commands" % device_id, headers=admin).json()["commands"]
    restores = [c for c in after if c["command"] == "RESTORE"]
    assert restores, "paying with nothing overdue must raise a restore command"
    assert restores[0]["reason"] == "payment received, no instalment overdue"

    # With no provider configured the attempt is recorded as failed rather
    # than pretended to have worked, and the device stays restricted.
    assert restores[0]["status"] == "FAILED"
    assert client.get("/admin/devices", headers=admin).json()["devices"]


def test_a_payment_that_leaves_arrears_does_not_restore(client):
    admin = tok(client, ADMIN_MOBILE)
    customer = tok(client, CUSTOMER_MOBILE)
    finance_id = my_finance(client, customer)["finance_id"]
    device_id = client.get("/finance/%s" % finance_id,
                           headers=customer).json()["device"]["id"]

    import datetime as dt

    from emi_locker.db import file_db, tx
    from emi_locker.lifecycle import run_daily_status_sweep
    conn = file_db(client.app.state.db_path, same_thread=False)
    with tx(conn):
        conn.execute("UPDATE devices SET status = 'RESTRICTED' WHERE id = ?",
                     (device_id,))
        # Far enough ahead that several instalments are past their grace.
        run_daily_status_sweep(conn, None, as_of=dt.date(2027, 2, 1))
    conn.close()

    due = client.get("/finance/%s" % finance_id, headers=customer).json()["next_due"]
    created = client.post("/payments/create", headers=customer, json={
        "finance_id": finance_id, "emi_id": due["id"],
        "amount_paise": due["amount_paise"]})
    client.post("/mock-gateway/pay", headers=customer,
                json={"payment_id": created.json()["payment_id"]})

    after = client.get("/devices/%s/commands" % device_id, headers=admin).json()["commands"]
    assert [c for c in after if c["command"] == "RESTORE"] == [], \
        "instalments are still overdue, so nothing should be restored"


# ------------------------------------------------- unusable allocated quota


def test_quota_allocated_with_no_backing_licence_is_refused(client):
    """It used to be credited, shown as available, and rejected on every use."""
    admin = tok(client, ADMIN_MOBILE)
    dist = client.post("/admin/users", headers=admin, json={
        "role": "DISTRIBUTOR", "name": "Direct Dist", "mobile": "9000000077"}).json()
    retailer = client.post("/admin/users", headers=admin, json={
        "role": "RETAILER", "name": "Direct Shop", "mobile": "9000000078",
        "parent_id": dist["user_id"]}).json()

    refused = client.post("/licenses/allocate", headers=admin,
                          json={"to_owner": retailer["user_id"], "quota": 10})
    assert refused.status_code == 409
    assert "licence" in refused.json()["message"]

    shop = tok(client, "9000000078")
    assert client.get("/licenses/wallet", headers=shop).json()["available"] == 0


def test_issuing_a_licence_is_the_supported_way_to_grant_quota(client):
    admin = tok(client, ADMIN_MOBILE)
    dist = client.post("/admin/users", headers=admin, json={
        "role": "DISTRIBUTOR", "name": "Direct Dist 2", "mobile": "9000000081"}).json()
    retailer = client.post("/admin/users", headers=admin, json={
        "role": "RETAILER", "name": "Direct Shop 2", "mobile": "9000000082",
        "parent_id": dist["user_id"]}).json()

    plans = client.get("/admin/plans", headers=admin).json()["plans"]
    business = next(p for p in plans if p["name"] == "BUSINESS")
    issued = client.post("/admin/licenses/generate", headers=admin, json={
        "plan_id": business["id"], "owner_type": "RETAILER",
        "owner_id": retailer["user_id"]})
    assert issued.status_code == 201

    shop = tok(client, "9000000082")
    assert client.get("/licenses/wallet", headers=shop).json()["available"] == business["quota"]

    customer = client.post("/retailer/customers", headers=shop,
                           json={"name": "Works", "mobile": "9555577777"}).json()
    for consent in ("TERMS", "PRIVACY", "DEVICE_MANAGEMENT"):
        client.post("/retailer/customers/%s/consents" % customer["customer_id"],
                    headers=shop, json={"consent_type": consent})
    created = client.post("/finance", headers=shop, json={
        "customer_id": customer["customer_id"], "imei": "860321035678902",
        "product_price": rupees(10000), "down_payment": rupees(2000),
        "tenure_months": 5})
    assert created.status_code == 201, created.text


# ------------------------------------------------------- account enumeration


def test_send_otp_answers_identically_for_known_and_unknown_numbers(client, monkeypatch):
    """With the local OTP echo off, the two must be indistinguishable."""
    from backend.app import auth as auth_module
    monkeypatch.setattr(type(auth_module.settings), "expose_otp", property(lambda _: False))

    known_first = client.post("/auth/send-otp", json={"mobile": DISTRIBUTOR_MOBILE})
    known_again = client.post("/auth/send-otp", json={"mobile": DISTRIBUTOR_MOBILE})
    unknown_first = client.post("/auth/send-otp", json={"mobile": "9111100000"})
    unknown_again = client.post("/auth/send-otp", json={"mobile": "9111100000"})

    for response in (known_first, known_again, unknown_first, unknown_again):
        assert response.status_code == 200, response.text
        assert response.json() == {"sent": True, "mobile": response.json()["mobile"]}

    assert known_again.status_code == unknown_again.status_code


# ---------------------------------------------- idempotency key namespacing


def test_two_retailers_using_the_same_idempotency_key_do_not_collide(client):
    """A client-chosen key used to be global.

    The second retailer was handed the first one's finance record - id,
    schedule and wallet - and their own request was silently never performed.
    """
    from backend.seed import RETAILER2_MOBILE

    first = tok(client, RETAILER_MOBILE)
    second = tok(client, RETAILER2_MOBILE)
    key = {"idempotency-key": "same-key-from-two-shops"}

    def create(headers, mobile, imei):
        customer = client.post("/retailer/customers", headers=headers,
                               json={"name": "Probe Customer", "mobile": mobile}).json()
        for consent in ("TERMS", "PRIVACY", "DEVICE_MANAGEMENT"):
            client.post("/retailer/customers/%s/consents" % customer["customer_id"],
                        headers=headers, json={"consent_type": consent})
        return client.post("/finance", headers=dict(headers, **key), json={
            "customer_id": customer["customer_id"], "imei": imei,
            "product_price": rupees(20000), "down_payment": rupees(5000),
            "tenure_months": 5})

    a = create(first, "9555511111", "356938035643809")
    b = create(second, "9555522222", "860321035678902")

    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["finance_id"] != b.json()["finance_id"]

    # Each retailer can read back the account they actually created.
    assert client.get("/finance/%s" % a.json()["finance_id"],
                      headers=first).status_code == 200
    assert client.get("/finance/%s" % b.json()["finance_id"],
                      headers=second).status_code == 200
    # And still cannot read the other's.
    assert client.get("/finance/%s" % a.json()["finance_id"],
                      headers=second).status_code == 403


def test_the_same_retailer_still_gets_idempotency(client):
    headers = tok(client, RETAILER_MOBILE)
    customer = client.post("/retailer/customers", headers=headers,
                           json={"name": "Retry Customer", "mobile": "9555533333"}).json()
    for consent in ("TERMS", "PRIVACY", "DEVICE_MANAGEMENT"):
        client.post("/retailer/customers/%s/consents" % customer["customer_id"],
                    headers=headers, json={"consent_type": consent})
    body = {"customer_id": customer["customer_id"], "imei": "356938035643809",
            "product_price": rupees(20000), "down_payment": rupees(5000),
            "tenure_months": 5}
    key = {"idempotency-key": "one-shop-retrying"}

    first = client.post("/finance", headers=dict(headers, **key), json=body)
    second = client.post("/finance", headers=dict(headers, **key), json=body)
    assert first.json()["finance_id"] == second.json()["finance_id"]
