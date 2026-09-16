# EMI Locker — core reference implementation

A runnable implementation of the risky parts of the Ashish Enterprises EMI
Locker blueprint: reseller licensing with activation quota, customer and device
onboarding, EMI scheduling, verified payments, the overdue lifecycle, and
audited device actions.

It exists to answer one question — *can this be built, and what are the parts
that bite?* — with code and tests instead of an opinion. See
[FEASIBILITY.md](FEASIBILITY.md) for the assessment.

**This is a reference core, not a product.** It uses SQLite and a static-token
HTTP demonstrator so it runs anywhere with no dependencies. A production build
would keep the service layer's shape and swap in PostgreSQL, real auth and a
proper web framework.

## Run it

Standard library only — Python 3.8+.

```bash
# the blueprint's own worked example, end to end
python -m emi_locker.demo

# the demo HTTP API
python -m emi_locker.api --port 8080 --db emi.db

# the test-suite (needs pytest)
python -m pytest tests/ -q
```

## What the demo shows

```
 1. Admin setup, network and license plans
 2. Distributor buys a 500-activation pack; key is issued once
 3. Distributor allocates 100 activations to its retailer
 4. A rival distributor tries to allocate into this retailer   -> denied
 5. Retailer onboards a customer with recorded consent
 6. New finance: Rs.30,000 device, Rs.8,000 down, 11 months
 7. The same IMEI cannot be financed twice                     -> denied
 8. Customer pays EMI 1 online: forged callback rejected,
    verified webhook accepted, gateway retry ignored
 9. Retailer collects EMI 2 in cash
10. Time passes: EMI 3 goes due, then grace, then overdue
11. Restriction needs eligibility, a reason and a second approver
12. Customer clears the arrears; the device is restored
13. Remaining instalments cleared -> finance closes itself
14. Admin dashboard and audit trail
```

## Layout

| Module | Responsibility |
|---|---|
| `db.py` | Schema, `BEGIN IMMEDIATE` transactions, append-only audit triggers |
| `core.py` | Ids, money, `Actor`, audit, idempotency, retailer scoping |
| `licensing.py` | Plans, keys, wallets, allocation, activation, renewal, transfer |
| `finance.py` | Customers, consent, IMEI rules, finance pricing, EMI schedule |
| `payments.py` | Payment initiation, webhook verification, receipts, cash collection |
| `lifecycle.py` | Due/grace/overdue sweep, reminders, closure certificate |
| `devices.py` | Device command queue, eligibility, dual control, provider adapter |
| `reports.py` | Scoped dashboards and reports |
| `api.py` | Demo HTTP surface matching the blueprint's endpoint list |

## Design decisions worth keeping

- **Money is integer paise.** No floats anywhere in the money path.
- **Invariants live in the database.** A partial unique index stops a second
  live finance on one IMEI; `CHECK (used + reserved <= total)` stops a wallet
  going negative; triggers make `audit_logs` append-only. Application code gets
  refactored — constraints do not quietly stop applying.
- **Quota deduction is one conditional `UPDATE` under the write lock.** That is
  the whole concurrency story, and `test_concurrent_activations_cannot_oversell_the_wallet`
  holds it to it: 20 simultaneous requests against a balance of 5 produce
  exactly 5 activations.
- **Nothing is paid without a verified webhook.** Signature, then replay check,
  then amount match — in that order.
- **`devices.py` records intent; it does not lock phones.** The default provider
  reports that nothing was sent, because an app cannot restrict a device on its
  own. See §3.1 of the feasibility note.

## Not included

Deliberately out of scope for a core demonstrator: OTP login and sessions, KYC
document storage, SMS/WhatsApp/push delivery, commission calculation, the three
mobile apps, the admin web UI, and any real device-management integration.
