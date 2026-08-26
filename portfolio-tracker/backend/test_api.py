"""Tests through HTTP, not around it.

Everything in main.py -- the CORS configuration, the host check, profile
selection from the cookie, the session lifecycle, the confirmation guards --
only exists on the request path, so calling the endpoint functions directly
proves none of it. These go through the app.
"""
import pytest
from fastapi.testclient import TestClient

import config
import db
import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_PATH", str(tmp_path / "app-config.json"))
    monkeypatch.delenv(config.ENV_DATA_DIR, raising=False)
    monkeypatch.setattr(db, "_engines", {})
    monkeypatch.setattr(db, "_factories", {})
    # base_url matters: the host check rejects anything that is not
    # loopback, and TestClient defaults to http://testserver.
    with TestClient(main.app, base_url="http://localhost:8000") as c:
        yield c


def as_profile(client, pid):
    """Point the client at a profile the way a browser does."""
    client.cookies.set("profile", pid)
    return client


# ---- the boundary that replaces having no login -------------------------
def test_another_website_cannot_read_the_portfolio(client):
    """Wildcard CORS would let any open tab fetch /api/summary."""
    r = client.get("/api/summary", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in {
        k.lower() for k in r.headers}


def test_a_cross_site_write_is_refused(client):
    """Sec-Fetch-Site is browser-set and cannot be forged by script."""
    r = client.post("/api/reset", json={"confirm": "ERASE"},
                    headers={"Origin": "https://evil.example",
                             "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_a_same_origin_write_still_works(client):
    r = client.post("/api/holdings",
                    json={"asset_class": "stock", "name": "S", "units": 1,
                          "avg_cost": 10},
                    headers={"Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200


def test_a_request_for_another_host_is_refused(client):
    """Closes DNS rebinding, which an origin check alone does not."""
    r = client.get("/api/summary", headers={"Host": "portfolio.evil.example"})
    assert r.status_code == 421


def test_loopback_hosts_are_allowed(client):
    for host in ("localhost:8000", "127.0.0.1:8000"):
        assert client.get("/api/summary",
                          headers={"Host": host}).status_code == 200


# ---- profiles, through the cookie that actually selects them ------------
def test_profiles_are_isolated_over_http(client):
    client.post("/api/profiles", json={"name": "Demo"})
    client.post("/api/holdings", json={"asset_class": "stock",
                                       "name": "My real stock",
                                       "units": 10, "avg_cost": 100})
    as_profile(client, "demo")
    assert client.get("/api/holdings").json() == []
    client.post("/api/holdings", json={"asset_class": "stock",
                                       "name": "Demo stock", "units": 1,
                                       "avg_cost": 5})
    assert [h["name"] for h in client.get("/api/holdings").json()] == [
        "Demo stock"]

    as_profile(client, "default")
    assert [h["name"] for h in client.get("/api/holdings").json()] == [
        "My real stock"]


def test_activating_a_profile_sets_the_cookie(client):
    client.post("/api/profiles", json={"name": "Demo"})
    r = client.post("/api/profiles/demo/activate")
    assert r.cookies.get("profile") == "demo"


def test_an_unknown_profile_cookie_falls_back(client):
    """A tab left open on a deleted profile must not error on every call."""
    as_profile(client, "gone")
    assert client.get("/api/holdings").status_code == 200


# ---- the guards on destructive things -----------------------------------
def test_reset_needs_the_confirm_token(client):
    assert client.post("/api/reset", json={}).status_code == 400
    assert client.post("/api/reset",
                       json={"confirm": "ERASE"}).status_code == 200


def test_deleting_a_profile_needs_its_name_in_the_body(client):
    client.post("/api/profiles", json={"name": "Demo"})
    assert client.request("DELETE", "/api/profiles/demo",
                          json={"confirm": "wrong"}).status_code == 400
    assert client.request("DELETE", "/api/profiles/demo",
                          json={"confirm": "Demo"}).status_code == 200


def test_the_first_profile_cannot_be_deleted_over_http(client):
    r = client.request("DELETE", "/api/profiles/default",
                       json={"confirm": "My portfolio"})
    assert r.status_code == 400


# ---- a holding through its whole life -----------------------------------
def test_a_holding_round_trips(client):
    created = client.post("/api/holdings", json={
        "asset_class": "stock", "name": "Reliance", "identifier": "RELIANCE",
        "units": 10, "avg_cost": 1000}).json()
    hid = created["id"]
    assert created["current_value"] == 10000      # priced at cost until refresh
    assert created["price_date"]

    fetched = [h for h in client.get("/api/holdings").json()
               if h["id"] == hid][0]
    assert fetched["name"] == "Reliance"

    updated = client.put("/api/holdings/%d" % hid,
                         json={"last_price": 1400}).json()
    assert updated["current_value"] == 14000
    assert updated["price_date"]

    assert client.delete("/api/holdings/%d" % hid).status_code == 200
    assert client.get("/api/holdings").json() == []


def test_a_404_does_not_leak_a_session(client):
    """The error paths are where the session leak lived."""
    for _ in range(30):
        assert client.get("/api/holdings").status_code == 200
        assert client.put("/api/holdings/999999",
                          json={"name": "x"}).status_code == 404
    assert client.get("/api/summary").status_code == 200


def test_a_bad_asset_class_is_refused(client):
    r = client.post("/api/holdings", json={"asset_class": "crypto",
                                           "name": "X"})
    assert r.status_code == 400


def test_a_holding_needs_a_name(client):
    assert client.post("/api/holdings",
                       json={"asset_class": "stock"}).status_code == 400


# ---- the privacy claims, over HTTP --------------------------------------
def test_the_privacy_page_reports_the_real_data_folder(client, tmp_path):
    body = client.get("/api/privacy").json()
    assert body["data_dir"] == str(tmp_path)
    assert body["offline"] is False
    assert {h["host"] for h in body["allowed_hosts"]} == set(
        main.netlog.ALLOWED_HOSTS)


def test_offline_mode_survives_a_round_trip(client):
    client.post("/api/privacy/offline", json={"offline": True})
    assert client.get("/api/privacy").json()["offline"] is True
    assert client.post("/api/prices/refresh").json()["offline"] is True


def test_an_oversized_upload_is_refused(client):
    big = b"x" * (main.MAX_UPLOAD_BYTES + 1)
    r = client.post("/api/import/preview",
                    files={"file": ("big.csv", big, "text/csv")})
    assert r.status_code == 413


def test_a_wipe_leaves_a_usable_portfolio_behind(client):
    """The default owner check is cached per file; a wipe must clear it."""
    client.post("/api/holdings", json={"asset_class": "stock", "name": "S",
                                       "units": 1, "avg_cost": 10})
    assert client.post("/api/reset", json={"confirm": "ERASE"}).status_code == 200
    assert client.get("/api/owners").json()
    assert client.post("/api/holdings",
                       json={"asset_class": "stock", "name": "After",
                             "units": 1, "avg_cost": 10}).status_code == 200


def test_the_dashboard_summary_matches_the_holdings_list(client):
    """summary() and /api/holdings must not drift apart now they share a load."""
    client.post("/api/holdings", json={"asset_class": "stock", "name": "A",
                                       "units": 10, "avg_cost": 100})
    client.post("/api/holdings", json={"asset_class": "fd", "name": "FD",
                                       "avg_cost": 50000, "rate": 7,
                                       "start_date": "2024-01-01"})
    summary = client.get("/api/summary").json()
    listed = client.get("/api/holdings").json()
    assert len(summary["holdings"]) == len(listed) == 2
    assert round(sum(h["current_value"] for h in listed), 2) == \
        summary["total_assets"]
