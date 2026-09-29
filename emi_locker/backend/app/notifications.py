"""How a one-time code actually reaches a customer.

The rest of the backend does not know or care which channel is used. It calls
``send_otp`` on whatever channel the configuration selects, and every channel
answers the same way. That matters here more than usual, because the likely
first choice - an unofficial WhatsApp gateway - is the one you are most likely
to have to abandon in a hurry.

Channels available:

* ``console``  - prints to the server log. The local default; no provider.
* ``evolution`` - Evolution Go, a whatsmeow-based WhatsApp gateway paired by
  QR to a real number. See the warning on EvolutionGoChannel.
* ``msg91``    - MSG91's Flow API, the usual SMS route for India.
* ``http``     - a generic JSON POST, for any other aggregator or an official
  WhatsApp Business provider, configured by URL and field names.

Swapping channel is an environment variable, not a code change.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Protocol

import httpx

log = logging.getLogger("emi.otp")

DEFAULT_TEMPLATE = (
    "{code} is your {business} verification code. It is valid for {minutes} "
    "minutes. Do not share it with anyone."
)


class OtpDeliveryError(Exception):
    """The provider did not accept the message.

    Never surfaced to the caller of /auth/send-otp. Reporting a delivery
    failure would report it only for numbers that have an account, which turns
    the endpoint back into an account-existence oracle.
    """


class OtpChannel(Protocol):  # pragma: no cover - interface only
    name: str

    def send_otp(self, mobile: str, code: str, ttl_seconds: int) -> Dict[str, Any]:
        ...


def render(template: str, code: str, ttl_seconds: int, business: str) -> str:
    return template.format(
        code=code, minutes=max(1, ttl_seconds // 60), business=business)


class ConsoleChannel:
    """Prints the code. The local default, and never appropriate in production.

    ``Settings.validate`` refuses to start a production process using it.
    """

    name = "console"

    def __init__(self, business: str = "EMI Locker"):
        self.business = business

    def send_otp(self, mobile: str, code: str, ttl_seconds: int) -> Dict[str, Any]:
        print("[OTP] %s -> %s (valid %ds)" % (mobile, code, ttl_seconds), flush=True)
        return {"delivered": True, "channel": self.name, "provider_ref": None}


class EvolutionGoChannel:
    """Evolution Go - a whatsmeow WhatsApp gateway paired by QR code.

    Read this before depending on it in production.

    whatsmeow speaks the WhatsApp Web protocol as an unofficial client, so
    using it is a breach of WhatsApp's Terms of Service. Meta bans numbers for
    the pattern this puts them into: high volumes of near-identical messages to
    people who have never messaged you first, which is exactly what an OTP is.

    If the number is banned, no customer can sign in and no customer can pay,
    because sign-in is the only way into the apps. There is no SLA and no
    appeal. Treat it as a stopgap for pilots, keep ``http`` configured against
    a licensed provider as the fallback, and do not let it become the only way
    into the platform.

    The official route is the WhatsApp Business Platform with an approved
    authentication-category template, direct from Meta or through a BSP.
    """

    name = "evolution-go"

    def __init__(
        self,
        base_url: str,
        instance: str,
        api_key: str,
        template: str = DEFAULT_TEMPLATE,
        business: str = "EMI Locker",
        country_code: str = "91",
        timeout_seconds: float = 10.0,
        client: Optional[httpx.Client] = None,
    ):
        if not base_url or not instance or not api_key:
            raise ValueError(
                "evolution channel needs EMI_WA_URL, EMI_WA_INSTANCE and EMI_WA_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.instance = instance
        self.api_key = api_key
        self.template = template
        self.business = business
        self.country_code = country_code
        self.timeout_seconds = timeout_seconds
        self._client = client

    def _post(self, url: str, payload: Dict[str, Any]) -> httpx.Response:
        headers = {"apikey": self.api_key, "Content-Type": "application/json"}
        if self._client is not None:
            return self._client.post(url, json=payload, headers=headers)
        with httpx.Client(timeout=self.timeout_seconds) as client:
            return client.post(url, json=payload, headers=headers)

    def send_otp(self, mobile: str, code: str, ttl_seconds: int) -> Dict[str, Any]:
        url = "%s/message/sendText/%s" % (self.base_url, self.instance)
        payload = {
            "number": "%s%s" % (self.country_code, mobile),
            "text": render(self.template, code, ttl_seconds, self.business),
        }
        try:
            response = self._post(url, payload)
        except httpx.HTTPError as exc:
            raise OtpDeliveryError("evolution gateway unreachable: %s" % exc)

        if response.status_code >= 400:
            raise OtpDeliveryError(
                "evolution gateway rejected the message (HTTP %d): %s"
                % (response.status_code, response.text[:200]))

        reference = None
        try:
            body = response.json()
            reference = (body.get("key") or {}).get("id") or body.get("id")
        except ValueError:
            pass
        return {"delivered": True, "channel": self.name, "provider_ref": reference}


class Msg91Channel:
    """MSG91 Flow API - templated SMS, the usual route for India.

    Two things worth knowing.

    **This sends our own code; it does not use MSG91's OTP API.** That API
    would generate and verify the code itself, handing over the hashing,
    single-use and attempt-capping this backend already does and has tests
    for. Sending through Flow keeps verification here and still satisfies DLT,
    which only cares that the *text* matches a registered template.

    **MSG91 answers HTTP 200 on failure.** A rejected message comes back as
    ``{"type": "error", "message": "..."}`` with a 200 status, so checking the
    status code alone reports success for messages that were never sent.

    The variable name carrying the code (``OTP`` below) has to match the
    variable in the DLT template registered in the MSG91 panel.
    """

    name = "msg91"
    ENDPOINT = "https://api.msg91.com/api/v5/flow/"

    def __init__(
        self,
        auth_key: str,
        template_id: str,
        sender: str = "",
        code_variable: str = "OTP",
        extra_variables: Optional[Dict[str, Any]] = None,
        country_code: str = "91",
        timeout_seconds: float = 10.0,
        endpoint: str = "",
        client: Optional[httpx.Client] = None,
    ):
        if not auth_key or not template_id:
            raise ValueError("msg91 channel needs EMI_MSG91_KEY and EMI_MSG91_TEMPLATE_ID")
        self.auth_key = auth_key
        self.template_id = template_id
        self.sender = sender
        self.code_variable = code_variable
        self.extra_variables = extra_variables or {}
        self.country_code = country_code
        self.timeout_seconds = timeout_seconds
        self.endpoint = endpoint or self.ENDPOINT
        self._client = client

    def send_otp(self, mobile: str, code: str, ttl_seconds: int) -> Dict[str, Any]:
        recipient: Dict[str, Any] = {"mobiles": "%s%s" % (self.country_code, mobile)}
        recipient.update(self.extra_variables)
        recipient[self.code_variable] = code

        payload: Dict[str, Any] = {
            "template_id": self.template_id,
            "short_url": "0",
            "recipients": [recipient],
        }
        if self.sender:
            payload["sender"] = self.sender

        headers = {"authkey": self.auth_key, "Content-Type": "application/json"}
        try:
            if self._client is not None:
                response = self._client.post(self.endpoint, json=payload, headers=headers)
            else:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(self.endpoint, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise OtpDeliveryError("msg91 unreachable: %s" % exc)

        if response.status_code >= 400:
            raise OtpDeliveryError(
                "msg91 rejected the message (HTTP %d): %s"
                % (response.status_code, response.text[:200]))

        try:
            body = response.json()
        except ValueError:
            raise OtpDeliveryError("msg91 returned a body that is not JSON")

        # The important check: a 200 does not mean it was sent.
        if str(body.get("type", "")).lower() != "success":
            raise OtpDeliveryError(
                "msg91 reported failure: %s" % (body.get("message") or body))

        return {"delivered": True, "channel": self.name,
                "provider_ref": body.get("message")}


class HttpChannel:
    """A generic JSON POST, for an SMS aggregator or a licensed WhatsApp BSP.

    Field names are configurable because every Indian aggregator names them
    differently, and none of them is worth a bespoke adapter until you have
    chosen one.
    """

    name = "http"

    def __init__(
        self,
        url: str,
        api_key: str = "",
        auth_header: str = "Authorization",
        auth_prefix: str = "Bearer ",
        to_field: str = "to",
        body_field: str = "message",
        extra_fields: Optional[Dict[str, Any]] = None,
        template: str = DEFAULT_TEMPLATE,
        business: str = "EMI Locker",
        country_code: str = "91",
        timeout_seconds: float = 10.0,
        client: Optional[httpx.Client] = None,
    ):
        if not url:
            raise ValueError("http channel needs EMI_OTP_HTTP_URL")
        self.url = url
        self.api_key = api_key
        self.auth_header = auth_header
        self.auth_prefix = auth_prefix
        self.to_field = to_field
        self.body_field = body_field
        self.extra_fields = extra_fields or {}
        self.template = template
        self.business = business
        self.country_code = country_code
        self.timeout_seconds = timeout_seconds
        self._client = client

    def send_otp(self, mobile: str, code: str, ttl_seconds: int) -> Dict[str, Any]:
        payload = dict(self.extra_fields)
        payload[self.to_field] = "%s%s" % (self.country_code, mobile)
        payload[self.body_field] = render(
            self.template, code, ttl_seconds, self.business)
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers[self.auth_header] = "%s%s" % (self.auth_prefix, self.api_key)
        try:
            if self._client is not None:
                response = self._client.post(self.url, json=payload, headers=headers)
            else:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(self.url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise OtpDeliveryError("otp provider unreachable: %s" % exc)
        if response.status_code >= 400:
            raise OtpDeliveryError(
                "otp provider rejected the message (HTTP %d): %s"
                % (response.status_code, response.text[:200]))
        return {"delivered": True, "channel": self.name, "provider_ref": None}


def build_channel(settings) -> OtpChannel:
    """Pick the channel named by configuration."""
    choice = (settings.otp_channel or "console").lower()
    if choice == "console":
        return ConsoleChannel(business=settings.business_name)
    if choice == "evolution":
        return EvolutionGoChannel(
            base_url=settings.wa_url,
            instance=settings.wa_instance,
            api_key=settings.wa_api_key,
            template=settings.otp_template,
            business=settings.business_name,
            country_code=settings.country_code,
        )
    if choice == "msg91":
        return Msg91Channel(
            auth_key=settings.msg91_key,
            template_id=settings.msg91_template_id,
            sender=settings.msg91_sender,
            code_variable=settings.msg91_code_variable,
            country_code=settings.country_code,
        )
    if choice == "http":
        return HttpChannel(
            url=settings.otp_http_url,
            api_key=settings.otp_http_key,
            auth_header=settings.otp_http_auth_header,
            to_field=settings.otp_http_to_field,
            body_field=settings.otp_http_body_field,
            template=settings.otp_template,
            business=settings.business_name,
            country_code=settings.country_code,
        )
    raise ValueError("unknown EMI_OTP_CHANNEL %r" % choice)
