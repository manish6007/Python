"""Shared fixtures for the EMI Locker test-suite."""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict

from emi_locker import finance, licensing
from emi_locker.core import Actor, create_user, rupees
from emi_locker.db import open_db, tx

VALID_IMEI = "490154203237518"
OTHER_IMEI = "356938035643809"
SECRET = "test-secret"


def build_world(quota: int = 100, cross_thread: bool = False) -> Dict[str, Any]:
    """Admin + distributor + retailer, with `quota` activations at the retailer."""
    conn = open_db(same_thread=not cross_thread)
    with tx(conn):
        admin_id = create_user(conn, "SUPER_ADMIN", "Admin")
        admin = Actor(admin_id, "SUPER_ADMIN")
        dist_id = create_user(conn, "DISTRIBUTOR", "Dist", actor=admin)
        dist = Actor(dist_id, "DISTRIBUTOR")
        retailer_id = create_user(conn, "RETAILER", "Retailer", parent_id=dist_id, actor=admin)
        retailer = Actor(retailer_id, "RETAILER", parent_id=dist_id)
        plan = licensing.create_plan(conn, admin, "TEST", quota=max(quota, 1),
                                     price_paise=rupees(1000), validity_days=365)
        issued = licensing.generate_license(conn, admin, plan, owner_type="DISTRIBUTOR",
                                            quota=max(quota * 10, 1000))
        licensing.redeem_license(conn, dist, issued["key"])
        if quota:
            licensing.allocate_quota(conn, dist, retailer_id, quota)
    return {
        "conn": conn,
        "admin": admin,
        "dist": dist,
        "retailer": retailer,
        "admin_id": admin_id,
        "dist_id": dist_id,
        "retailer_id": retailer_id,
        "plan": plan,
        "license_id": issued["license_id"],
        "license_key": issued["key"],
    }


def make_customer(world, name="Customer", mobile="9876543210", consents=True) -> str:
    conn, retailer = world["conn"], world["retailer"]
    with tx(conn):
        cid = finance.create_customer(conn, retailer, world["retailer_id"], name, mobile)
        if consents:
            for consent in finance.REQUIRED_CONSENTS:
                finance.record_consent(conn, retailer, cid, consent, "v1")
    return cid


def make_finance(world, customer_id=None, imei=VALID_IMEI, price=30000, down=8000,
                 tenure=11, start=None, **kwargs):
    conn, retailer = world["conn"], world["retailer"]
    customer_id = customer_id or make_customer(world)
    with tx(conn):
        return finance.create_finance(
            conn, retailer, customer_id, imei=imei,
            product_price=rupees(price), down_payment=rupees(down),
            tenure_months=tenure, start_date=start or _dt.date(2026, 1, 10), **kwargs
        )
