# Portfolio Tracker

One place to track a household's complete financial life — mutual funds,
stocks, gold/SGB, REITs, FDs, savings, EPF/PPF/NPS, other investments, loans,
income & expenses — with a monthly investible-surplus calculation, rule-based
suggestions, and a privacy-safe PDF/JSON export designed to be pasted into
Claude for an optimization review.

**Stack**: FastAPI + SQLite backend (all data stays in a local file),
React (Vite) + Recharts frontend. See [PLAN.md](PLAN.md) for the full product
plan and roadmap.

## Run it

Prereqs: Python 3.9+, Node 18+.

```bash
# 1. Backend deps
cd backend
pip install -r requirements.txt

# 2. Build the frontend once (rebuild only after UI changes)
cd ../frontend
npm install
npm run build

# 3. Start — one process serves the app + API
cd ../backend
uvicorn main:app --port 8000
```

Open http://localhost:8000. All data lives in `backend/portfolio.db` —
back that one file up; delete it to start over.

For frontend development use two terminals instead:
`uvicorn main:app --reload --port 8000` and `npm run dev` (Vite proxies
`/api` to the backend, hot-reloads the UI at http://localhost:5173).

## First steps in the app

1. **Settings** → add household members (e.g. Wife), set target allocation,
   emergency-fund target, savings float — or hit **Load demo data** to explore.
2. **Portfolio** → add holdings (or bulk-import the CSV template). Give
   mutual funds their AMFI scheme code (search box provided) and stocks their
   NSE ticker, then **Refresh prices** pulls NAVs/quotes automatically.
3. **Cashflow** → add salary/expenses monthly, plus committed SIPs/EMIs once.
4. **Loans** → add the home loan; try the prepay-vs-invest calculator.
5. **Dashboard** → net worth, allocation vs target, suggestions; take a
   **snapshot** each month to build the trend chart.
6. **Export** → download the PDF, or copy the privacy-safe AI package and
   paste it into Claude for a portfolio review.

## Testing

```bash
cd backend && python -m pytest test_analytics.py -q
```

## Notes

- Valuation rules: unit-priced assets use units × latest price; FDs compound
  quarterly from the start date; PPF/EPF/savings accrue simply from the last
  entered balance.
- Suggestions are deliberately generic (asset-class level, never specific
  products) and labeled educational — not investment advice.
- Privacy-safe export masks owner names, folio/account numbers, and bank
  names; use it whenever sharing data with any AI or person.
