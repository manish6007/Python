"""The Distributor and Admin surfaces: scoping, stock control and settings."""
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
    RETAILER2_MOBILE,
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
    code = client.post("/auth/send-otp", json={"mobile": mobile}).json()["dev_otp"]
    out = client.post("/auth/verify-otp", json={"mobile": mobile, "code": code})
    assert out.status_code == 200, out.text
    return out.json()


def auth(token):
    return {"Authorization": "Bearer %s" % token}


def tok(client, mobile):
    return auth(login(client, mobile)["token"])


# ----------------------------------------------------------------- distributor


def test_distributor_dashboard_covers_its_whole_network(client):
    h = tok(client, DISTRIBUTOR_MOBILE)
    body = client.get("/distributor/dashboard", headers=h).json()
    assert body["retailers"] == 2
    assert body["customers"] == 3
    assert body["active_finance"] == 2
    # 500 bought, 150 pushed down to two retailers.
    assert body["wallet"]["available"] == 350
    assert body["allocated_to_retailers"] == 150
    assert body["activations_used_downstream"] == 2
    assert body["outstanding_paise"] == rupees(22000) + rupees(14000)


def test_distributor_retailer_list_shows_stock_and_money(client):
    h = tok(client, DISTRIBUTOR_MOBILE)
    rows = client.get("/distributor/retailers", headers=h).json()["retailers"]
    assert {r["name"] for r in rows} == {"Sharma Mobiles", "Verma Telecom"}
    sharma = next(r for r in rows if r["name"] == "Sharma Mobiles")
    assert sharma["available_quota"] == 99
    assert sharma["customers"] == 2
    assert sharma["outstanding_paise"] == rupees(22000)


def test_distributor_can_allocate_more_quota_and_it_is_idempotent(client):
    h = tok(client, DISTRIBUTOR_MOBILE)
    rows = client.get("/distributor/retailers", headers=h).json()["retailers"]
    target = next(r for r in rows if r["name"] == "Verma Telecom")

    for _ in range(2):
        out = client.post("/distributor/allocate",
                          headers=dict(h, **{"idempotency-key": "alloc-app-1"}),
                          json={"to_owner": target["id"], "quota": 25})
        assert out.status_code == 201, out.text

    after = client.get("/distributor/retailers", headers=h).json()["retailers"]
    verma = next(r for r in after if r["name"] == "Verma Telecom")
    assert verma["total_quota"] == 75
    assert client.get("/distributor/dashboard", headers=h).json()[
        "wallet"]["available"] == 325


def test_distributor_cannot_allocate_more_than_it_holds(client):
    h = tok(client, DISTRIBUTOR_MOBILE)
    rows = client.get("/distributor/retailers", headers=h).json()["retailers"]
    out = client.post("/distributor/allocate", headers=h,
                      json={"to_owner": rows[0]["id"], "quota": 10_000})
    assert out.status_code == 409
    assert out.json()["error"] == "INSUFFICIENT_QUOTA"


def test_distributor_cannot_reach_another_networks_retailer(client):
    """A second distributor must not be able to allocate into, or read, a
    retailer that is not theirs."""
    admin = tok(client, ADMIN_MOBILE)
    created = client.post("/admin/users", headers=admin, json={
        "role": "DISTRIBUTOR", "name": "South Distributor", "mobile": "9000000009"})
    assert created.status_code == 201

    mine = client.get("/distributor/retailers",
                      headers=tok(client, DISTRIBUTOR_MOBILE)).json()["retailers"]

    rival = tok(client, "9000000009")
    assert client.get("/distributor/retailers", headers=rival).json()["retailers"] == []

    blocked = client.get("/distributor/retailers/%s" % mine[0]["id"], headers=rival)
    assert blocked.status_code == 403

    blocked = client.post("/distributor/allocate", headers=rival,
                          json={"to_owner": mine[0]["id"], "quota": 1})
    assert blocked.status_code == 403


