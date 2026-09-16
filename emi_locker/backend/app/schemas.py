"""Request bodies for the API.

All money crosses this boundary as **integer paise**. The apps convert once,
at the edge, so no rupee/paise confusion can reach the ledger.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SendOtpIn(BaseModel):
    mobile: str = Field(min_length=6, max_length=20)


class VerifyOtpIn(BaseModel):
    mobile: str
    code: str = Field(min_length=4, max_length=8)


class CustomerIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    mobile: str
    address: Optional[str] = None


class ConsentIn(BaseModel):
    consent_type: str
    doc_version: str = "v1"
    channel: str = "APP"
    meta: Optional[Dict[str, Any]] = None


class FinanceIn(BaseModel):
    customer_id: str
    imei: str
    model: Optional[str] = None
    product_price: int = Field(gt=0, description="paise")
    down_payment: int = Field(ge=0, description="paise")
    tenure_months: int = Field(gt=0, le=60)
    late_fee_paise: int = 0
    grace_days: int = Field(default=5, ge=0, le=60)


class QuoteIn(BaseModel):
    product_price: int = Field(gt=0)
    down_payment: int = Field(ge=0)
    tenure_months: int = Field(gt=0, le=60)


class PaymentIn(BaseModel):
    finance_id: str
    amount_paise: int = Field(gt=0)
    emi_id: Optional[str] = None


class CollectionIn(BaseModel):
    finance_id: str
    amount_paise: int = Field(gt=0)
    emi_id: Optional[str] = None
    mode: str = "CASH"


class RedeemIn(BaseModel):
    key: str


class AllocateIn(BaseModel):
    to_owner: str
    quota: int = Field(gt=0)
    license_id: Optional[str] = None


class DeviceActionIn(BaseModel):
    device_id: str
    command: str
    reason: str = Field(min_length=3)


class MockPayIn(BaseModel):
    """Local-only: stands in for the customer completing payment at a gateway."""

    payment_id: str
    outcome: str = Field(default="SUCCESS", pattern="^(SUCCESS|FAILED)$")


class ScheduleRow(BaseModel):
    id: str
    seq: int
    amount_paise: int
    due_date: str
    status: str
    paid_at: Optional[str] = None


class ScheduleOut(BaseModel):
    finance_id: str
    schedule: List[ScheduleRow]
