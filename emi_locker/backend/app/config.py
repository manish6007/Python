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


@dataclass
class Settings:
    env: str = field(default_factory=lambda: os.getenv("EMI_ENV", "local"))
    db_path: str = field(default_factory=lambda: os.getenv("EMI_DB", "emi_locker.db"))
    jwt_secret: str = field(
        default_factory=lambda: os.getenv("EMI_JWT_SECRET", DEV_JWT_SECRET))
    webhook_secret: str = field(
        default_factory=lambda: os.getenv("EMI_WEBHOOK_SECRET", DEV_WEBHOOK_SECRET))
    token_ttl_minutes: int = field(
        default_factory=lambda: int(os.getenv("EMI_TOKEN_TTL_MIN", "720")))
    otp_ttl_seconds: int = field(
        default_factory=lambda: int(os.getenv("EMI_OTP_TTL_SEC", "300")))
    otp_max_attempts: int = field(
        default_factory=lambda: int(os.getenv("EMI_OTP_MAX_ATTEMPTS", "5")))
    cors_origins: List[str] = field(
        default_factory=lambda: os.getenv("EMI_CORS", "*").split(","))

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
        if problems:
            raise RuntimeError(
                "refusing to start in production mode:\n  - " + "\n  - ".join(problems))


settings = Settings()


def new_secret() -> str:
    return secrets.token_urlsafe(32)
