"""No EMI is ever marked paid without a verified, non-replayed gateway event."""
from __future__ import annotations

import json

import pytest

from emi_locker import finance, payments
from emi_locker.core import rupees
from emi_locker.db import tx
from emi_locker.errors import (
    PaymentVerificationError,
    ReplayedEvent,
    ValidationError,
)
from tests.helpers import SECRET, build_world, make_finance


def setup_payment(world, amount=rupees(2000)):
    conn = world["conn"]
    result = make_finance(world)
    with tx(conn):
        init = payments.initiate_payment(conn, world["retailer"], result["finance_id"], amount)
    return result, init


def webhook_body(payment_id, amount=rupees(2000), event_id="evt-1", status="SUCCESS", **extra):
    payload = {"event_id": event_id, "payment_id": payment_id, "status": status,
               "amount_paise": amount, "gateway_txn_id": "gw_123"}
    payload.update(extra)
    return json.dumps(payload).encode()


def test_initiating_a_payment_does_not_move_the_ledger():
    world = build_world()
    result, init = setup_payment(world)
    assert init["status"] == "INITIATED"
    schedule = finance.get_schedule(world["conn"], result["finance_id"])
    assert schedule[0]["status"] == "UPCOMING"
    assert finance.outstanding(world["conn"], result["finance_id"]) == rupees(22000)


def test_forged_signature_is_rejected():
    world = build_world()
    _, init = setup_payment(world)
    body = webhook_body(init["payment_id"])
    with pytest.raises(PaymentVerificationError):
        with tx(world["conn"]):
            payments.handle_webhook(world["conn"], body, "not-a-signature", SECRET)


def test_signature_from_the_wrong_secret_is_rejected():
    world = build_world()
    _, init = setup_payment(world)
    body = webhook_body(init["payment_id"])
    bad = payments.sign_payload("attacker-secret", body)
    with pytest.raises(PaymentVerificationError):
        with tx(world["conn"]):
            payments.handle_webhook(world["conn"], body, bad, SECRET)


def test_tampered_body_invalidates_the_signature():
    world = build_world()
    _, init = setup_payment(world)
    body = webhook_body(init["payment_id"])
    sig = payments.sign_payload(SECRET, body)
    tampered = body.replace(b'"amount_paise": 200000', b'"amount_paise": 1')
    with pytest.raises(PaymentVerificationError):
        with tx(world["conn"]):
            payments.handle_webhook(world["conn"], tampered, sig, SECRET)


def test_amount_mismatch_is_refused_even_with_a_valid_signature():
    world = build_world()
    result, init = setup_payment(world)
    body = webhook_body(init["payment_id"], amount=rupees(1))
    sig = payments.sign_payload(SECRET, body)
    with tx(world["conn"]):
        out = payments.handle_webhook(world["conn"], body, sig, SECRET)
    assert out["status"] == "REJECTED"
    assert "amount mismatch" in out["reason"]
    # The refusal is committed, not rolled back: reconciliation needs the trail.
    logged = world["conn"].execute(
        "SELECT COUNT(*) c FROM audit_logs WHERE action = 'payment.amount_mismatch'"
    ).fetchone()["c"]
    assert logged == 1
    assert finance.get_schedule(world["conn"], result["finance_id"])[0]["status"] == "UPCOMING"


def test_verified_webhook_marks_the_emi_paid_and_issues_a_receipt():
    world = build_world()
    result, init = setup_payment(world)
    body = webhook_body(init["payment_id"])
    sig = payments.sign_payload(SECRET, body)
    with tx(world["conn"]):
        applied = payments.handle_webhook(world["conn"], body, sig, SECRET)
    assert applied["status"] == "SUCCESS"
    assert applied["receipt_number"]
    schedule = finance.get_schedule(world["conn"], result["finance_id"])
    assert schedule[0]["status"] == "PAID"
    assert finance.outstanding(world["conn"], result["finance_id"]) == rupees(20000)


