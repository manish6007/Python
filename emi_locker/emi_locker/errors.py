"""Domain errors for the EMI Locker platform core."""
from __future__ import annotations


class DomainError(Exception):
    """Base class for all business-rule violations."""

    code = "DOMAIN_ERROR"
    http_status = 400


class PermissionDenied(DomainError):
    code = "PERMISSION_DENIED"
    http_status = 403


class SessionInvalid(PermissionDenied):
    """The token itself is no good: missing, expired, forged, ended or suspended.

    Kept apart from an ordinary 403 so a client can tell "sign in again" from
    "you may not do this". Signing a user out on every 403 would throw a
    retailer out for opening someone else's customer.
    """

    code = "SESSION_INVALID"
    http_status = 401


class NotFound(DomainError):
    code = "NOT_FOUND"
    http_status = 404


class ValidationError(DomainError):
    code = "VALIDATION_ERROR"
    http_status = 422


class InsufficientQuota(DomainError):
    code = "INSUFFICIENT_QUOTA"
    http_status = 409


class LicenseInvalid(DomainError):
    code = "LICENSE_INVALID"
    http_status = 409


class DuplicateDevice(DomainError):
    code = "DUPLICATE_DEVICE"
    http_status = 409


class PaymentVerificationError(DomainError):
    code = "PAYMENT_VERIFICATION_FAILED"
    http_status = 400


class ReplayedEvent(DomainError):
    code = "REPLAYED_EVENT"
    http_status = 200
