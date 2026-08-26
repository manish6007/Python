"""What the app can reach, and where it keeps things.

The app has always been local-only, but a user cannot see that. These tests
cover the claims the app makes about itself, because a claim nobody checks
is worth nothing.
"""
import os

import pytest

import config
import db
import netlog
import pricing
import profiles as profiles_mod


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_PATH", str(tmp_path / "app-config.json"))
    monkeypatch.delenv(config.ENV_DATA_DIR, raising=False)
    monkeypatch.setattr(db, "_engines", {})
    monkeypatch.setattr(db, "_factories", {})
    netlog.clear()
    return tmp_path


# ---- what can be contacted ----------------------------------------------
def test_an_unlisted_host_is_refused_before_connecting(store, monkeypatch):
    """The allowlist is enforced in code, not just described in the UI."""
    def explode(*a, **k):
        raise AssertionError("a connection was opened to an unlisted host")
    monkeypatch.setattr(pricing.requests, "get", explode)
    with pytest.raises(pricing.Offline):
        pricing._get("https://example.com/tracker.js", 5)
    assert netlog.entries()[0]["outcome"] == "refused"


def test_offline_mode_blocks_the_request_and_says_so(store, monkeypatch):
    def explode(*a, **k):
        raise AssertionError("a connection was opened while offline")
    monkeypatch.setattr(pricing.requests, "get", explode)
    config.set_offline(True)
    assert pricing.fetch_amfi() == ({}, {})
    entry = netlog.entries()[0]
    assert entry["outcome"] == "blocked" and "offline" in entry["detail"]


def test_offline_mode_leaves_prices_alone_rather_than_zeroing_them(store):
    config.set_offline(True)
    assert pricing.fetch_stock_price("RELIANCE") == (None, None)


def test_a_successful_fetch_is_logged_with_its_host_and_purpose(store,
                                                                monkeypatch):
    class Resp:
        content = b"x" * 10
        text = "120503;INF1;INF2;A Fund;10.5;25-Aug-2026"

        def raise_for_status(self):
            pass
    monkeypatch.setattr(pricing.requests, "get", lambda *a, **k: Resp())
    navs, _ = pricing.fetch_amfi()
    assert navs
    entry = netlog.entries()[0]
    assert entry["host"] == "www.amfiindia.com"
    assert entry["outcome"] == "ok"
    assert "NAV" in entry["purpose"]


def test_a_failed_fetch_is_logged_rather_than_swallowed(store, monkeypatch):
    def boom(*a, **k):
        raise pricing.requests.RequestException("no route to host")
    monkeypatch.setattr(pricing.requests, "get", boom)
    assert pricing.fetch_amfi() == ({}, {})
    assert netlog.entries()[0]["outcome"] == "failed"


def test_the_log_does_not_grow_without_bound(store):
    for i in range(netlog.MAX_ENTRIES + 50):
        netlog.record("www.amfiindia.com", "x", "ok", str(i))
    assert len(netlog.entries()) == netlog.MAX_ENTRIES


def test_every_allowed_host_says_why_it_is_allowed(store):
    assert all(purpose for purpose in netlog.ALLOWED_HOSTS.values())


# ---- where the data is ---------------------------------------------------
def test_the_data_folder_defaults_to_where_it_has_always_been(store):
    assert config.data_dir() == str(store)
    assert config.data_dir_source() == "default"


def test_an_environment_variable_wins_over_anything_the_app_wrote(store,
                                                                  monkeypatch):
    config.set_data_dir(str(store / "chosen"))
    monkeypatch.setenv(config.ENV_DATA_DIR, str(store / "pinned"))
    assert config.data_dir() == str(store / "pinned")
    assert config.data_dir_source() == "environment"


def test_an_unwritable_folder_is_refused(store):
    with pytest.raises(ValueError):
        config.set_data_dir("/proc/nope/cannot-create-this")


def test_data_files_reports_real_paths_and_sizes(store):
    (store / "portfolio.db").write_bytes(b"x" * 1234)
    files = config.data_files()
    assert files[0]["path"] == str(store / "portfolio.db")
    assert files[0]["bytes"] == 1234
    assert files[0]["modified"]


def test_moving_the_data_copies_it_and_leaves_the_original(store):
    (store / "portfolio.db").write_bytes(b"real data")
    os.makedirs(store / "profiles")
    (store / "profiles" / "demo.db").write_bytes(b"demo data")
    dest = store / "vault"

    result = config.move_data(str(dest))

    assert config.data_dir() == str(dest)
    assert (dest / "portfolio.db").read_bytes() == b"real data"
    assert (dest / "profiles" / "demo.db").read_bytes() == b"demo data"
    # The originals are still there: a move that half-worked must never be
    # the reason someone loses their portfolio.
    assert (store / "portfolio.db").exists()
    assert set(result["copied"]) == {"portfolio.db", "profiles/demo.db"}