def test_retailer_cannot_open_the_distributor_app(client):
    h = tok(client, RETAILER_MOBILE)
    assert client.get("/distributor/dashboard", headers=h).status_code == 403
    assert client.get("/distributor/retailers", headers=h).status_code == 403


def test_distributor_overdue_is_limited_to_its_own_retailers(client):
    h = tok(client, DISTRIBUTOR_MOBILE)
    client.post("/admin/run-daily-sweep", headers=tok(client, ADMIN_MOBILE))
    body = client.get("/distributor/overdue", headers=h).json()
    assert "rows" in body and "total_paise" in body
    for row in body["rows"]:
        assert row["retailer_name"] in {"Sharma Mobiles", "Verma Telecom"}


def test_distributor_sees_its_own_licences_only(client):
    h = tok(client, DISTRIBUTOR_MOBILE)
    licences = client.get("/distributor/licenses", headers=h).json()["licenses"]
    assert len(licences) == 1
    assert licences[0]["quota"] == 500
    assert licences[0]["key_masked"].startswith("*")


# --------------------------------------------------------------------- admin


def test_admin_network_is_a_tree_of_distributors_and_retailers(client):
    h = tok(client, ADMIN_MOBILE)
    body = client.get("/admin/network", headers=h).json()
    assert len(body["distributors"]) == 1
    assert {r["name"] for r in body["distributors"][0]["retailers"]} == {
        "Sharma Mobiles", "Verma Telecom"}


def test_admin_creates_a_distributor_and_a_retailer_under_it(client):
    h = tok(client, ADMIN_MOBILE)
    dist = client.post("/admin/users", headers=h, json={
        "role": "DISTRIBUTOR", "name": "West Distributor", "mobile": "9000000011"})
    assert dist.status_code == 201
    retailer = client.post("/admin/users", headers=h, json={
        "role": "RETAILER", "name": "New Shop", "mobile": "9000000012",
        "parent_id": dist.json()["user_id"]})
    assert retailer.status_code == 201

    body = client.get("/admin/network", headers=h).json()
    west = next(d for d in body["distributors"] if d["name"] == "West Distributor")
    assert [r["name"] for r in west["retailers"]] == ["New Shop"]


def test_a_retailer_cannot_be_parented_to_another_retailer(client):
    h = tok(client, ADMIN_MOBILE)
    retailers = client.get("/distributor/retailers",
                           headers=tok(client, DISTRIBUTOR_MOBILE)).json()["retailers"]
    out = client.post("/admin/users", headers=h, json={
        "role": "RETAILER", "name": "Bad Parent", "mobile": "9000000013",
        "parent_id": retailers[0]["id"]})
    assert out.status_code == 422
    assert "distributor" in out.json()["message"]


def test_suspending_an_account_invalidates_its_existing_token(client):
    """Not just future logins - the token they are already holding."""
    retailer_headers = tok(client, RETAILER_MOBILE)
    assert client.get("/retailer/dashboard", headers=retailer_headers).status_code == 200

    admin = tok(client, ADMIN_MOBILE)
    network = client.get("/admin/network", headers=admin).json()
    sharma = next(r for r in network["distributors"][0]["retailers"]
                  if r["name"] == "Sharma Mobiles")
    out = client.post("/admin/users/%s/status" % sharma["id"], headers=admin,
                      json={"status": "SUSPENDED", "reason": "cash reconciliation"})
    assert out.status_code == 200

    blocked = client.get("/retailer/dashboard", headers=retailer_headers)
    assert blocked.status_code == 403
    assert "SUSPENDED" in blocked.json()["message"]


def test_admin_accounts_cannot_be_suspended_from_the_panel(client):
    h = tok(client, ADMIN_MOBILE)
    me = client.get("/auth/me", headers=h).json()
    out = client.post("/admin/users/%s/status" % me["id"], headers=h,
                      json={"status": "SUSPENDED", "reason": "oops"})
    assert out.status_code == 403


