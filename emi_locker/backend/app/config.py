"""Backend configuration.

Everything here is read from the environment so the same code runs on your
laptop and on a server. The defaults are the *local testing* values - they are
deliberately insecure and the app refuses to start with them when
``EMI_ENV=production``.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from typing import List

DEV_JWT_SECRET = "dev-only-jwt-secret-change-me"
DEV_WEBHOOK_SECRET = "dev-only-webhook-secret-change-me"

# Kept here rather than imported from notifications, so that importing config
# never drags in an HTTP client.
DEFAULT_OTP_TEMPLATE = (
    "{code} is your {business} verification code. It is valid for {minutes} "
    "minutes. Do not share it with anyone."
)


@dataclass
class Settings:
    env: str = field(default_factory=lambda: os.getenv("EMI_ENV", "local"))
    db_path: str = field(default_factory=lambda: os.getenv("EMI_DB", "emi_locker.db"))
    jwt_secret: str = field(
        default_factory=lambda: os.getenv("EMI_JWT_SECRET", DEV_JWT_SECRET))
    webhook_secret: str = field(
        default_factory=lambda: os.getenv("EMI_WEBHOOK_SECRET", DEV_WEBHOOK_SECRET))
    # Session length is the biggest driver of the OTP bill: a short session
    # means a fresh code on almost every visit. Business users get a long one;
    # the admin panel does not, because it can suspend accounts, issue licences
    # and move commission rates, and it is often open on a shared desktop.
    admin_session_minutes: int = field(
        default_factory=lambda: int(os.getenv("EMI_ADMIN_SESSION_MIN", "720")))
    app_session_minutes: int = field(
        default_factory=lambda: int(os.getenv("EMI_APP_SESSION_MIN", "43200")))
    otp_ttl_seconds: int = field(
        default_factory=lambda: int(os.getenv("EMI_OTP_TTL_SEC", "300")))
    otp_max_attempts: int = field(
        default_factory=lambda: int(os.getenv("EMI_OTP_MAX_ATTEMPTS", "5")))
    cors_origins: List[str] = field(
        default_factory=lambda: os.getenv("EMI_CORS", "*").split(","))

    # --- how a one-time code reaches the customer -------------------------
    otp_channel: str = field(
        default_factory=lambda: os.getenv("EMI_OTP_CHANNEL", "console"))
    otp_template: str = field(
        default_factory=lambda: os.getenv("EMI_OTP_TEMPLATE", "") or DEFAULT_OTP_TEMPLATE)
    business_name: str = field(
        default_factory=lambda: os.getenv("EMI_BUSINESS_NAME", "EMI Locker"))
    country_code: str = field(
        default_factory=lambda: os.getenv("EMI_COUNTRY_CODE", "91"))

    # Evolution Go (unofficial WhatsApp gateway)
    wa_url: str = field(default_factory=lambda: os.getenv("EMI_WA_URL", ""))
    wa_instance: str = field(default_factory=lambda: os.getenv("EMI_WA_INSTANCE", ""))
    wa_api_key: str = field(default_factory=lambda: os.getenv("EMI_WA_API_KEY", ""))

    # MSG91 Flow API (SMS)
    msg91_key: str = field(default_factory=lambda: os.getenv("EMI_MSG91_KEY", ""))
    msg91_template_id: str = field(
        default_factory=lambda: os.getenv("EMI_MSG91_TEMPLATE_ID", ""))
    msg91_sender: str = field(default_factory=lambda: os.getenv("EMI_MSG91_SENDER", ""))
    msg91_code_variable: str = field(
        default_factory=lambda: os.getenv("EMI_MSG91_CODE_VAR", "OTP"))

    # Generic JSON provider (SMS aggregator or licensed WhatsApp BSP)
    otp_http_url: str = field(default_factory=lambda: os.getenv("EMI_OTP_HTTP_URL", ""))
    otp_http_key: str = field(default_factory=lambda: os.getenv("EMI_OTP_HTTP_KEY", ""))
    otp_http_auth_header: str = field(
        default_factory=lambda: os.getenv("EMI_OTP_HTTP_AUTH_HEADER", "Authorization"))
    otp_http_to_field: str = field(
        default_factory=lambda: os.getenv("EMI_OTP_HTTP_TO_FIELD", "to"))
    otp_http_body_field: str = field(
        default_factory=lambda: os.getenv("EMI_OTP_HTTP_BODY_FIELD", "message"))

    def session_minutes_for(self, role: str) -> int:
        return (self.admin_session_minutes if role == "SUPER_ADMIN"
                else self.app_session_minutes)

    @property
    def is_local(self) -> bool:
        return self.env != "production"

    @property
    def expose_otp(self) -> bool:
        """Return the OTP in the API response so you can log in without SMS.

        Local only. In production this must be false or every account on the
        system is one API call away from being taken over.
        """
        return self.is_local and os.getenv("EMI_EXPOSE_OTP", "1") == "1"

    def validate(self) -> None:
        if self.is_local:
            return
        problems = []
        if self.jwt_secret == DEV_JWT_SECRET:
            problems.append("EMI_JWT_SECRET is still the development default")
        if self.webhook_secret == DEV_WEBHOOK_SECRET:
            problems.append("EMI_WEBHOOK_SECRET is still the development default")
        if self.expose_otp:
            problems.append("EMI_EXPOSE_OTP must be 0 in production")
        if "*" in self.cors_origins:
            problems.append("EMI_CORS must list real origins in production")
        if self.otp_channel == "console":
            problems.append(
                "EMI_OTP_CHANNEL is still 'console', which only prints codes to"
                " the server log - nobody would receive one")
        if self.otp_channel == "evolution" and not (
                self.wa_url and self.wa_instance and self.wa_api_key):
            problems.append(
                "EMI_OTP_CHANNEL=evolution needs EMI_WA_URL, EMI_WA_INSTANCE"
                " and EMI_WA_API_KEY")
        if self.otp_channel == "msg91" and not (
                self.msg91_key and self.msg91_template_id):
            problems.append(
                "EMI_OTP_CHANNEL=msg91 needs EMI_MSG91_KEY and"
                " EMI_MSG91_TEMPLATE_ID")
        if self.otp_channel == "http" and not self.otp_http_url:
            problems.append("EMI_OTP_CHANNEL=http needs EMI_OTP_HTTP_URL")
        if problems:
            raise RuntimeError(
                "refusing to start in production mode:\n  - " + "\n  - ".join(problems))


settings = Settings()


def new_secret() -> str:
    return secrets.token_urlsafe(32)
