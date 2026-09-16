"""End-to-end walkthrough of the blueprint's production flow.

Run with::

    python -m emi_locker.demo

It uses the exact worked example from the documents: a Rs.30,000 handset,
Rs.8,000 down, Rs.22,000 financed over 11 months, sold by a retailer who is
working off activation quota allocated by a distributor.
"""
from __future__ import annotations

import datetime as _dt
import json

from . import devices as devices_mod
from . import finance as finance_mod
from . import licensing, lifecycle, payments, reports
from .core import Actor, create_user, format_inr, rupees
from .db import open_db, tx
from .errors import DomainError

WEBHOOK_SECRET = "demo-webhook-secret-not-for-production"


class DemoProvider:
    """Stand-in for an authorised EMM. Acknowledges, changes no real device."""

    name = "demo-emm-sandbox"

    def send(self, device_imei, command, context):
        return {"delivered": True, "provider_ref": "demo-%s-%s" % (command.lower(), device_imei[-4:]),
                "detail": "sandbox acknowledgement only"}


def line(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def main() -> None:  # noqa: C901 - a linear narrative reads better unsplit
    conn = open_db()

    line("1. Admin setup, network and license plans")
    with tx(conn):
        admin_id = create_user(conn, "SUPER_ADMIN", "Ashish Enterprises")
        admin = Actor(admin_id, "SUPER_ADMIN")
        ops_id = create_user(conn, "SUPER_ADMIN", "Ops Manager", actor=admin)
        ops = Actor(ops_id, "SUPER_ADMIN")
        dist_id = create_user(conn, "DISTRIBUTOR", "North Distributor", actor=admin)
        dist = Actor(dist_id, "DISTRIBUTOR")
        retailer_id = create_user(conn, "RETAILER", "Retailer A", parent_id=dist_id, actor=admin)
        retailer = Actor(retailer_id, "RETAILER", parent_id=dist_id)
        rival_id = create_user(conn, "DISTRIBUTOR", "South Distributor", actor=admin)
        rival = Actor(rival_id, "DISTRIBUTOR")

        business = licensing.create_plan(conn, admin, "BUSINESS", quota=100,
                                         price_paise=rupees(25000), validity_days=365)
        premium = licensing.create_plan(conn, admin, "PREMIUM", quota=500,
                                        price_paise=rupees(100000), validity_days=365)
    print("admin=%s distributor=%s retailer=%s" % (admin_id, dist_id, retailer_id))
    print("plans: BUSINESS=%s PREMIUM=%s" % (business, premium))

    line("2. Distributor buys a 500-activation pack; key is issued once")
    with tx(conn):
        issued = licensing.generate_license(conn, admin, premium, owner_type="DISTRIBUTOR")
    print("license %s  key=%s  (stored as %s)" % (
        issued["license_id"], issued["key"], issued["key_masked"]))
    with tx(conn):
        redeemed = licensing.redeem_license(conn, dist, issued["key"])
    print("distributor wallet after redeem:", redeemed["wallet"])

    line("3. Distributor allocates 100 activations to its retailer")
    with tx(conn):
        licensing.allocate_quota(conn, dist, retailer_id, 100, idempotency_key="alloc-1")
    with tx(conn):
        # Same request replayed by a flaky mobile network - no double spend.
        licensing.allocate_quota(conn, dist, retailer_id, 100, idempotency_key="alloc-1")
    print("distributor:", licensing.wallet(conn, dist_id))
    print("retailer   :", licensing.wallet(conn, retailer_id))

    line("4. A rival distributor tries to allocate into this retailer")
    try:
        with tx(conn):
            licensing.allocate_quota(conn, rival, retailer_id, 5)
    except DomainError as exc:
        print("blocked: [%s] %s" % (exc.code, exc))

    line("5. Retailer onboards a customer with recorded consent")
    with tx(conn):
        customer_id = finance_mod.create_customer(
            conn, retailer, retailer_id, "Ramesh Kumar", "9876543210", "Indore, MP")
        for consent in finance_mod.REQUIRED_CONSENTS:
            finance_mod.record_consent(conn, retailer, customer_id, consent, "v1",
                                       meta={"ip": "203.0.113.9"})
    print("customer %s registered, consents captured: %s" % (
        customer_id, ", ".join(finance_mod.REQUIRED_CONSENTS)))

    line("6. New finance: Rs.30,000 device, Rs.8,000 down, 11 months")
    start = _dt.date(2026, 9, 10)
    with tx(conn):
        result = finance_mod.create_finance(
            conn, retailer, customer_id, imei="490154203237518",
            product_price=rupees(30000), down_payment=rupees(8000), tenure_months=11,
            model="Galaxy A16", start_date=start, late_fee_paise=rupees(200), grace_days=5,
            idempotency_key="fin-req-1",
        )
    finance_id = result["finance_id"]
    device_id = result["device_id"]
    print("finance %s on device %s, financed %s, EMI %s x %d" % (
        finance_id, device_id, format_inr(result["principal"]),
        format_inr(result["emi_amount"]), result["tenure_months"]))
    print("one activation consumed ->", result["activation"]["wallet"])
    for row in result["schedule"][:3]:
        print("   EMI %2d  %s  due %s" % (
            row["seq"], format_inr(row["amount_paise"]), row["due_date"]))
    print("   ... EMI 11 %s due %s" % (
        format_inr(result["schedule"][-1]["amount_paise"]), result["schedule"][-1]["due_date"]))

    line("7. The same IMEI cannot be financed twice")
    with tx(conn):
        other_customer = finance_mod.create_customer(
            conn, retailer, retailer_id, "Suresh", "9998887776")
        for consent in finance_mod.REQUIRED_CONSENTS:
            finance_mod.record_consent(conn, retailer, other_customer, consent, "v1")
    try:
        with tx(conn):
            finance_mod.create_finance(
                conn, retailer, other_customer, imei="490154203237518",
                product_price=rupees(20000), down_payment=rupees(5000), tenure_months=6)
    except DomainError as exc:
        print("blocked: [%s] %s" % (exc.code, exc))
    print("retailer wallet unchanged after the failed attempt:",
          licensing.wallet(conn, retailer_id))

    line("8. Customer pays EMI 1 online - client claim vs verified webhook")
    with tx(conn):
        init = payments.initiate_payment(conn, retailer, finance_id, rupees(2000))
    print("payment %s INITIATED" % init["payment_id"])

    forged = json.dumps({"event_id": "evt-forged", "payment_id": init["payment_id"],
                         "status": "SUCCESS", "amount_paise": rupees(2000)}).encode()
    try:
        with tx(conn):
            payments.handle_webhook(conn, forged, "deadbeef", WEBHOOK_SECRET)
    except DomainError as exc:
        print("forged callback rejected: [%s] %s" % (exc.code, exc))

    body = json.dumps({"event_id": "evt-1001", "payment_id": init["payment_id"],
                       "status": "SUCCESS", "amount_paise": rupees(2000),
                       "gateway_txn_id": "pay_LmN0p1"}).encode()
    sig = payments.sign_payload(WEBHOOK_SECRET, body)
    with tx(conn):
        applied = payments.handle_webhook(conn, body, sig, WEBHOOK_SECRET)
    print("verified webhook -> EMI %s PAID, receipt %s" % (
        applied["emi_id"], applied["receipt_number"]))

    try:
        with tx(conn):
            payments.handle_webhook(conn, body, sig, WEBHOOK_SECRET)
    except DomainError as exc:
        print("gateway retry of the same event: [%s] %s" % (exc.code, exc))

    line("9. Retailer collects EMI 2 in cash")
    with tx(conn):
        cash = payments.record_cash_collection(
            conn, retailer, finance_id, rupees(2000), idempotency_key="cash-1")
    print("collection %s, receipt %s, outstanding %s" % (
        cash["collection_id"], cash["receipt_number"],
        format_inr(finance_mod.outstanding(conn, finance_id))))

    line("10. Time passes - EMI 3 goes due, then grace, then overdue")
    as_of = _dt.date(2026, 12, 20)
    with tx(conn):
        moved = lifecycle.run_daily_status_sweep(conn, ops, as_of=as_of)
    print("sweep on %s moved: %s" % (as_of, {k: len(v) for k, v in moved.items()}))
    for row in lifecycle.overdue_report(conn, as_of=as_of):
        print("overdue: finance %s, %d instalment(s), %s, %d days past due" % (
            row["finance_id"], row["overdue_count"],
            format_inr(row["overdue_amount"]), row["days_past_due"]))

    line("11. Restriction needs eligibility, a reason and a second approver")
    with tx(conn):
        cmd = devices_mod.request_command(conn, ops, device_id, "RESTRICT",
                                          reason="EMI 3 overdue beyond grace period")
    print("command %s -> %s" % (cmd["command_id"], cmd["status"]))
    try:
        with tx(conn):
            devices_mod.approve_command(conn, ops, cmd["command_id"])
    except DomainError as exc:
        print("self-approval blocked: [%s] %s" % (exc.code, exc))
    with tx(conn):
        devices_mod.approve_command(conn, admin, cmd["command_id"])
        sent = devices_mod.send_to_provider(conn, admin, cmd["command_id"], DemoProvider())
    print("dispatch -> %s via %s (%s)" % (sent["status"], sent["provider"], sent["detail"]))

    line("12. Customer clears the arrears; the device is restored")
    with tx(conn):
        payments.record_cash_collection(conn, retailer, finance_id, rupees(2000))
        lifecycle.run_daily_status_sweep(conn, ops, as_of=as_of)
        restored = devices_mod.restore_on_payment(conn, ops, finance_id, DemoProvider())
    print("restore command:", restored)
    print("device status:",
          conn.execute("SELECT status FROM devices WHERE id = ?", (device_id,)).fetchone()[0])

    line("13. Remaining instalments cleared -> finance closes itself")
    with tx(conn):
        while finance_mod.outstanding(conn, finance_id) > 0:
            emi = conn.execute(
                "SELECT id, amount_paise FROM emi_schedules WHERE finance_id = ?"
                " AND status NOT IN ('PAID','WAIVED') ORDER BY seq LIMIT 1", (finance_id,)
            ).fetchone()
            payments.record_cash_collection(conn, retailer, finance_id, emi["amount_paise"],
                                            emi_id=emi["id"])
    print(json.dumps(lifecycle.closure_certificate(conn, finance_id), indent=2))

    line("14. Admin dashboard and audit trail")
    print(json.dumps(reports.admin_dashboard(conn, admin), indent=2))
    print("\naudit events recorded for %s:" % finance_id)
    for row in reports.audit_trail(conn, admin, finance_id):
        print("   %s  %-24s by %s" % (row["created_at"], row["action"], row["actor_id"]))
    total_events = conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
    print("\ntotal audit events in this run: %d" % total_events)


if __name__ == "__main__":
    main()