def test_replayed_event_does_not_pay_a_second_instalment():
    world = build_world()
    result, init = setup_payment(world)
    body = webhook_body(init["payment_id"])
    sig = payments.sign_payload(SECRET, body)
    with tx(world["conn"]):
        payments.handle_webhook(world["conn"], body, sig, SECRET)
    with pytest.raises(ReplayedEvent):
        with tx(world["conn"]):
            payments.handle_webhook(world["conn"], body, sig, SECRET)
    paid = [r for r in finance.get_schedule(world["conn"], result["finance_id"])
            if r["status"] == "PAID"]
    assert len(paid) == 1
    receipts = world["conn"].execute("SELECT COUNT(*) c FROM receipts").fetchone()["c"]
    assert receipts == 1


def test_failed_status_leaves_the_instalment_unpaid():
    world = build_world()
    result, init = setup_payment(world)
    body = webhook_body(init["payment_id"], status="FAILED")
    sig = payments.sign_payload(SECRET, body)
    with tx(world["conn"]):
        out = payments.handle_webhook(world["conn"], body, sig, SECRET)
    assert out["status"] == "FAILED"
    assert finance.get_schedule(world["conn"], result["finance_id"])[0]["status"] == "UPCOMING"


def test_webhook_for_an_unknown_payment_is_refused():
    world = build_world()
    setup_payment(world)
    body = webhook_body("PAY-9999999")
    sig = payments.sign_payload(SECRET, body)
    with pytest.raises(PaymentVerificationError):
        with tx(world["conn"]):
            payments.handle_webhook(world["conn"], body, sig, SECRET)


def test_webhook_without_event_id_is_refused():
    world = build_world()
    _, init = setup_payment(world)
    body = json.dumps({"payment_id": init["payment_id"], "status": "SUCCESS",
                       "amount_paise": rupees(2000)}).encode()
    sig = payments.sign_payload(SECRET, body)
    with pytest.raises(PaymentVerificationError):
        with tx(world["conn"]):
            payments.handle_webhook(world["conn"], body, sig, SECRET)


def test_cash_collection_must_match_the_instalment():
    world = build_world()
    result = make_finance(world)
    with pytest.raises(ValidationError):
        with tx(world["conn"]):
            payments.record_cash_collection(world["conn"], world["retailer"],
                                            result["finance_id"], rupees(1500))


def test_cash_collection_is_idempotent_and_leaves_one_receipt():
    world = build_world()
    result = make_finance(world)
    conn = world["conn"]
    for _ in range(2):
        with tx(conn):
            payments.record_cash_collection(conn, world["retailer"], result["finance_id"],
                                            rupees(2000), idempotency_key="dup-click")
    assert conn.execute("SELECT COUNT(*) c FROM receipts").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM collections").fetchone()["c"] == 1
    assert finance.outstanding(conn, result["finance_id"]) == rupees(20000)


def test_receipt_numbers_are_unique_and_sequential():
    world = build_world()
    result = make_finance(world)
    conn = world["conn"]
    numbers = []
    for _ in range(3):
        with tx(conn):
            out = payments.record_cash_collection(conn, world["retailer"],
                                                  result["finance_id"], rupees(2000))
            numbers.append(out["receipt_number"])
    assert len(set(numbers)) == 3
    assert numbers == sorted(numbers)


def test_paying_every_instalment_closes_the_finance():
    world = build_world()
    result = make_finance(world)
    conn = world["conn"]
    with tx(conn):
        for _ in range(11):
            payments.record_cash_collection(conn, world["retailer"], result["finance_id"],
                                            rupees(2000))
    assert finance.outstanding(conn, result["finance_id"]) == 0
    status = conn.execute("SELECT status FROM finance_accounts WHERE id = ?",
                          (result["finance_id"],)).fetchone()["status"]
    assert status == "COMPLETED"
    device = conn.execute("SELECT status FROM devices WHERE id = ?",
                          (result["device_id"],)).fetchone()["status"]
    assert device == "COMPLETED"
