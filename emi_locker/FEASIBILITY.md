# EMI Locker platform — feasibility assessment

**Question asked:** can the two Ashish Enterprises workflow documents
(*Complete Workflow* and *License Key & Reseller Business Model*) actually be
built?

**Short answer: yes, and most of it is ordinary software.** Nothing in either
document requires an unsolved problem. The blueprint is unusually well
specified — it already names the entities, the endpoints, the status model and
the security rules, and those rules are the right ones.

To make that answer concrete rather than a claim, this directory contains a
**working implementation of the risky parts of the core**, with 86 tests. The
paragraphs below separate what is a coding job from what is not.

---

## 1. What is proven here, not just asserted

`python -m emi_locker.demo` runs the document's own worked example end to end:
a ₹30,000 handset, ₹8,000 down, ₹22,000 over 11 months, sold by a retailer
working off quota allocated by a distributor, through payment, overdue,
restriction, restore and closure.

The parts of the blueprint that are easy to get wrong — and are therefore the
ones worth proving before a rupee is spent on app screens — each have a test:

| Blueprint rule | Where it lives | Test that proves it |
|---|---|---|
| "Quota deduction must be atomic and idempotent" | `licensing.consume_activation` | `test_concurrent_activations_cannot_oversell_the_wallet` — 20 simultaneous requests against a balance of 5 yield exactly 5 activations |
| "Double-click must not consume two units" | idempotency keys | `test_allocation_is_idempotent_under_retry`, `test_retry_of_the_same_request_creates_one_finance` |
| "Never mark an EMI paid from a client-side success response" | `payments.handle_webhook` | `test_forged_signature_is_rejected`, `test_tampered_body_invalidates_the_signature`, `test_amount_mismatch_is_refused_even_with_a_valid_signature` |
| Gateway retries must not pay twice | `webhook_events` replay table | `test_replayed_event_does_not_pay_a_second_instalment` |
| "Failed activation must roll back quota" | single-transaction registration | `test_failed_activation_leaves_no_device_row_and_no_lost_quota` |
| "Duplicate IMEI must be blocked" | partial unique index + Luhn check | `test_duplicate_live_imei_is_blocked`, `test_imei_luhn_validation` |
| "Distributor cannot modify another distributor's retailers" | `core.assert_can_touch_retailer` | `test_distributor_cannot_touch_another_distributors_retailer`, `test_distributor_sees_only_its_own_retailers_in_reports` |
| "Expired/suspended license cannot create new activations" | `licensing.effective_license` | `test_expired_license_stops_new_activations`, `test_suspended_license_stops_new_activations` |
| "Every license movement must create an audit event" | `core.audit` + SQLite triggers | `test_every_license_movement_is_audited`, `test_audit_rows_cannot_be_updated_or_deleted` |
| EMI schedule must reconcile to the paise | `finance.build_schedule` | `test_schedule_always_sums_to_the_financed_amount` (property-style, 5 amount/tenure pairs) |
| Device action needs eligibility, a reason and an approver | `devices.request_command` | `test_restriction_needs_a_second_approver`, `test_payment_between_approval_and_dispatch_cancels_the_restriction` |

Two of those tests found real bugs while this was being written, which is the
point of writing them first:

1. **Allocated quota had no backing license.** A retailer's balance is pushed
   down by its distributor, so the retailer holds no license row of its own.
   The first version happily let a retailer keep activating after the
   distributor's subscription expired — the wallet outlived the thing that paid
   for it. Fixed by `licensing.effective_license`, which resolves validity
   through the allocation chain.
2. **The amount-mismatch incident was rolled back with its own exception.** A
   gateway reporting a different figure than the one we priced is a
   reconciliation incident that must be visible afterwards; raising inside the
   caller's transaction erased the audit row that recorded it. `handle_webhook`
   now *returns* a `REJECTED` result for well-formed events it refuses, so the
   refusal and its audit trail commit together.