def test_a_failed_move_puts_the_setting_back(store, monkeypatch):
    (store / "portfolio.db").write_bytes(b"real data")
    monkeypatch.setattr(config.shutil, "copy2",
                        lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(ValueError):
        config.move_data(str(store / "vault"))
    assert config.data_dir() == str(store)          # still pointing at the data


def test_moving_onto_the_same_folder_is_refused(store):
    with pytest.raises(ValueError):
        config.move_data(str(store))


def test_profiles_follow_the_data_folder(store):
    config.set_data_dir(str(store / "vault"))
    assert profiles_mod.path_for("default").startswith(str(store / "vault"))
    profiles_mod.create("Demo")
    assert os.path.exists(profiles_mod.registry_path())
    assert profiles_mod.registry_path().startswith(str(store / "vault"))


# ---- stock prices go through the same allowlist as NAVs ------------------
CHART = {"chart": {"result": [{
    "timestamp": [1756166400, 1756252800],
    "indicators": {"quote": [{"close": [1400.5, None]}]},
}]}}


def test_a_stock_price_is_parsed_from_the_last_non_null_close(store):
    """Yahoo pads the series with nulls for holidays."""
    price, when = pricing.parse_chart(CHART)
    assert price == 1400.5 and when is not None


def test_a_malformed_chart_response_is_not_a_crash(store):
    assert pricing.parse_chart({}) == (None, None)
    assert pricing.parse_chart({"chart": {"result": []}}) == (None, None)


def test_stock_prices_are_now_behind_the_enforced_allowlist(store,
                                                            monkeypatch):
    """They used to go via yfinance, which opened its own connections."""
    seen = {}

    class Resp:
        content = b"{}"

        def raise_for_status(self):
            pass

        def json(self):
            return CHART

    def fake_get(url, timeout=None, headers=None):
        seen["url"] = url
        seen["headers"] = headers or {}
        return Resp()
    monkeypatch.setattr(pricing.requests, "get", fake_get)
    assert pricing.fetch_stock_price("RELIANCE")[0] == 1400.5
    assert seen["url"].startswith("https://query1.finance.yahoo.com/")
    assert "RELIANCE.NS" in seen["url"]
    entry = netlog.entries()[0]
    assert entry["host"] == "query1.finance.yahoo.com"
    assert entry["outcome"] == "ok"
    # Both feeds reject the default python-requests agent.
    assert "Mozilla" in seen["headers"].get("User-Agent", "")


def test_offline_mode_blocks_stock_prices_too(store, monkeypatch):
    def explode(*a, **k):
        raise AssertionError("a connection was opened while offline")
    monkeypatch.setattr(pricing.requests, "get", explode)
    config.set_offline(True)
    assert pricing.fetch_stock_price("RELIANCE") == (None, None)
    assert netlog.entries()[0]["outcome"] == "blocked"


def test_symbols_are_de_duplicated_before_fetching(store, monkeypatch):
    calls = []
    monkeypatch.setattr(pricing, "fetch_stock_price",
                        lambda s, t=15: calls.append(s) or (100.0, None))
    out = pricing.fetch_stock_prices(["RELIANCE", "RELIANCE", "TCS", ""])
    assert sorted(calls) == ["RELIANCE", "TCS"]
    assert set(out) == {"RELIANCE", "TCS"}


# ---- saying why, not "check your internet connection" --------------------
def test_each_kind_of_failure_gets_its_own_explanation(store):
    import requests as rq
    ssl = pricing.explain(rq.exceptions.SSLError("bad handshake"))
    assert "certificate" in ssl or "inspecting traffic" in ssl

    dns = pricing.explain(rq.exceptions.ConnectionError(
        "Failed to resolve: Name or service not known"))
    assert "DNS" in dns

    proxy = pricing.explain(rq.exceptions.ProxyError("tunnel failed"))
    assert "proxy" in proxy.lower()

    resp = type("R", (), {"status_code": 403})()
    forbidden = pricing.explain(rq.exceptions.HTTPError(response=resp))
    assert "403" in forbidden and "refused" in forbidden

    resp429 = type("R", (), {"status_code": 429})()
    assert "429" in pricing.explain(rq.exceptions.HTTPError(response=resp429))


def test_the_connection_test_reports_one_row_per_host(store, monkeypatch):
    import requests as rq

    def boom(*a, **k):
        raise rq.exceptions.SSLError("bad handshake")
    monkeypatch.setattr(pricing.requests, "get", boom)
    rows = pricing.check_hosts(timeout=1)
    assert [r["host"] for r in rows] == ["www.amfiindia.com",
                                         "query1.finance.yahoo.com"]
    assert all(r["ok"] is False for r in rows)
    assert all("certificate" in r["detail"] or "inspecting" in r["detail"]
               for r in rows)


def test_the_connection_test_says_so_when_offline(store, monkeypatch):
    def explode(*a, **k):
        raise AssertionError("a connection was opened while offline")
    monkeypatch.setattr(pricing.requests, "get", explode)
    config.set_offline(True)
    rows = pricing.check_hosts(timeout=1)
    assert all("Offline mode" in r["detail"] for r in rows)
