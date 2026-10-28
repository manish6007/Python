"""Restriction notices over the real channels and the HTTP API."""
from __future__ import annotations

import json
import sqlite3

import httpx
import pytest

from backend.app.notifications import (
    ConsoleChannel,
    HttpChannel,
    Msg91Channel,
    OtpDeliveryError,
)
from backend.seed import ADMIN_MOBILE, CUSTOMER_MOBILE
from backend.tests.test_otp_delivery import _settings, transport
from backend.tests.test_sessions import auth, client, login  # noqa: F401 - fixture

VARIABLES = {"business": "Ashish Enterprises", "amount": "Rs.4,000.00", "model": "Galaxy A16",
             "days": 60, "pay_by": "02 May 2026", "retailer": "Sharma Mobiles"}


def test_msg91_fills_the_registered_notice_template_with_the_variables():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"type": "success", "message": "req-1"})

    channel = Msg91Channel("key", "otp-template", notice_template_id="notice-template",
                           client=transport(handler))
    out = channel.send_notice("9876543210", "ignored text", VARIABLES)
    assert out["delivered"] is True
    assert seen["template_id"] == "notice-template"
    recipient = seen["recipients"][0]
    assert recipient["mobiles"] == "919876543210"
    assert recipient["pay_by"] == "02 May 2026"
    assert recipient["days"] == "60"


def test_msg91_without_a_notice_template_fails_loudly():
    channel = Msg91Channel("key", "otp-template", client=transport(lambda r: None))
    with pytest.raises(OtpDeliveryError):
        channel.send_notice("9876543210", "text", VARIABLES)


def test_http_and_console_channels_send_the_text_itself(capsys):
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={})

    HttpChannel("https://sms.example/send", client=transport(handler)).send_notice(
        "9876543210", "the notice", VARIABLES)
    assert seen == {"to": "919876543210", "message": "the notice"}

    ConsoleChannel().send_notice("9876543210", "the notice", VARIABLES)
    assert "[NOTICE] 9876543210 -> the notice" in capsys.readouterr().out


def test_production_refuses_msg91_without_a_notice_template():
    configured = _settings(
        EMI_ENV="production", EMI_EXPOSE_OTP="0",
        EMI_JWT_SECRET="x" * 40, EMI_WEBHOOK_SECRET="y" * 40,
        EMI_CORS="https://admin.example",
        EMI_OTP_CHANNEL="msg91", EMI_MSG91_KEY="k", EMI_MSG91_TEMPLATE_ID="t",
    )
    with pytest.raises(RuntimeError) as exc:
        configured.validate()
    assert "EMI_MSG91_NOTICE_TEMPLATE_ID" in str(exc.value)


def test_the_sweep_delivers_the_notice_and_the_customer_app_shows_it(client):
    # Age the seeded finance by 300 days so its first instalments are long overdue.
    db_path = client.app.state.db_path
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE emi_schedules SET due_date = date(due_date, '-300 days')"
                 " WHERE finance_id = 'FIN-0000001'")
    conn.commit()
    conn.close()

    customer = auth(login(client, CUSTOMER_MOBILE))
    before = client.get("/me/finances", headers=customer).json()["finances"][0]
    assert before["notice"] is None

    admin = auth(login(client, ADMIN_MOBILE))
    moved = client.post("/admin/run-daily-sweep", headers=admin).json()["moved"]
    assert moved["NOTICE_FIRST"] == 1
    assert moved["NOTICES_DELIVERED"] == 1

    notice = client.get("/me/finances", headers=customer).json()["finances"][0]["notice"]
    assert notice["kind"] == "FIRST"
    assert notice["delivered_at"] is not None
    assert notice["overdue_paise"] > 0
    assert notice["pay_by"]
