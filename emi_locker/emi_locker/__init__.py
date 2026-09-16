"""EMI Locker platform core.

A runnable reference implementation of the Ashish Enterprises EMI Locker
blueprint: licensing/reseller quota, customer and device onboarding, EMI
scheduling, verified payments, the overdue lifecycle and audited device
actions.

The modules here are transport-agnostic. ``api.py`` puts a small HTTP layer
on top of them to show the endpoint shape from the blueprint; the same calls
would sit behind FastAPI, NestJS or Laravel unchanged.
"""
from __future__ import annotations

from . import core, db, devices, finance, licensing, lifecycle, payments, reports  # noqa: F401
from .core import Actor, format_inr, rupees  # noqa: F401
from .errors import DomainError  # noqa: F401

__version__ = "0.1.0"
__all__ = [
    "Actor",
    "DomainError",
    "core",
    "db",
    "devices",
    "finance",
    "format_inr",
    "licensing",
    "lifecycle",
    "payments",
    "reports",
    "rupees",
]
