"""The HTTP surface honours auth, scoping and webhook verification."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from emi_locker import payments
from emi_locker.api import Api, serve
from emi_locker.core import rupees
from tests.helpers import SECRET, VALID_IMEI, build_world


@pytest.fixture()
def api():
    world = build_world()
    tokens = {
        "admin-token": world["admin_id"],
        "dist-token": world["dist_id"],
        "retailer-token": world["retailer_id"],
    }
    return Api(world["conn"], SECRET, tokens), world


def call(api, method, path, payload=None, token="retailer-token", headers=None):
    body = json.dumps(payload).encode() if payload is not None else b""
    hdrs = {"authorization": "Bearer %s" % token} if token else {}
    hdrs.update(headers or {})
    return api.dispatch(method, path, body, hdrs)


def test_request_without_a_token_is_rejected(api):
    api_obj, _ = api
    status, body = call(api_obj, "GET", "/reports/outstanding", token=None)
    assert status == 403
    assert body["error"] == "PERMISSION_DENIED"


def test_unknown_route_is_404(api):
    api_obj, _ = api
    status, _body = call(api_obj, "GET", "/nope")
    assert status == 404


def test_full_flow_over_http_handlers(api):
    api_obj, world = api
    status, cust = call(api_obj, "POST", "/customers", {
        "retailer_id": world["retailer_id"], "name": "Ramesh", "mobile": "9876543210"})
    assert status == 201
    customer_id = cust["customer_id"]

    status, detail = call(api_obj, "GET", "/customers/%s" % customer_id)
    assert status == 200
    assert detail["missing_consents"] == ["TERMS", "PRIVACY", "DEVICE_MANAGEMENT"]

    # Finance is refused while consent is missing.
    finance_payload = {
        "customer_id": customer_id, "imei": VALID_IMEI,
        "product_price": rupees(30000), "down_payment": rupees(8000), "tenure_months": 11,
    }
    status, body = call(api_obj, "POST", "/finance", finance_payload)
    assert status == 403 and "consent" in body["message"].lower()

    for consent in ("TERMS", "PRIVACY", "DEVICE_MANAGEMENT"):
        call(api_obj, "POST", "/customers/%s/consents" % customer_id,
             {"consent_type": consent, "doc_version": "v1"})

    status, fin = call(api_obj, "POST", "/finance", finance_payload,
                       headers={"idempotency-key": "req-1"})
    assert status == 201
    assert fin["emi_amount"] == rupees(2000)

    # The retried request returns the same finance, not a second one.
    status, again = call(api_obj, "POST", "/finance", finance_payload,
                         headers={"idempotency-key": "req-1"})
    assert again["finance_id"] == fin["finance_id"]

    status, sched = call(api_obj, "GET", "/finance/%s/emi-schedule" % fin["finance_id"])
    assert status == 200 and len(sched["schedule"]) == 11

    status, pay = call(api_obj, "POST", "/payments/create",
                       {"finance_id": fin["finance_id"], "amount_paise": rupees(2000)})
    assert status == 201

    body = json.dumps({"event_id": "e1", "payment_id": pay["payment_id"],
                       "status": "SUCCESS", "amount_paise": rupees(2000)}).encode()
    status, out = api_obj.dispatch("POST", "/payments/webhook", body,
                                   {"x-signature": "wrong"})
    assert status == 400 and out["error"] == "PAYMENT_VERIFICATION_FAILED"

    sig = payments.sign_payload(SECRET, body)
    status, out = api_obj.dispatch("POST", "/payments/webhook", body, {"x-signature": sig})
    assert status == 200 and out["status"] == "SUCCESS"

    # A gateway retry gets 200 so it stops resending, without paying twice.
    status, out = api_obj.dispatch("POST", "/payments/webhook", body, {"x-signature": sig})
    assert status == 200 and out["status"] == "IGNORED"

    status, summary = call(api_obj, "GET", "/finance/%s" % fin["finance_id"])
    assert summary["outstanding"] == rupees(20000)


def test_wallet_endpoint_is_per_token(api):
    api_obj, world = api
    _, retailer_wallet = call(api_obj, "GET", "/licenses/wallet", token="retailer-token")
    _, dist_wallet = call(api_obj, "GET", "/licenses/wallet", token="dist-token")
    assert retailer_wallet["owner_id"] == world["retailer_id"]
    assert dist_wallet["owner_id"] == world["dist_id"]
    assert retailer_wallet["available"] == 100


def test_retailer_cannot_reach_the_admin_dashboard(api):
    api_obj, _ = api
    status, body = call(api_obj, "GET", "/reports/dashboard", token="retailer-token")
    assert status == 403
    status, _ = call(api_obj, "GET", "/reports/dashboard", token="admin-token")
    assert status == 200


def test_malformed_json_is_a_400(api):
    api_obj, _ = api
    status, body = api_obj.dispatch("POST", "/customers", b"{not json",
                                    {"authorization": "Bearer retailer-token"})
    assert status == 400 and body["error"] == "BAD_JSON"


def test_server_boots_and_answers_over_a_socket():
    world = build_world(cross_thread=True)
    server = serve(world["conn"], SECRET,
                   {"retailer-token": world["retailer_id"]}, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        req = urllib.request.Request(
            "http://127.0.0.1:%d/licenses/wallet" % port,
            headers={"Authorization": "Bearer retailer-token"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
        assert data["available"] == 100

        bad = urllib.request.Request("http://127.0.0.1:%d/licenses/wallet" % port)
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(bad, timeout=5)
        assert exc.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
