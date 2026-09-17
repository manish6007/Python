"""Create a local database with enough data to exercise both apps.

Run once before starting the API::

    python -m backend.seed

It prints the mobile numbers to sign in with. Every login is by OTP, and in
local mode the code is printed by the API and returned in the response, so no
SMS provider is needed.
"""
from __future__ import annotations

import argparse
import os
import sys

from emi_locker import finance as finance_mod
from emi_locker import licensing
from emi_locker.core import Actor, create_user, format_inr, rupees
from emi_locker.db import file_db, tx

ADMIN_MOBILE = "9000000001"
DISTRIBUTOR_MOBILE = "9000000002"
RETAILER_MOBILE = "9000000003"
RETAILER2_MOBILE = "9000000004"
CUSTOMER_MOBILE = "9876543210"
CUSTOMER2_MOBILE = "9876543211"

DEMO_IMEI = "490154203237518"
DEMO_IMEI_2 = "356938035643809"
DEMO_IMEI_3 = "352099001761481"
SPARE_IMEI = "860321035678902"


def seed(db_path: str, reset: bool = False) -> None:
    if reset:
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(db_path + suffix):
                os.unlink(db_path + suffix)

    conn = file_db(db_path)
    existing = conn.execute(
        "SELECT id FROM users WHERE mobile = ?", (ADMIN_MOBILE,)).fetchone()
    if existing:
        print("database %s is already seeded - pass --reset to rebuild it" % db_path)
        return

    with tx(conn):
        admin_id = create_user(conn, "SUPER_ADMIN", "Ashish Enterprises", ADMIN_MOBILE)
        admin = Actor(admin_id, "SUPER_ADMIN")
        dist_id = create_user(conn, "DISTRIBUTOR", "North Distributor", DISTRIBUTOR_MOBILE,
                              actor=admin)
        dist = Actor(dist_id, "DISTRIBUTOR")
        retailer_id = create_user(conn, "RETAILER", "Sharma Mobiles", RETAILER_MOBILE,
                                  parent_id=dist_id, actor=admin)
        retailer = Actor(retailer_id, "RETAILER", parent_id=dist_id)
        # A second retailer, so the Distributor app has a network to compare.
        retailer2_id = create_user(conn, "RETAILER", "Verma Telecom", RETAILER2_MOBILE,
                                   parent_id=dist_id, actor=admin)
        retailer2 = Actor(retailer2_id, "RETAILER", parent_id=dist_id)

        licensing.create_plan(conn, admin, "STARTER", 10, rupees(5000), 30)
        licensing.create_plan(conn, admin, "BUSINESS", 100, rupees(25000), 365)
        premium = licensing.create_plan(conn, admin, "PREMIUM", 500, rupees(100000), 365)

        issued = licensing.generate_license(conn, admin, premium, "DISTRIBUTOR")
        licensing.redeem_license(conn, dist, issued["key"])
        licensing.allocate_quota(conn, dist, retailer_id, 100)
        licensing.allocate_quota(conn, dist, retailer2_id, 50)

    with tx(conn):
        # One customer with a live finance, so the Customer app has something
        # to show on first login.
        cust_id = finance_mod.create_customer(
            conn, retailer, retailer_id, "Ramesh Kumar", CUSTOMER_MOBILE, "Indore, MP")
        for consent in finance_mod.REQUIRED_CONSENTS:
            finance_mod.record_consent(conn, retailer, cust_id, consent, "v1")
        result = finance_mod.create_finance(
            conn, retailer, cust_id, imei=DEMO_IMEI,
            product_price=rupees(30000), down_payment=rupees(8000), tenure_months=11,
            model="Galaxy A16", late_fee_paise=rupees(200), grace_days=5)

        # A second customer with consent captured but no finance yet, so you
        # can walk the "new finance" flow in the Retailer app immediately.
        cust2_id = finance_mod.create_customer(
            conn, retailer, retailer_id, "Sunita Devi", CUSTOMER2_MOBILE, "Bhopal, MP")
        for consent in finance_mod.REQUIRED_CONSENTS:
            finance_mod.record_consent(conn, retailer, cust2_id, consent, "v1")

    with tx(conn):
        # One live finance at the second retailer too, so distributor reports
        # have more than a single row in them.
        cust3_id = finance_mod.create_customer(
            conn, retailer2, retailer2_id, "Imran Sheikh", "9876543212", "Dewas, MP")
        for consent in finance_mod.REQUIRED_CONSENTS:
            finance_mod.record_consent(conn, retailer2, cust3_id, consent, "v1")
        finance_mod.create_finance(
            conn, retailer2, cust3_id, imei=DEMO_IMEI_3,
            product_price=rupees(18000), down_payment=rupees(4000), tenure_months=7,
            model="Redmi 14C", grace_days=5)

    print("seeded %s\n" % db_path)
    print("Sign in with these mobile numbers (OTP is printed by the API):\n")
    print("  Retailer app    %s   Sharma Mobiles" % RETAILER_MOBILE)
    print("  Retailer app    %s   Verma Telecom" % RETAILER2_MOBILE)
    print("  Customer app    %s   Ramesh Kumar (has a live finance)" % CUSTOMER_MOBILE)
    print("  Customer app    %s   Sunita Devi (no finance yet)" % CUSTOMER2_MOBILE)
    print("  Distributor app %s   North Distributor" % DISTRIBUTOR_MOBILE)
    print("  Admin panel     %s   Ashish Enterprises (web)" % ADMIN_MOBILE)
    print("\nSeeded finance %s: %s financed over 11 months, EMI %s" % (
        result["finance_id"], format_inr(result["principal"]),
        format_inr(result["emi_amount"])))
    print("Spare IMEIs for new finances: %s, %s" % (DEMO_IMEI_2, SPARE_IMEI))
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a local EMI Locker database")
    parser.add_argument("--db", default=os.getenv("EMI_DB", "emi_locker.db"))
    parser.add_argument("--reset", action="store_true", help="delete and rebuild")
    args = parser.parse_args()
    seed(args.db, args.reset)


if __name__ == "__main__":
    sys.exit(main())
