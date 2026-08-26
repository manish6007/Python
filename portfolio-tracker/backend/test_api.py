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
    assert r.status_code == 422
    assert "asset_class must be one of" in r.json()["detail"]


def test_a_misspelled_field_is_an_error_not_a_silent_no_op(client):
    """`payload.get("assetClass")` used to just return None."""
    r = client.post("/api/holdings", json={"asset_class": "stock",
                                           "name": "X", "assetClass": "y"})
    assert r.status_code == 422
    assert "assetClass" in r.json()["detail"]


def test_a_validation_error_reads_as_a_sentence(client):
    """The UI shows `detail` verbatim; a list of error objects is noise."""
    r = client.post("/api/holdings", json={"asset_class": "stock",
                                           "name": "X", "units": "lots"})
    assert isinstance(r.json()["detail"], str)
    assert r.json()["detail"].startswith("units: ")


def test_a_negative_quantity_is_refused(client):
    r = client.post("/api/holdings", json={"asset_class": "stock",
                                           "name": "X", "units": -5})
    assert r.status_code == 422


def test_a_holding_needs_a_name(client):
    r = client.post("/api/holdings", json={"asset_class": "stock"})
    assert r.status_code == 422
    assert "name" in r.json()["detail"]


def test_a_missing_amount_is_a_422_not_a_500(client):
    """float(payload["amount"]) used to raise KeyError -> 500."""
    r = client.post("/api/income", json={"category": "Salary"})
    assert r.status_code == 422
    assert "amount" in r.json()["detail"]


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


# ---- partial updates must stay partial ----------------------------------
def test_a_put_touches_only_the_fields_it_was_sent(client):
    """exclude_unset is what keeps "absent" different from "sent as null"."""
    h = client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "name": "Fund", "identifier": "120503",
        "units": 100, "avg_cost": 50,
        "meta": {"category": "equity", "nominee": "Spouse"}}).json()

    client.put("/api/holdings/%d" % h["id"], json={"last_price": 75})
    after = client.get("/api/holdings").json()[0]
    assert after["identifier"] == "120503"          # untouched
    assert after["units"] == 100
    assert after["meta"]["nominee"] == "Spouse"
    assert after["current_value"] == 7500


def test_meta_merges_rather_than_replacing(client):
    h = client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "name": "Fund", "units": 1,
        "avg_cost": 1, "meta": {"category": "hybrid"}}).json()
    client.put("/api/holdings/%d" % h["id"],
               json={"meta": {"nominee": "Spouse"}})
    meta = client.get("/api/holdings").json()[0]["meta"]
    assert meta["category"] == "hybrid" and meta["nominee"] == "Spouse"


def test_a_recurring_cost_keeps_its_frequency_on_a_partial_update(client):
    r = client.post("/api/recurring", json={
        "name": "Insurance", "kind": "premium", "amount": 12000,
        "frequency": "yearly"}).json()
    assert r["amount_monthly"] == 1000
    client.put("/api/recurring/%d" % r["id"], json={"name": "Car insurance"})
    after = client.get("/api/recurring").json()[0]
    assert after["frequency"] == "yearly" and after["amount_monthly"] == 1000


def test_a_bad_frequency_is_refused(client):
    r = client.post("/api/recurring", json={"name": "X", "amount": 100,
                                            "frequency": "fortnightly"})
    assert r.status_code == 422
    assert "frequency" in r.json()["detail"]


def test_settings_still_accept_the_whole_object_back(client):
    """The UI sends read-only fields along with the editable ones."""
    settings = client.get("/api/settings").json()
    settings["age"] = "38"
    assert client.put("/api/settings", json=settings).status_code == 200
    assert client.get("/api/settings").json()["age"] == "38"


def test_the_openapi_schema_describes_the_bodies(client):
    """Every request body used to be documented as "object"."""
    schema = client.get("/openapi.json").json()
    body = (schema["paths"]["/api/holdings"]["post"]["requestBody"]
            ["content"]["application/json"]["schema"])
    ref = body.get("$ref", "")
    assert ref.endswith("HoldingIn")
    props = schema["components"]["schemas"]["HoldingIn"]["properties"]
    assert "asset_class" in props and "units" in props


def test_erase_all_data_really_erases_all_of_it(client):
    """Policies and goals used to survive a wipe, orphaned against no owner."""
    client.post("/api/holdings", json={"asset_class": "stock", "name": "S",
                                       "units": 1, "avg_cost": 10})
    client.post("/api/policies", json={"name": "Term", "kind": "term",
                                       "sum_assured": 10000000,
                                       "premium": 18000})
    client.post("/api/goals", json={"name": "Car", "amount_today": 1200000,
                                    "target_year": 5})
    client.post("/api/loans", json={"name": "Home", "annual_rate": 8.5,
                                    "principal_outstanding": 5000000})

    assert client.post("/api/reset", json={"confirm": "ERASE"}).status_code == 200

    for path in ("/api/holdings", "/api/policies", "/api/goals", "/api/loans"):
        assert client.get(path).json() == [], path
    assert client.get("/api/summary").json()["total_assets"] == 0


