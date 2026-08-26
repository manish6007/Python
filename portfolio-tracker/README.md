# Portfolio Tracker

A household financial platform for Indian families: track everything you own
and owe in one place, see whether you are on course for financial
independence, and leave your family a record they can actually use.

It runs entirely on your own machine. All data sits in a single SQLite file
that never leaves it.

**Stack**: FastAPI + SQLite backend, React (Vite) + Recharts frontend.
See [PLAN.md](PLAN.md) for the original product plan.

---

## Contents

- [What it does](#what-it-does)
- [Running it](#running-it)
- [User guide](#user-guide)
- [How the numbers are calculated](#how-the-numbers-are-calculated)
- [Privacy and security](#privacy-and-security)
- [Testing](#testing)
- [Not built yet](#not-built-yet)

---

## What it does

### Track everything
Twelve asset classes — mutual funds, direct stocks, physical gold, sovereign
gold bonds, gold ETFs, REITs/InvITs, fixed deposits, savings accounts, EPF,
PPF, NPS and a catch-all — each tagged to a household member so you can see
your holdings and your spouse's together or apart. Mutual-fund NAVs refresh
from AMFI and stock prices from Yahoo, with a built-in AMFI scheme-code
search.

**Import instead of typing.** Upload a broker export exactly as it downloads —
Zerodha, Groww, Upstox, Angel One, ICICI Direct and most others, CSV or XLSX.
The column headings brokers use are recognised automatically, the guessed
mapping is shown for you to correct, and you confirm the rows before anything
is saved. A CAMS/KFintech statement PDF brings in every mutual-fund folio across both
registrars in one go — both the Consolidated Account Summary table and the
detailed statement are understood, scheme codes are resolved from each ISIN so
NAVs refresh by themselves afterwards, and the parsed totals are checked
against the statement's own Total row so a partial read cannot pass silently.

### Understand your allocation
Holdings roll up into buckets (equity, debt, gold, real estate, cash) which
you compare against a target you choose. Multi-asset funds can be split
across buckets so the gold and debt inside them stop being counted as equity.
Hover any bar to see exactly which holdings are inside that bucket.

### Know your real cashflow
Income and expenses per member, plus committed outflows — EMIs, SIPs, PF, NPS,
premiums, subscriptions, maintenance — each entered **the way it is actually
billed**: monthly, quarterly, half-yearly or yearly. Non-monthly costs are
spread into a monthly equivalent so the surplus is honest, and a warning lists
the lumpy bills falling due in the next three months so you keep the cash
reachable.

### Plan for financial independence
Your FI number, years to reach it under 9% / 12% / 15% equity assumptions, and
— the question most calculators skip — **whether the money then lasts**. The
projection runs accumulation and drawdown on one timeline. Goals (a car, a
child's education) are modelled as withdrawals from the same corpus, so you
can see what each one costs in FI years.

### Check your cover
An insurance register with sum assured, premium, renewal date and nominee,
plus a cover-adequacy check against the conventional 12× income plus
outstanding debt for life cover and a family floor for health.

### Get an AI review
Export a privacy-safe snapshot — a PDF, JSON, or a ready-to-paste package with
a reviewer prompt. The export states its own data quality: how many months
each average rests on, whether income is gross or net, what is estimated, and
every inconsistency the app has spotted, so a reviewer asks instead of
assuming.

### Leave your family a record
Two documents: a **sealed PDF** (AES-256) listing every account, folio, policy
and loan in full, and an **open one-page locator sheet** saying where the
sealed file is kept and who holds the password, listing institutions with no
numbers against them. Neither contains a username, password or security
answer. Off by default.

---

## Running it

Prerequisites: Python 3.9+, Node 18+.

```bash
# 1. Backend dependencies
cd backend
pip install -r requirements.txt

# 2. Build the frontend once (repeat only after UI changes)
cd ../frontend
npm install
npm run build

# 3. Start — one process serves the app and the API
cd ../backend
uvicorn main:app --port 8000
```

Open <http://localhost:8000>.

All data lives in `backend/portfolio.db`. **Back up that one file.** Delete it
to start over.

For frontend development use two terminals instead — `uvicorn main:app
--reload --port 8000` and `npm run dev` — and open the Vite URL; it proxies
`/api` to the backend and hot-reloads the UI.

---

## User guide

The **ⓘ** button in the top bar opens this guide inside the app.

### Start here (about 20 minutes)

1. **Settings → Household members.** Add your spouse, and anyone else whose
   money you track.
2. **Settings → Target asset allocation.** Enter your age and apply one of the
   suggested allocations, or set your own. Until you do, the dashboard warns
   that it is comparing you against placeholder numbers.
3. **Settings → Planning inputs.** Emergency-fund target, savings float, and
   whether the salary you enter is **gross or net** — the most common reason a
   plan fails to reconcile.
4. **Portfolio.** Import your broker's CSV or your CAS PDF rather than typing
   — upload the file untouched and correct the mapping if anything was
   guessed wrong. Give mutual funds their AMFI scheme code and stocks their
   NSE ticker so prices refresh automatically.
5. **Cashflow.** Add a month of income and expenses, then your committed
   outflows once.
6. **Loans**, **Insurance** — add what applies.
7. **Dashboard → Take snapshot.** Do this monthly; it is what builds the trend.

Not sure yet? **Settings → Load demo data** fills a realistic household you
can explore, and **Clear demo data** removes exactly those records again.

### Dashboard

Net worth, assets, liabilities and monthly investible surplus; allocation by
asset class and by owner; your allocation against target; prioritised
suggestions; and the net-worth trend built from monthly snapshots.

Anything the app finds inconsistent appears here as a warning — an EMI with no
loan behind it, holdings without a nominee, stale prices, a hybrid fund with
no look-through split. These are **reported, never silently corrected**,
because the app cannot know which side is right.

### Portfolio

| Field | Why it matters |
|---|---|
| **Identifier** | AMFI scheme code (auto-NAV), NSE ticker (auto-price), or folio/account number |
| **Bought on** | Enables the short-term vs long-term split on unrealised gains |
| **Maturity date** (FDs) | An FD maturing within 12 months counts toward your emergency fund |
| **Nominee** | Flagged when missing — the commonest reason a family cannot claim |
| **Counts as** | Overrides the allocation bucket, e.g. a sweep FD filed under Cash |
| **⊞ split** | Splits one holding across buckets — for multi-asset funds |

**Refresh prices** pulls MF NAVs from AMFI and stock prices from Yahoo.
**Unrealised gains & losses** shows the long/short split and how many holdings
are underwater.

### Cashflow

Enter each committed cost **as it is billed** — a ₹12,000 yearly subscription
stays a yearly ₹12,000 — and the app spreads it. The table shows per-payment,
per-month and per-year columns; the per-year total is the one that surprises
people.

Mark PF, NPS and ESOP contributions as **investments**, not expenses, or your
savings rate will read far too low. Each card states what it is based on
("average of 3 months of entries"), and adding a **next-due date** to
non-monthly items puts them in the lumpy-bills warning.

### Loans

Outstanding, rate, EMI and tenure, plus a **prepay vs invest** comparison that
shows interest saved and months shaved against the expected return on
investing the same lump sum instead.

### Insurance

Policies with cover, premium, renewal date and nominee, and gaps against
conventional cover levels. Renewals due in the next six months are listed —
premiums are held here **for the reminder only**; the committed outflows on
Cashflow own the cashflow figure, so nothing is double-counted.

### FI (financial independence)

Your FI number in today's money, years to reach it, and whether the corpus
survives the drawdown. Add **goals** to see what each costs in FI years. The
chart shows corpus against a rising FI target with a band across the 9–15%
range; **today's money is the default view** because nominal figures flatter
the plan.

### Export

- **Privacy-safe mode** (default) masks owner names and account numbers.
- **Copy AI review package** puts a reviewer prompt plus the JSON on your
  clipboard — paste it into a Claude chat.
- **Family record** — see [Privacy and security](#privacy-and-security).

### Settings

Household members, target allocation with age-based and risk-profile presets,
planning inputs, demo data, and a confirm-guarded **Erase all data**.

---

## How the numbers are calculated

Assumptions worth knowing, all of them editable:

- **Valuation** — unit-priced assets use units × latest price; FDs compound
  quarterly from their start date; PPF/EPF/savings accrue from the last
  balance you entered.
- **Averages** — income and expenses are each divided by the number of
  calendar months that actually carry entries, not by a fixed window.
- **Expenses** exclude EMI (which is tracked separately) and include the
  monthly equivalent of recurring costs. That is also what post-FI spending
  looks like, which is why the FI page uses the same figure.
- **Allocation presets** — equity via the "100 minus age" rule clamped to
  20–80%, gold 10%, cash 5%, REITs 5%, debt the remainder. Conventions common
  among Indian fee-only planners, not advice.
- **FI target** — annual expenses × 30 by default. The 25× (4%) rule is
  US-derived; Indian inflation is higher. 25×/30×/33× are all selectable.
- **Projection** — each bucket compounds at its own rate (equity 12%, debt 7%,
  gold 8%, cash 3.5%); new money follows your target allocation; SIPs step up
  5%/year; the EMI becomes investible when the loan closes; at FI the corpus
  is re-allocated to a conservative mix and withdrawals begin, rising with
  inflation.
- **Long-term capital gains** — simplified: 12 months for listed equity and
  equity-oriented funds, 24 otherwise. Confirm specifics with a CA.
- **Life cover** — 12× annual income plus outstanding debt. Investment-linked
  policies are counted at their stated sum assured, which flatters them.

A projection is not a prediction. It assumes steady returns in a straight
line; real markets deliver the same average through crashes and booms, and
sequence-of-returns risk is the thing these charts cannot show.

**This is not investment advice.** Suggestions are deliberately generic —
asset-class level, never specific products — and labelled educational.

---

## Privacy and security

- **Your data never leaves your machine.** One SQLite file, no accounts, no
  cloud, no telemetry. Outbound requests go only to AMFI and Yahoo for prices.
- **No credentials, ever.** There is no field anywhere for a username,
  password, PIN or security answer, and there will not be. The app records
  *where* money is and *who inherits it*, never how to log in.
- **Privacy-safe export** masks owner names, folio and account numbers,
  insurers and policy numbers while keeping every number needed for analysis.
  Use it before sharing with any AI or person.

### The family record

Two documents, off by default, generated from Export:

1. **Sealed record** — every account, folio, policy and loan in full,
   **AES-256 encrypted**. Passwords need 10+ characters and are never stored
   anywhere; if you lose one, regenerate the file.
2. **Locator sheet** — one unencrypted page saying where the sealed file is
   kept and who holds the password, then the institutions with **no account
   numbers on it**, so it can safely sit with your will.

If AES-256 is unavailable the app **refuses to write the file** rather than
falling back to ReportLab's RC4 — a document labelled "protected" that is not
protected is worse than none.

Where you keep these matters more than the cipher. A bank locker or a password
manager's secure notes are good; email and chat apps are not.

Both documents state plainly that a record is not a will, and that in India a
nominee is often a trustee for the legal heirs rather than the owner.

---

## Testing

```bash
cd backend && python -m pytest -q
```

94 tests covering the analytics, FI projection and family-record documents —
valuation, XIRR, cashflow averaging, allocation drift and presets, liquidity,
reconciliation, amortisation, the FI accumulation and drawdown model, goal
impact, insurance gaps, and AES-256 encryption round-trips.

```bash
flake8 backend --max-line-length=127
```

---

## Not built yet

Considered and deliberately deferred:

- **Tax module** — old vs new regime comparison, 80C/80D optimiser.
- **Estate planning** — will drafting, document vault.
- **Account Aggregator sync** — requires being a regulated FIU; not worth it
  for personal use.

If you plan to share this with others or charge for it, read the compliance
notes in [PLAN.md](PLAN.md) first: personalised investment advice for a fee is
regulated by SEBI, and holding other people's financial data brings the DPDP
Act into scope.
