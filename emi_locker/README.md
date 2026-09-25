# EMI Locker

A working local build of the Ashish Enterprises EMI Locker platform: a Python
backend, three Android apps (**Customer**, **Retailer**, **Distributor**) and a
**Super Admin web panel**, on top of a tested domain core.

**New here? Go straight to [docs/WINDOWS_SETUP.md](docs/WINDOWS_SETUP.md).**
It takes you from a clean Windows PC to both apps running, and ends with a
scripted walkthrough of the whole flow.

[FEASIBILITY.md](FEASIBILITY.md) is the assessment of what can and cannot be
built, including the parts that are not a coding job at all.

## What is here

```
emi_locker/
  emi_locker/      domain core - licensing, finance, EMI, payments, devices
  backend/         FastAPI app: OTP login, REST API, mock gateway, seed data
  mobile/          Flutter: customer, retailer, distributor and admin panel
  docs/            setup guide
  start-backend.bat / start-backend.sh
```

One Flutter project serves all four audiences. The role returned at sign-in
decides which shell opens, and the backend enforces the boundaries
independently - the routing is convenience, not security.

## Quick start

```bash
./start-backend.sh            # Windows: double-click start-backend.bat
```

Then, in a second terminal:

```bash
cd mobile/emi_locker_app
flutter pub get
flutter run              # Android: customer, retailer, distributor
flutter run -d chrome    # the Super Admin panel
```

Sign in with one of the seeded numbers - the OTP is printed by the backend and
filled in for you, because local mode returns it instead of sending an SMS:

| Number | Opens |
|---|---|
| `9876543210` | Customer app (has a live finance) |
| `9000000003` | Retailer app |
| `9000000002` | Distributor app |
| `9000000001` | Super Admin panel (use Chrome) |

## Tests

```bash
python -m pytest tests backend/tests -q      # 144: domain core + API
cd mobile/emi_locker_app && flutter test     # 54: apps and panel
```

There is also a dependency-free walkthrough of the domain core on its own,
which prints the blueprint's worked example end to end:

```bash
python -m emi_locker.demo
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

## Domain core modules

The backend is a thin HTTP layer over these. Business rules live here, so they
are covered by the core's own tests and cannot drift between transports.

| Module | Responsibility |
|---|---|
| `db.py` | Schema, `BEGIN IMMEDIATE` transactions, append-only audit triggers |
| `core.py` | Ids, money, `Actor`, audit, idempotency, retailer scoping |
| `licensing.py` | Plans, keys, wallets, allocation, activation, renewal, transfer |
| `finance.py` | Customers, consent, IMEI rules, finance pricing, EMI schedule |
| `payments.py` | Payment initiation, webhook verification, receipts, cash collection |
| `lifecycle.py` | Due/grace/overdue sweep, reminders, closure certificate |
| `devices.py` | Device command queue, eligibility, dual control, provider adapter |
| `reports.py` | Scoped dashboards, reports and commission |
| `settings_store.py` | Admin-configurable business settings |

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

## Not built yet

Deliberately out of scope for a local build: KYC document storage,
SMS/WhatsApp/push delivery, and any real device-management integration.
Payments run against a local mock gateway rather than a real one. Commission
rates default to zero and are set in the admin panel - the blueprint fixes no
rate, so neither does this.

See [FEASIBILITY.md](FEASIBILITY.md) §4 for the order these come in, and §3 for
the parts that depend on a contract or a lawyer rather than on code.