def test_the_app_notices_when_the_server_is_older_than_the_code(client,
                                                                monkeypatch):
    """Updating is git pull + npm run build; the Python process is not
    restarted by either, so a new page ends up calling an endpoint the
    running server does not have. That looks like a network fault."""
    from datetime import datetime, timedelta
    assert client.get("/api/meta").json()["stale_backend"] is False

    # Pretend the process started before the files on disk were last written.
    monkeypatch.setattr(main, "_started", datetime.now() + timedelta(days=1))
    assert client.get("/api/meta").json()["stale_backend"] is False

    monkeypatch.setattr(main, "_started", datetime.now() - timedelta(days=365))
    assert client.get("/api/meta").json()["stale_backend"] is True


def test_a_readable_nav_file_and_an_unreadable_one_report_differently(client,
                                                                      monkeypatch):
    """"AMFI could not be reached" for a file that downloaded fine sent
    someone to check a connection that had just delivered a megabyte."""
    import pricing

    monkeypatch.setattr(pricing, "fetch_amfi",
                        lambda *a, **k: ({}, {}, pricing.AMFI_UNREACHABLE))
    body = client.post("/api/prices/refresh").json()
    assert body["amfi_status"] == "unreachable"
    assert body["amfi_reachable"] is False

    monkeypatch.setattr(pricing, "fetch_amfi",
                        lambda *a, **k: ({}, {}, pricing.AMFI_UNREADABLE))
    body = client.post("/api/prices/refresh").json()
    assert body["amfi_status"] == "unreadable"
    assert body["amfi_reachable"] is False      # still no NAVs, different why


# ---- giving funds the code that prices them -----------------------------
def _stub_amfi(monkeypatch, main_mod):
    """A small AMFI table, so the suggestion path can be tested offline."""
    from datetime import date as _date
    import pricing
    navs, code, nav = {}, 100000, 50.0
    for base in ("DSP Midcap Fund", "Parag Parikh Flexi Cap Fund"):
        for plan in ("Direct Plan", "Regular Plan"):
            nav += 20
            navs[str(code)] = {"name": "%s - %s - Growth" % (base, plan),
                               "nav": nav, "date": _date(2026, 8, 26)}
            code += 1
    monkeypatch.setattr(pricing, "fetch_amfi",
                        lambda *a, **k: (navs, {}, pricing.AMFI_OK))
    main_mod._amfi_cache.update(data={}, at=None, by_isin={})
    return navs


def test_a_fund_with_a_folio_gets_its_code_suggested(client, monkeypatch):
    _stub_amfi(monkeypatch, main)
    client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "name": "DSP Midcap Fund",
        "identifier": "90722941761/0", "units": 100, "avg_cost": 50})
    body = client.get("/api/amfi/suggest-codes").json()
    assert len(body["holdings"]) == 1
    row = body["holdings"][0]
    assert row["confident"] is True
    assert row["candidates"][0]["name"].startswith("DSP Midcap Fund - Direct")


def test_a_fund_that_already_has_a_code_is_left_out(client, monkeypatch):
    navs = _stub_amfi(monkeypatch, main)
    code = next(iter(navs))
    client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "name": "DSP Midcap Fund",
        "identifier": code, "units": 100, "avg_cost": 50})
    assert client.get("/api/amfi/suggest-codes").json()["holdings"] == []


def test_applying_a_code_prices_the_fund_and_keeps_the_folio(client,
                                                             monkeypatch):
    navs = _stub_amfi(monkeypatch, main)
    h = client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "name": "DSP Midcap Fund",
        "identifier": "90722941761/0", "units": 100, "avg_cost": 50}).json()
    row = client.get("/api/amfi/suggest-codes").json()["holdings"][0]
    code = row["candidates"][0]["code"]

    r = client.post("/api/amfi/apply-codes", json={"assignments": [
        {"holding_id": h["id"], "scheme_code": code}]}).json()
    assert r["applied"] == 1 and r["errors"] == []

    after = client.get("/api/holdings").json()[0]
    assert after["identifier"] == code
    assert after["last_price"] == navs[code]["nav"]
    # The folio is needed by the family record and CAS reconciliation.
    assert after["meta"]["folio"] == "90722941761/0"
    assert client.get("/api/amfi/suggest-codes").json()["holdings"] == []


def test_applying_a_code_that_is_not_a_scheme_is_refused(client, monkeypatch):
    _stub_amfi(monkeypatch, main)
    h = client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "name": "DSP Midcap Fund",
        "units": 1, "avg_cost": 50}).json()
    r = client.post("/api/amfi/apply-codes", json={"assignments": [
        {"holding_id": h["id"], "scheme_code": "999999"}]}).json()
    assert r["applied"] == 0 and "not an AMFI scheme code" in r["errors"][0]


def test_a_purchase_price_is_not_treated_as_a_recent_nav(client, monkeypatch):
    """The app writes last_price = avg_cost when a holding is created. Read
    as evidence, that rejected every correct match for funds bought years
    ago at a very different price."""
    _stub_amfi(monkeypatch, main)
    client.post("/api/holdings", json={
        "asset_class": "mutual_fund", "name": "DSP Midcap Fund",
        "units": 100, "avg_cost": 12.5})       # nothing like today's NAV
    row = client.get("/api/amfi/suggest-codes").json()["holdings"][0]
    assert row["compared_against"] is None
    assert row["confident"] is True
