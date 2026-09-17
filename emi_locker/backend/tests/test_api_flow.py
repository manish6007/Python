"""End-to-end tests over the real HTTP app, as the two Flutter apps will call it."""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.seed import (
    ADMIN_MOBILE,
    CUSTOMER2_MOBILE,
    CUSTOMER_MOBILE,
    DEMO_IMEI_2,
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


def login(client, mobile):
    sent = client.post("/auth/send-otp", json={"mobile": mobile})
    assert sent.status_code == 200, sent.text
    code = sent.json()["dev_otp"]
    out = client.post("/auth/verify-otp", json={"mobile": mobile, "code": code})
    assert out.status_code == 200, out.text
    return out.json()


def auth(token):
    return {"Authorization": "Bearer %s" % token}


# --------------------------------------------------------------------- login


def test_health_reports_local_mode(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["mock_gateway"] is True


def test_otp_login_returns_a_role(client):
    session = login(client, RETAILER_MOBILE)
    assert session["user"]["role"] == "RETAILER"
    assert session["user"]["retailer_id"] == session["user"]["id"]
    assert session["token"]


def test_customer_login_resolves_their_customer_record(client):
    session = login(client, CUSTOMER_MOBILE)
    assert session["user"]["role"] == "CUSTOMER"
    assert session["user"]["customer_id"].startswith("CUS-")


def test_wrong_code_is_rejected_and_counted(client):
    client.post("/auth/send-otp", json={"mobile": RETAILER_MOBILE})
    for _ in range(5):
        bad = client.post("/auth/verify-otp",
                          json={"mobile": RETAILER_MOBILE, "code": "000000"})
        assert bad.status_code == 403
    # The code is destroyed after too many attempts.
    again = client.post("/auth/verify-otp",
                        json={"mobile": RETAILER_MOBILE, "code": "000000"})
    assert again.status_code == 403
    assert "too many attempts" in again.json()["message"]

    # The burnt code is gone: even the correct one no longer works.
    fresh = client.post("/auth/verify-otp",
                        json={"mobile": RETAILER_MOBILE, "code": "123456"})
    assert "request a code first" in fresh.json()["message"]


def test_otp_is_single_use(client):
    sent = client.post("/auth/send-otp", json={"mobile": RETAILER_MOBILE}).json()
    code = sent["dev_otp"]
    assert client.post("/auth/verify-otp",
                       json={"mobile": RETAILER_MOBILE, "code": code}).status_code == 200
    replay = client.post("/auth/verify-otp", json={"mobile": RETAILER_MOBILE, "code": code})
    assert replay.status_code == 403


def test_unknown_mobile_does_not_reveal_itself(client):
    out = client.post("/auth/send-otp", json={"mobile": "9111111111"})
    assert out.status_code == 200
    assert out.json()["sent"] is True
    assert "dev_otp" not in out.json()


def test_endpoints_need_a_token(client):
    assert client.get("/retailer/dashboard").status_code == 403
    assert client.get("/me/finances").status_code == 403


def test_garbage_token_is_rejected(client):
    r = client.get("/retailer/dashboard", headers=auth("not.a.token"))
    assert r.status_code == 403


# ------------------------------------------------------------ retailer flows


def test_retailer_dashboard_shows_the_seeded_book(client):
    token = login(client, RETAILER_MOBILE)["token"]
    body = client.get("/retailer/dashboard", headers=auth(token)).json()
    assert body["customers"] == 2
    assert body["active_finance"] == 1
    assert body["outstanding_paise"] == rupees(22000)
    assert body["wallet"]["available"] == 99  # 100 allocated, 1 consumed by the seed


def test_retailer_creates_customer_captures_consent_and_finances_a_device(client):
    token = login(client, RETAILER_MOBILE)["token"]
    h = auth(token)

    created = client.post("/retailer/customers", headers=h,
                          json={"name": "Anil Verma", "mobile": "9555500001",
                                "address": "Ujjain"})
    assert created.status_code == 201, created.text
    customer_id = created.json()["customer_id"]

    detail = client.get("/retailer/customers/%s" % customer_id, headers=h).json()
    assert detail["missing_consents"] == ["TERMS", "PRIVACY", "DEVICE_MANAGEMENT"]

    # Finance is refused until every consent is on file.
    finance_body = {"customer_id": customer_id, "imei": DEMO_IMEI_2,
                    "product_price": rupees(24000), "down_payment": rupees(6000),
                    "tenure_months": 9, "model": "Redmi 14"}
    refused = client.post("/finance", headers=h, json=finance_body)
    assert refused.status_code == 403
    assert "consent" in refused.json()["message"].lower()

    for consent in ("TERMS", "PRIVACY", "DEVICE_MANAGEMENT"):
        client.post("/retailer/customers/%s/consents" % customer_id, headers=h,
                    json={"consent_type": consent, "doc_version": "v1"})

    quote = client.post("/finance/quote", headers=h,
                        json={"product_price": rupees(24000),
                              "down_payment": rupees(6000), "tenure_months": 9}).json()
    assert quote["financed_amount"] == rupees(18000)
    assert quote["emi_amount"] == rupees(2000)
    assert len(quote["schedule"]) == 9

    created = client.post("/finance", headers=dict(h, **{"idempotency-key": "app-req-1"}),
                          json=finance_body)
    assert created.status_code == 201, created.text
    finance = created.json()
    assert finance["emi_amount"] == rupees(2000)
    assert finance["activation"]["wallet"]["available"] == 98

    # The app retrying on a flaky connection must not create a second finance.
    again = client.post("/finance", headers=dict(h, **{"idempotency-key": "app-req-1"}),
                        json=finance_body)
    assert again.json()["finance_id"] == finance["finance_id"]

    dash = client.get("/retailer/dashboard", headers=h).json()
    assert dash["active_finance"] == 2
    assert dash["wallet"]["available"] == 98


def test_duplicate_imei_gives_a_readable_error(client):
    token = login(client, RETAILER_MOBILE)["token"]
    h = auth(token)
    created = client.post("/retailer/customers", headers=h,
                          json={"name": "Clash", "mobile": "9555500002"})
    customer_id = created.json()["customer_id"]
    for consent in ("TERMS", "PRIVACY", "DEVICE_MANAGEMENT"):
        client.post("/retailer/customers/%s/consents" % customer_id, headers=h,
                    json={"consent_type": consent})
    out = client.post("/finance", headers=h, json={
        "customer_id": customer_id, "imei": "490154203237518",
        "product_price": rupees(10000), "down_payment": rupees(2000), "tenure_months": 4})
    assert out.status_code == 409
    assert out.json()["error"] == "DUPLICATE_DEVICE"
    assert "already on live finance" in out.json()["message"]


def test_bad_imei_is_rejected_before_anything_is_created(client):
    token = login(client, RETAILER_MOBILE)["token"]
    h = auth(token)
    created = client.post("/retailer/customers", headers=h,
                          json={"name": "Bad IMEI", "mobile": "9555500003"})
    customer_id = created.json()["customer_id"]
    for consent in ("TERMS", "PRIVACY", "DEVICE_MANAGEMENT"):
        client.post("/retailer/customers/%s/consents" % customer_id, headers=h,
                    json={"consent_type": consent})
    out = client.post("/finance", headers=h, json={
        "customer_id": customer_id, "imei": "123456789012345",
        "product_price": rupees(10000), "down_payment": rupees(2000), "tenure_months": 4})
    assert out.status_code == 422
    assert "checksum" in out.json()["message"]


def test_duplicate_mobile_is_refused(client):
    token = login(client, RETAILER_MOBILE)["token"]
    h = auth(token)
    out = client.post("/retailer/customers", headers=h,
                      json={"name": "Copy", "mobile": CUSTOMER_MOBILE})
    assert out.status_code == 422
    assert "already registered" in out.json()["message"]


def test_retailer_collects_cash_and_gets_a_receipt(client):
    token = login(client, RETAILER_MOBILE)["token"]
    h = auth(token)
    customers = client.get("/retailer/customers", headers=h).json()["customers"]
    with_finance = [c for c in customers if c["finance_count"] > 0]
    assert len(with_finance) == 1
    detail = client.get("/retailer/customers/%s" % with_finance[0]["id"], headers=h).json()
    finance_id = detail["finances"][0]["id"]

    out = client.post("/collections", headers=dict(h, **{"idempotency-key": "cash-1"}),
                      json={"finance_id": finance_id, "amount_paise": rupees(2000)})
    assert out.status_code == 201, out.text
    assert out.json()["receipt_number"]

    # Double tap on the collect button.
    again = client.post("/collections", headers=dict(h, **{"idempotency-key": "cash-1"}),
                        json={"finance_id": finance_id, "amount_paise": rupees(2000)})
    assert again.json()["receipt_number"] == out.json()["receipt_number"]

    detail = client.get("/finance/%s" % finance_id, headers=h).json()
    assert detail["outstanding_paise"] == rupees(20000)


def test_cash_amount_must_match_the_instalment(client):
    token = login(client, RETAILER_MOBILE)["token"]
    h = auth(token)
    finance_id = client.get("/me/finances", headers=auth(
        login(client, CUSTOMER_MOBILE)["token"])).json()["finances"][0]["finance_id"]
    out = client.post("/collections", headers=h,
                      json={"finance_id": finance_id, "amount_paise": rupees(1500)})
    assert out.status_code == 422


def test_pending_collections_lists_what_to_chase(client):
    token = login(client, RETAILER_MOBILE)["token"]
    h = auth(token)
    client.post("/retailer/run-daily-sweep", headers=h)
    body = client.get("/retailer/collections/pending", headers=h).json()
    assert "pending" in body and "total_paise" in body


# ------------------------------------------------------------ customer flows


def test_customer_sees_only_their_own_finance(client):
    session = login(client, CUSTOMER_MOBILE)
    h = auth(session["token"])
    body = client.get("/me/finances", headers=h).json()
    assert len(body["finances"]) == 1
    finance = body["finances"][0]
    assert finance["outstanding_paise"] == rupees(22000)
    assert finance["next_due"]["seq"] == 1

    other = login(client, CUSTOMER2_MOBILE)
    assert client.get("/me/finances", headers=auth(other["token"])).json()["finances"] == []


def test_customer_cannot_open_someone_elses_finance(client):
    mine = login(client, CUSTOMER_MOBILE)
    finance_id = client.get("/me/finances", headers=auth(mine["token"])).json()[
        "finances"][0]["finance_id"]
    stranger = login(client, CUSTOMER2_MOBILE)
    out = client.get("/finance/%s" % finance_id, headers=auth(stranger["token"]))
    assert out.status_code == 403


def test_customer_cannot_reach_retailer_endpoints(client):
    token = login(client, CUSTOMER_MOBILE)["token"]
    assert client.get("/retailer/dashboard", headers=auth(token)).status_code == 403
    assert client.post("/retailer/customers", headers=auth(token),
                       json={"name": "X", "mobile": "9555500009"}).status_code == 403


def test_customer_pays_an_emi_through_the_verified_gateway_path(client):
    session = login(client, CUSTOMER_MOBILE)
    h = auth(session["token"])
    finance_id = client.get("/me/finances", headers=h).json()["finances"][0]["finance_id"]
    schedule = client.get("/finance/%s/emi-schedule" % finance_id, headers=h).json()
    first = schedule["schedule"][0]
    assert first["status"] == "UPCOMING"

    created = client.post("/payments/create", headers=h,
                          json={"finance_id": finance_id,
                                "amount_paise": first["amount_paise"]})
    assert created.status_code == 201, created.text
    payment_id = created.json()["payment_id"]

    # Creating the payment alone changes nothing - the app cannot mark it paid.
    still = client.get("/finance/%s/emi-schedule" % finance_id, headers=h).json()
    assert still["schedule"][0]["status"] == "UPCOMING"

    paid = client.post("/mock-gateway/pay", headers=h, json={"payment_id": payment_id})
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "SUCCESS"

    after = client.get("/finance/%s/emi-schedule" % finance_id, headers=h).json()
    assert after["schedule"][0]["status"] == "PAID"

    detail = client.get("/finance/%s" % finance_id, headers=h).json()
    assert detail["outstanding_paise"] == rupees(20000)

    receipt = client.get("/receipts/%s" % payment_id, headers=h).json()
    assert receipt["receipt_number"]
    assert receipt["customer_name"] == "Ramesh Kumar"
    assert receipt["amount_paise"] == rupees(2000)

    history = client.get("/me/payments", headers=h).json()["payments"]
    assert len(history) == 1 and history[0]["status"] == "SUCCESS"


def test_gateway_callback_replay_does_not_pay_twice(client):
    session = login(client, CUSTOMER_MOBILE)
    h = auth(session["token"])
    finance_id = client.get("/me/finances", headers=h).json()["finances"][0]["finance_id"]
    created = client.post("/payments/create", headers=h,
                          json={"finance_id": finance_id, "amount_paise": rupees(2000)})
    payment_id = created.json()["payment_id"]
    client.post("/mock-gateway/pay", headers=h, json={"payment_id": payment_id})
    again = client.post("/mock-gateway/pay", headers=h, json={"payment_id": payment_id})
    assert again.json()["status"] == "IGNORED"

    schedule = client.get("/finance/%s/emi-schedule" % finance_id, headers=h).json()
    paid = [r for r in schedule["schedule"] if r["status"] == "PAID"]
    assert len(paid) == 1


def test_unsigned_webhook_is_refused(client):
    session = login(client, CUSTOMER_MOBILE)
    h = auth(session["token"])
    finance_id = client.get("/me/finances", headers=h).json()["finances"][0]["finance_id"]
    created = client.post("/payments/create", headers=h,
                          json={"finance_id": finance_id, "amount_paise": rupees(2000)})
    payload = {"event_id": "forged-1", "payment_id": created.json()["payment_id"],
               "status": "SUCCESS", "amount_paise": rupees(2000)}
    out = client.post("/payments/webhook", json=payload,
                      headers={"x-signature": "not-a-signature"})
    assert out.status_code == 400
    assert out.json()["error"] == "PAYMENT_VERIFICATION_FAILED"

    schedule = client.get("/finance/%s/emi-schedule" % finance_id, headers=h).json()
    assert schedule["schedule"][0]["status"] == "UPCOMING"


def test_failed_payment_leaves_the_emi_unpaid(client):
    session = login(client, CUSTOMER_MOBILE)
    h = auth(session["token"])
    finance_id = client.get("/me/finances", headers=h).json()["finances"][0]["finance_id"]
    created = client.post("/payments/create", headers=h,
                          json={"finance_id": finance_id, "amount_paise": rupees(2000)})
    out = client.post("/mock-gateway/pay", headers=h,
                      json={"payment_id": created.json()["payment_id"],
                            "outcome": "FAILED"})
    assert out.json()["status"] == "FAILED"
    schedule = client.get("/finance/%s/emi-schedule" % finance_id, headers=h).json()
    assert schedule["schedule"][0]["status"] == "UPCOMING"


def test_paying_every_instalment_closes_the_account(client):
    session = login(client, CUSTOMER_MOBILE)
    h = auth(session["token"])
    finance_id = client.get("/me/finances", headers=h).json()["finances"][0]["finance_id"]
    for _ in range(11):
        created = client.post("/payments/create", headers=h,
                              json={"finance_id": finance_id, "amount_paise": rupees(2000)})
        client.post("/mock-gateway/pay", headers=h,
                    json={"payment_id": created.json()["payment_id"]})
    detail = client.get("/finance/%s" % finance_id, headers=h).json()
    assert detail["outstanding_paise"] == 0
    assert detail["status"] == "COMPLETED"

    cert = client.get("/me/closure/%s" % finance_id, headers=h).json()
    assert cert["no_dues"] is True

    # A completed account cannot be paid again.
    refused = client.post("/payments/create", headers=h,
                          json={"finance_id": finance_id, "amount_paise": rupees(2000)})
    assert refused.status_code == 403


# ---------------------------------------------------------------- admin/other


def test_admin_dashboard_is_admin_only(client):
    retailer = login(client, RETAILER_MOBILE)["token"]
    assert client.get("/reports/dashboard", headers=auth(retailer)).status_code == 403
    admin = login(client, ADMIN_MOBILE)["token"]
    body = client.get("/reports/dashboard", headers=auth(admin))
    assert body.status_code == 200
    # Two customers under Sharma Mobiles, one under Verma Telecom.
    assert body.json()["customers"] == 3


def test_distributor_sees_its_own_licence_utilisation(client):
    token = login(client, DISTRIBUTOR_MOBILE)["token"]
    rows = client.get("/reports/licenses", headers=auth(token)).json()["rows"]
    owners = {r["owner_id"] for r in rows}
    assert len(owners) == 3  # itself and its two retailers


def test_openapi_document_builds(client):
    """Guards against a malformed route or schema breaking /docs."""
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    paths = spec.json()["paths"]
    for expected in ("/auth/send-otp", "/finance", "/payments/create", "/me/finances",
                     "/collections", "/receipts/{payment_id}"):
        assert expected in paths, expected
