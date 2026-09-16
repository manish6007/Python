"""Domain errors for the EMI Locker platform core."""
from __future__ import annotations


class DomainError(Exception):
    """Base class for all business-rule violations."""

    code = "DOMAIN_ERROR"
    http_status = 400


class PermissionDenied(DomainError):
    code = "PERMISSION_DENIED"
    http_status = 403


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
