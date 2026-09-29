"""The OTP delivery channels, and what happens when one fails."""
from __future__ import annotations

import os
import tempfile

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import auth as auth_module
from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.notifications import (
    ConsoleChannel,
    EvolutionGoChannel,
    HttpChannel,
    OtpDeliveryError,
    build_channel,
    render,
)
from backend.seed import DISTRIBUTOR_MOBILE, RETAILER_MOBILE, seed


def transport(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


# ------------------------------------------------------------- the adapters


def test_evolution_posts_to_the_instance_with_the_api_key():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["apikey"] = request.headers.get("apikey")
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json={"key": {"id": "WA-MSG-1"}})

    channel = EvolutionGoChannel(
        base_url="http://gateway.local:8080/",
        instance="emi-locker",
        api_key="secret-key",
        client=transport(handler),
    )
    out = channel.send_otp("9876543210", "482910", 300)

    assert seen["url"] == "http://gateway.local:8080/message/sendText/emi-locker"
    assert seen["apikey"] == "secret-key"
    assert seen["body"]["number"] == "919876543210"
    assert "482910" in seen["body"]["text"]
    assert out == {"delivered": True, "channel": "evolution-go",
                   "provider_ref": "WA-MSG-1"}


def test_evolution_reports_a_rejection_rather_than_pretending_to_send():
    def handler(request):
        return httpx.Response(401, text="invalid apikey")

    channel = EvolutionGoChannel("http://gateway.local", "i", "bad",
                                 client=transport(handler))
    with pytest.raises(OtpDeliveryError) as exc:
        channel.send_otp("9876543210", "111111", 300)
    assert "401" in str(exc.value)


def test_evolution_reports_an_unreachable_gateway():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    channel = EvolutionGoChannel("http://gateway.local", "i", "k",
                                 client=transport(handler))
    with pytest.raises(OtpDeliveryError) as exc:
        channel.send_otp("9876543210", "111111", 300)
    assert "unreachable" in str(exc.value)


def test_evolution_refuses_to_build_without_credentials():
    with pytest.raises(ValueError):
        EvolutionGoChannel(base_url="", instance="i", api_key="k")
    with pytest.raises(ValueError):
        EvolutionGoChannel(base_url="http://x", instance="i", api_key="")


def test_http_channel_uses_the_configured_field_names():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.read())
        seen["auth"] = request.headers.get("X-Api-Key")
        return httpx.Response(200, json={"ok": True})

    channel = HttpChannel(
        url="https://sms.example/send",
        api_key="k123",
        auth_header="X-Api-Key",
        auth_prefix="",
        to_field="mobile",
        body_field="text",
        extra_fields={"sender": "EMILCK", "dlt_template_id": "1207xxxx"},
        client=transport(handler),
    )
    channel.send_otp("9876543210", "482910", 300)

    assert seen["auth"] == "k123"
    assert seen["body"]["mobile"] == "919876543210"
    assert seen["body"]["dlt_template_id"] == "1207xxxx"
    assert seen["body"]["sender"] == "EMILCK"
    assert "482910" in seen["body"]["text"]


def test_the_message_reads_like_something_a_person_would_trust():
    text = render(Settings().otp_template, "482910", 300, "Ashish Enterprises")
    assert "482910" in text
    assert "Ashish Enterprises" in text
    assert "5 minutes" in text
    assert "Do not share" in text


# ------------------------------------------------------------ channel choice


def _settings(**env):
    for key, value in env.items():
        os.environ[key] = value
    try:
        return Settings()
    finally:
        for key in env:
            os.environ.pop(key, None)


def test_console_is_the_default():
    assert isinstance(build_channel(_settings()), ConsoleChannel)


def test_evolution_is_selected_by_configuration_alone():
    built = build_channel(_settings(
        EMI_OTP_CHANNEL="evolution",
        EMI_WA_URL="http://gateway.local",
        EMI_WA_INSTANCE="emi",
        EMI_WA_API_KEY="k",
    ))
    assert isinstance(built, EvolutionGoChannel)
    assert built.country_code == "91"


def test_an_unknown_channel_name_is_refused():
    with pytest.raises(ValueError):
        build_channel(_settings(EMI_OTP_CHANNEL="carrier-pigeon"))


def test_production_refuses_to_start_with_codes_going_to_the_log():
    problems = _settings(
        EMI_ENV="production",
        EMI_EXPOSE_OTP="0",
        EMI_JWT_SECRET="x" * 40,
        EMI_WEBHOOK_SECRET="y" * 40,
        EMI_CORS="https://admin.example",
    )
    with pytest.raises(RuntimeError) as exc:
        problems.validate()
    assert "console" in str(exc.value)


def test_production_refuses_a_half_configured_gateway():
    half = _settings(
        EMI_ENV="production",
        EMI_EXPOSE_OTP="0",
        EMI_JWT_SECRET="x" * 40,
        EMI_WEBHOOK_SECRET="y" * 40,
        EMI_CORS="https://admin.example",
        EMI_OTP_CHANNEL="evolution",
        EMI_WA_URL="http://gateway.local",
    )
    with pytest.raises(RuntimeError) as exc:
        half.validate()
    assert "EMI_WA_INSTANCE" in str(exc.value)


# ------------------------------------------------- failure must not leak or block


@pytest.fixture()
def client():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    seed(path)
    with TestClient(create_app(path)) as c:
        yield c
    auth_module.reset_channel()
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.unlink(path + suffix)


class DeadChannel:
    name = "dead"

    def send_otp(self, mobile, code, ttl_seconds):
        raise OtpDeliveryError("gateway number has been banned")


