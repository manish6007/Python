"""The restriction rules as the admin panel and a scheduler see them over HTTP."""
from __future__ import annotations

from backend.seed import ADMIN_MOBILE, RETAILER_MOBILE
from backend.tests.test_sessions import auth, client, login  # noqa: F401 - fixture


def test_the_admin_panel_shows_the_restriction_settings_and_their_defaults(client):
    admin = auth(login(client, ADMIN_MOBILE))
    settings = client.get("/admin/settings", headers=admin).json()["settings"]
    assert settings["restriction.min_days_past_due"]["value"] == 90
    assert settings["restriction.unlock_limit_minutes"]["value"] == 60
    assert settings["restriction.late_unlock_compensation_paise_per_hour"]["value"] == 25000


def test_the_admin_panel_cannot_loosen_a_minimum(client):
    admin = auth(login(client, ADMIN_MOBILE))
    out = client.put("/admin/settings", headers=admin,
                     json={"key": "restriction.min_days_past_due", "value": 30})
    assert out.status_code == 422
    assert "RBI draft minimum" in out.json()["message"]


def test_the_seeded_finance_cannot_be_restricted_today(client):
    admin = auth(login(client, ADMIN_MOBILE))
    device_id = client.get("/finance/FIN-0000001", headers=admin).json()["device"]["id"]
    out = client.post("/device-actions", headers=admin,
                      json={"device_id": device_id, "command": "RESTRICT", "reason": "test"})
    assert out.status_code == 403
    assert "not eligible" in out.json()["message"]


def test_the_unlock_monitor_is_for_admins_only(client):
    admin = auth(login(client, ADMIN_MOBILE))
    assert client.get("/admin/unlock-monitor", headers=admin).json() == {"waiting": []}
    retailer = auth(login(client, RETAILER_MOBILE))
    assert client.get("/admin/unlock-monitor", headers=retailer).status_code == 403