A later review of the money path found six more, all reproduced against the
running API before being fixed, all now pinned by tests in
`backend/tests/test_payment_integrity.py`:

3. **A customer could clear a ₹2,000 instalment by paying ₹1.** The webhook
   checked that the gateway paid what we *asked for*, but nothing checked that
   what we asked for matched the instalment. The cash path had that check; the
   online path never did.
4. **Quoting another account's instalment id marked that instalment paid.**
   The id was never checked against the finance being paid, so money recorded
   against one account credited a different one.
5. **A restriction was never lifted by payment.** `restore_on_payment` existed
   and was called only by the demo script, so the production path could
   restrict a device and never release it — while the customer app promised
   that clearing the arrears would.
6. **Quota an admin allocated could never be spent.** The wallet showed a
   balance and every activation against it was refused, because nothing backed
   it.
7. **Two accounts using the same idempotency key collided.** The key was
   global, so the second caller received the first one's finance record and
   schedule, and their own request was silently never performed.
8. **System-raised device commands violated a foreign key**, because they
   wrote the string `"SYSTEM"` into a column referencing `users`.

Both sets were design errors in the sort of code that looks obviously correct
on a whiteboard. That is the argument for building this core first — and for
reviewing the money path separately from the happy path, because every one of
these passed the happy-path tests.

---

## 2. What is a coding job (all of it, essentially)

Everything in the *Complete Workflow* document and sections 1–21 of the
*License* document is standard transactional business software:

- admin setup, roles and permissions, distributor/retailer hierarchy;
- customer registration, consent capture, document storage;
- finance pricing, agreement snapshot, EMI schedule generation;
- payment initiation, verified webhooks, receipts, cash collection ledger;
- reminders, overdue escalation, grace periods, late fees;
- license plans, keys, wallets, allocation, activation, renewal, transfer;
- commissions, dashboards, reports, audit logs;
- three apps and a website on top of one API.

None of it is technically novel. The volume is real — this is a genuine
multi-month build, not a weekend — but there is no step where the answer is
"that can't be done".

---

## 3. What is *not* a coding job — read this part twice

These four items decide the project far more than the code does. Three of them
cannot be solved by writing software at all.

### 3.1 Locking the phone is a provisioning problem, not an API call

This is the single biggest gap between "EMI Locker" as a name and what an app
can do. **An ordinary Android app installed from the Play Store cannot restrict
another device, and cannot lock a handset by IMEI.** Restriction requires a
Device Policy Controller running in **Device Owner** mode, which can only be
established at provisioning time — factory-reset QR flow, zero-touch
enrolment, or an EMM token — driven through the Android Management API or a
licensed EMM partner.

Practical consequences:

- **The retailer must enrol the handset at the point of sale**, before or
  during first setup. A device sold and set up normally cannot be brought under
  management afterwards without a factory reset.