def test_a_dead_gateway_does_not_break_the_endpoint_or_name_the_account(
        client, monkeypatch):
    """The realistic failure: the WhatsApp number gets banned overnight."""
    monkeypatch.setattr(auth_module, "channel", lambda: DeadChannel())
    monkeypatch.setattr(
        type(auth_module.settings), "expose_otp", property(lambda _: False))

    known = client.post("/auth/send-otp", json={"mobile": RETAILER_MOBILE})
    unknown = client.post("/auth/send-otp", json={"mobile": "9111100000"})

    assert known.status_code == 200 and unknown.status_code == 200
    assert known.json() == {"sent": True, "mobile": RETAILER_MOBILE}
    assert unknown.json() == {"sent": True, "mobile": "9111100000"}


def test_a_code_that_failed_to_send_is_still_a_valid_code(client, monkeypatch):
    """Delivery and issuance are separate. A retry through a working channel
    must not be required to make the already-issued code work."""
    sent = {}

    class CapturingChannel:
        name = "capture"

        def send_otp(self, mobile, code, ttl_seconds):
            sent["code"] = code
            raise OtpDeliveryError("provider timed out")

    monkeypatch.setattr(auth_module, "channel", lambda: CapturingChannel())
    client.post("/auth/send-otp", json={"mobile": DISTRIBUTOR_MOBILE})

    verified = client.post("/auth/verify-otp",
                           json={"mobile": DISTRIBUTOR_MOBILE, "code": sent["code"]})
    assert verified.status_code == 200
    assert verified.json()["user"]["role"] == "DISTRIBUTOR"


def test_the_real_channel_receives_the_code_that_was_issued(client, monkeypatch):
    delivered = {}

    class SpyChannel:
        name = "spy"

        def send_otp(self, mobile, code, ttl_seconds):
            delivered["mobile"] = mobile
            delivered["code"] = code
            delivered["ttl"] = ttl_seconds
            return {"delivered": True, "channel": "spy", "provider_ref": "X1"}

    monkeypatch.setattr(auth_module, "channel", lambda: SpyChannel())
    out = client.post("/auth/send-otp", json={"mobile": RETAILER_MOBILE}).json()

    assert delivered["mobile"] == RETAILER_MOBILE
    assert delivered["code"] == out["dev_otp"]
    assert delivered["ttl"] == 300
    assert client.post("/auth/verify-otp", json={
        "mobile": RETAILER_MOBILE, "code": delivered["code"]}).status_code == 200


# ------------------------------------------------------------------- MSG91


def test_msg91_sends_our_own_code_through_the_flow_api():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["authkey"] = request.headers.get("authkey")
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json={"message": "5762846b4f8d285d378b4567",
                                         "type": "success"})

    from backend.app.notifications import Msg91Channel

    channel = Msg91Channel(auth_key="AK123", template_id="TPL987", sender="EMILCK",
                           client=transport(handler))
    out = channel.send_otp("9876543210", "482910", 300)

    assert seen["url"] == "https://api.msg91.com/api/v5/flow/"
    assert seen["authkey"] == "AK123"
    assert seen["body"]["template_id"] == "TPL987"
    assert seen["body"]["sender"] == "EMILCK"
    assert seen["body"]["recipients"] == [{"mobiles": "919876543210", "OTP": "482910"}]
    assert out["provider_ref"] == "5762846b4f8d285d378b4567"


def test_msg91_failure_reported_as_http_200_is_still_a_failure():
    """The trap: MSG91 answers 200 with type=error for a message it refused."""
    def handler(request):
        return httpx.Response(200, json={"type": "error",
                                         "message": "template not approved"})

    from backend.app.notifications import Msg91Channel

    channel = Msg91Channel("AK", "TPL", client=transport(handler))
    with pytest.raises(OtpDeliveryError) as exc:
        channel.send_otp("9876543210", "482910", 300)
    assert "template not approved" in str(exc.value)


def test_msg91_variable_name_follows_the_registered_dlt_template():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json={"message": "id", "type": "success"})

    from backend.app.notifications import Msg91Channel

    channel = Msg91Channel("AK", "TPL", code_variable="VAR1",
                           extra_variables={"COMPANY": "Ashish Enterprises"},
                           client=transport(handler))
    channel.send_otp("9876543210", "482910", 300)

    recipient = seen["body"]["recipients"][0]
    assert recipient["VAR1"] == "482910"
    assert recipient["COMPANY"] == "Ashish Enterprises"
    assert "OTP" not in recipient


def test_msg91_refuses_to_build_without_a_template():
    from backend.app.notifications import Msg91Channel

    with pytest.raises(ValueError):
        Msg91Channel(auth_key="AK", template_id="")


def test_msg91_is_selected_by_configuration():
    from backend.app.notifications import Msg91Channel

    built = build_channel(_settings(
        EMI_OTP_CHANNEL="msg91", EMI_MSG91_KEY="AK",
        EMI_MSG91_TEMPLATE_ID="TPL"))
    assert isinstance(built, Msg91Channel)


def test_production_refuses_msg91_without_credentials():
    half = _settings(
        EMI_ENV="production", EMI_EXPOSE_OTP="0",
        EMI_JWT_SECRET="x" * 40, EMI_WEBHOOK_SECRET="y" * 40,
        EMI_CORS="https://admin.example", EMI_OTP_CHANNEL="msg91",
        EMI_MSG91_KEY="AK")
    with pytest.raises(RuntimeError) as exc:
        half.validate()
    assert "EMI_MSG91_TEMPLATE_ID" in str(exc.value)