def test_admin_issues_a_licence_and_the_key_is_shown_once(client):
    h = tok(client, ADMIN_MOBILE)
    plans = client.get("/admin/plans", headers=h).json()["plans"]
    business = next(p for p in plans if p["name"] == "BUSINESS")

    issued = client.post("/admin/licenses/generate", headers=h, json={
        "plan_id": business["id"], "owner_type": "RETAILER"})
    assert issued.status_code == 201
    raw_key = issued.json()["key"]
    assert len(raw_key) > 10

    listed = client.get("/admin/licenses", headers=h).json()["licenses"]
    mine = next(lic for lic in listed if lic["id"] == issued.json()["license_id"])
    assert mine["status"] == "AVAILABLE"
    # The listing shows a masked key and never the real one.
    assert raw_key not in str(listed)
    assert mine["key_masked"].count("*") > 0

    # And it works: a retailer can claim it.
    retailer = tok(client, RETAILER2_MOBILE)
    redeemed = client.post("/licenses/redeem", headers=retailer, json={"key": raw_key})
    assert redeemed.status_code == 200
    assert redeemed.json()["wallet"]["total"] == 50 + business["quota"]


def test_admin_can_suspend_a_licence_and_stop_new_activations(client):
    h = tok(client, ADMIN_MOBILE)
    licences = client.get("/admin/licenses", headers=h).json()["licenses"]
    active = next(lic for lic in licences if lic["status"] == "ACTIVE")
    out = client.post("/admin/licenses/%s/status" % active["id"], headers=h,
                      json={"status": "SUSPENDED", "reason": "payment reversed"})
    assert out.status_code == 200

    # The retailer it backs can no longer activate a device.
    retailer = tok(client, RETAILER_MOBILE)
    created = client.post("/retailer/customers", headers=retailer,
                          json={"name": "Blocked", "mobile": "9555512345"})
    customer_id = created.json()["customer_id"]
    for consent in ("TERMS", "PRIVACY", "DEVICE_MANAGEMENT"):
        client.post("/retailer/customers/%s/consents" % customer_id, headers=retailer,
                    json={"consent_type": consent})
    refused = client.post("/finance", headers=retailer, json={
        "customer_id": customer_id, "imei": "860321035678902",
        "product_price": rupees(10000), "down_payment": rupees(2000),
        "tenure_months": 5})
    assert refused.status_code == 409
    assert refused.json()["error"] == "LICENSE_INVALID"


def test_admin_lists_the_whole_book(client):
    h = tok(client, ADMIN_MOBILE)
    assert len(client.get("/admin/customers", headers=h).json()["customers"]) == 3
    assert len(client.get("/admin/finances", headers=h).json()["finances"]) == 2
    assert len(client.get("/admin/devices", headers=h).json()["devices"]) == 2
    active = client.get("/admin/finances?status=ACTIVE", headers=h).json()["finances"]
    assert len(active) == 2
    assert client.get("/admin/finances?status=COMPLETED",
                      headers=h).json()["finances"] == []


def test_admin_customer_search_matches_name_and_mobile(client):
    h = tok(client, ADMIN_MOBILE)
    by_name = client.get("/admin/customers?q=Ramesh", headers=h).json()["customers"]
    assert len(by_name) == 1 and by_name[0]["name"] == "Ramesh Kumar"
    by_mobile = client.get("/admin/customers?q=9876543212",
                           headers=h).json()["customers"]
    assert len(by_mobile) == 1 and by_mobile[0]["name"] == "Imran Sheikh"


def test_payments_listing_reflects_a_real_payment(client):
    customer = tok(client, CUSTOMER_MOBILE)
    finance_id = client.get("/me/finances", headers=customer).json()[
        "finances"][0]["finance_id"]
    created = client.post("/payments/create", headers=customer,
                          json={"finance_id": finance_id, "amount_paise": rupees(2000)})
    client.post("/mock-gateway/pay", headers=customer,
                json={"payment_id": created.json()["payment_id"]})

    admin = tok(client, ADMIN_MOBILE)
    payments = client.get("/admin/payments", headers=admin).json()["payments"]
    assert len(payments) == 1
    assert payments[0]["status"] == "SUCCESS"
    assert payments[0]["customer_name"] == "Ramesh Kumar"
    assert payments[0]["receipt_number"]