- **You need a device-management provider**: Android Management API directly
  (Google's own, requires an enterprise setup), or a commercial EMM. This is a
  contract and an integration, not a library import.
- **Google Play reviews this category closely.** Apps in the device-financing
  space are held to specific policy requirements around disclosure, consent and
  what may be restricted. Plan for a policy review cycle, and design so that
  restriction is a documented, consented term of the agreement rather than a
  surprise.
- **iOS is effectively out of scope** for this model.

The blueprint already says this (section 8: *"authorized Android Enterprise /
device-management architecture … not arbitrary phone-lock capability"*). The
code here follows it honestly: `devices.py` records who requested a restriction,
why, who approved it, and what the provider replied — and the default provider
**reports that nothing was sent**, because nothing was. Wiring a real EMM in is
one adapter class; obtaining the right to use one is a business task.

### 3.2 The regulatory question is a lawyer's, not a developer's

Whether this is "our own sales on instalments" or "facilitating lending" is a
legal determination with very different obligations attached. If any part of it
is credit originated or facilitated for a regulated lender, India's digital
lending rules bring in disclosure, cooling-off, data-localisation, recovery
practice and grievance requirements that shape the product, not just the
paperwork. KYC handling, data retention, and recovery/repossession conduct are
regulated regardless. **Get this assessed before the build settles**, because
the answer changes screens, consent copy, retention windows and reporting.

The compliance note at the end of the reseller document says the same thing,
and it is correct to say it.

### 3.3 Payments need a merchant account

The webhook verification is implemented here and tested. What cannot be coded
is the merchant onboarding with a compliant gateway, the settlement account,
and the reconciliation process with your finance team. Start that paperwork
early — it is routinely the long pole.

### 3.4 Collection conduct

Restricting someone's phone over an overdue instalment is a serious action with
real consequences for the person holding it. The controls in `devices.py`
(eligibility check, mandatory reason, a second approver, a re-check immediately
before dispatch so a customer who has just paid is never locked, automatic
restore when arrears clear) are deliberate. Keep them. They protect customers
from a mistake and protect the business from a dispute it would lose.

---

## 4. Recommended build order

The blueprint's own phasing (section 27) is sound. One change: **build and test
the money and quota core before any app screen exists**, which is what this
directory is.

| Phase | Scope | Rough effort |
|---|---|---|
| 0 | Domain core: licensing, finance, EMI, payments, RBAC, audit — with tests | *done here, as a reference implementation* |
| 1 | Production backend: real DB (PostgreSQL), OTP auth, sessions, file storage, migrations | 4–6 weeks |
| 2 | Payment gateway integration, reconciliation, receipts, commission | 3–4 weeks |
| 3 | Super Admin panel (web) | 4–6 weeks |
| 4 | Retailer app + Customer app | 8–10 weeks |
| 5 | Distributor app, reports, notifications (SMS/WhatsApp/push) | 4–6 weeks |
| 6 | Device-management integration + enrolment flow at point of sale | 4–8 weeks, **gated on the EMM contract** |
| 7 | Security testing, load testing, backup/restore drill, Play review, go-live | 3–4 weeks |

That is roughly **6–9 months for a small team (2 backend, 2 mobile, 1 web,
part-time QA/design)** to a real production launch, with phase 6 the one most
likely to slip for non-technical reasons. The MVP scope in section 28 of the
blueprint is the right cut: Customer app, Retailer app, admin panel, finance,
EMI, payments, receipts, collection, outstanding — distributor and advanced
commission later.

### Stack

The blueprint's suggestion is fine and needs no argument: **PostgreSQL,
Node.js/NestJS or Laravel, React/Next.js admin, Flutter apps, REST**. Two
notes from building this:

- Use **integer paise** everywhere in the money path. No floats, no decimals
  from JSON. Every amount in this implementation is an integer.
- Let the **database enforce the invariants** that must not be violated —
  partial unique index on live IMEIs, `CHECK (used + reserved <= total)` on
  wallets, append-only triggers on the audit table. Application code gets
  refactored; constraints do not quietly stop applying.

---

## 5. Honest risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| EMM/Play approval slips | Phase 6 is gated on an external party and a policy review | Start the EMM conversation in week 1, not month 5; design the product to be useful without restriction |
| Regulatory classification changes the product | Screens, consent copy and retention all move | Legal review before Phase 3 locks the admin UI |
| Point-of-sale enrolment friction | Retail staff must do a factory-reset flow on a busy shop floor | Invest in the retailer app's enrolment UX and staff training; measure enrolment failure rate |
| Quota oversell / double-spend | Directly monetary, and silent when it happens | Already solved here — keep the tests |
| Cash collection leakage | Offline money, weak trail | Unique collection IDs, daily reconciliation, manager approval (schema supports it; workflow is Phase 2) |

---

## 6. Verdict

**Buildable, with one hard dependency and one open question.** The software is
well within reach; the schedule risk sits in the device-management partnership
and the Play policy review, and the product risk sits in the regulatory
classification. Resolve those two in parallel with Phase 1 rather than after it.

The code in this directory is a reference implementation of the core, not a
product. It is worth keeping as the executable specification the production
backend is tested against.