# ------------------------------------------------------- settings and commission


def test_commission_reports_nothing_until_a_rate_is_configured(client):
    h = tok(client, ADMIN_MOBILE)
    body = client.get("/reports/commission", headers=h).json()
    assert body["rules"]["configured"] is False
    assert body["total_paise"] == 0
    assert all(r["commission_paise"] == 0 for r in body["rows"])


def test_setting_a_rate_produces_commission(client):
    h = tok(client, ADMIN_MOBILE)
    out = client.put("/admin/settings", headers=h, json={
        "key": "commission.retailer_per_activation_paise", "value": rupees(150)})
    assert out.status_code == 200

    body = client.get("/reports/commission", headers=h).json()
    assert body["rules"]["configured"] is True
    retailers = [r for r in body["rows"] if r["role"] == "RETAILER"]
    # Two activations across the network, at Rs.150 each.
    assert sum(r["commission_paise"] for r in retailers) == rupees(300)


def test_percentage_commission_uses_basis_points_not_floats(client):
    h = tok(client, ADMIN_MOBILE)
    client.put("/admin/settings", headers=h, json={
        "key": "commission.distributor_percent_of_financed_bp", "value": 250})  # 2.5%

    body = client.get("/reports/commission", headers=h).json()
    distributors = [r for r in body["rows"] if r["role"] == "DISTRIBUTOR"]
    # The distributor itself consumed no activations, so it earns nothing on
    # its own line; the rate applies to what it activated directly.
    assert all(isinstance(r["commission_paise"], int) for r in distributors)


def test_a_distributor_sees_only_its_own_commission_lines(client):
    admin = tok(client, ADMIN_MOBILE)
    client.put("/admin/settings", headers=admin, json={
        "key": "commission.retailer_per_activation_paise", "value": rupees(100)})
    client.post("/admin/users", headers=admin, json={
        "role": "DISTRIBUTOR", "name": "Other Dist", "mobile": "9000000021"})

    h = tok(client, DISTRIBUTOR_MOBILE)
    rows = client.get("/distributor/commission", headers=h).json()["rows"]
    names = {r["name"] for r in rows}
    assert "Other Dist" not in names
    assert names <= {"North Distributor", "Sharma Mobiles", "Verma Telecom"}


def test_unknown_or_malformed_settings_are_rejected(client):
    h = tok(client, ADMIN_MOBILE)
    assert client.put("/admin/settings", headers=h, json={
        "key": "commission.made_up", "value": 1}).status_code == 422
    assert client.put("/admin/settings", headers=h, json={
        "key": "commission.retailer_per_activation_paise",
        "value": "lots"}).status_code == 422
    assert client.put("/admin/settings", headers=h, json={
        "key": "commission.retailer_per_activation_paise",
        "value": -5}).status_code == 422


def test_settings_are_admin_only(client):
    h = tok(client, DISTRIBUTOR_MOBILE)
    assert client.get("/admin/settings", headers=h).status_code == 403
    assert client.put("/admin/settings", headers=h, json={
        "key": "business.name", "value": "Hijacked"}).status_code == 403


def test_audit_trail_is_readable_and_records_admin_actions(client):
    h = tok(client, ADMIN_MOBILE)
    client.put("/admin/settings", headers=h,
               json={"key": "business.support_mobile", "value": "9000000099"})
    events = client.get("/admin/audit?action=settings", headers=h).json()["events"]
    assert events
    assert events[0]["action"] == "settings.change"
    assert events[0]["actor_name"] == "Ashish Enterprises"


def test_audit_trail_is_not_visible_to_a_distributor(client):
    h = tok(client, DISTRIBUTOR_MOBILE)
    assert client.get("/admin/audit", headers=h).status_code == 403
