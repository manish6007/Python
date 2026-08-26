"""Financial-independence projection.

Deliberately models the things a single-CAGR calculator gets wrong:

* Each bucket compounds at its own rate -- applying an equity return to a
  portfolio that is a third debt overstates the outcome badly.
* New money is invested at the *target* allocation, so the mix drifts from
  where it is today towards where it is meant to be.
* SIPs step up with income; a fixed contribution for twenty years is fiction.
* The EMI stops when the loan closes and that cash becomes investible.
* Expenses inflate, so the FI target is a moving line, not a fixed number.

Everything is nominal internally; real (today's-money) figures are derived by
discounting at the same inflation rate, because a crore in 2046 is not a
crore now and quoting only the nominal figure flatters the plan.
"""
import math

# Long-run expectations per bucket, in % per year. Deliberately unexciting.
DEFAULT_RETURNS = {"equity": 12.0, "debt": 7.0, "gold": 8.0,
                   "real_estate": 8.0, "cash": 3.5, "other": 7.0}

DEFAULT_INFLATION = 6.0
DEFAULT_STEP_UP = 5.0

# 25x comes from the US Trinity study. Indian inflation is higher, so Indian
# writing on FI generally uses 30-33x. 30x is the default; the multiple is
# the user's to choose and the UI shows what each implies.
DEFAULT_SWR_MULTIPLE = 30.0

EQUITY_SCENARIOS = (9.0, 12.0, 15.0)


def _normalise(weights):
    total = sum(v for v in weights.values() if v > 0)
    if total <= 0:
        return {"equity": 1.0}
    return {k: v / total for k, v in weights.items() if v > 0}


def loan_payoff_year(loans, amortization):
    """Years until the last EMI ends, and the annual EMI that then frees up."""
    latest, emi_annual = 0, 0.0
    for loan in loans or []:
        emi = loan.get("emi") or 0
        principal = loan.get("principal_outstanding") or 0
        if emi <= 0 or principal <= 0:
            continue
        emi_annual += emi * 12
        _, months = amortization(principal, loan.get("annual_rate") or 0, emi)
        if months is None:            # EMI does not cover interest
            return None, emi_annual
        latest = max(latest, math.ceil(months / 12.0))
    return latest, emi_annual


def project(corpus_by_bucket, annual_investment, annual_expense, *,
            target_allocation=None, returns=None, inflation_pct=DEFAULT_INFLATION,
            step_up_pct=DEFAULT_STEP_UP, swr_multiple=DEFAULT_SWR_MULTIPLE,
            years=40, payoff_year=None, freed_emi_annual=0.0):
    """Year-by-year corpus against a rising FI target.

    Contributions are added at the end of each year (conservative); growth is
    applied before them.
    """
    rates = dict(DEFAULT_RETURNS)
    rates.update(returns or {})
    buckets = {k: float(v) for k, v in (corpus_by_bucket or {}).items()}
    alloc = _normalise(dict(target_allocation)
                       if target_allocation else dict(buckets) or {"equity": 1})

    contribution = float(annual_investment)
    rows, crossover = [], None
    for t in range(0, int(years) + 1):
        if t > 0:
            for b in list(buckets):
                buckets[b] *= 1 + rates.get(b, DEFAULT_RETURNS["other"]) / 100.0
            added = contribution
            if payoff_year is not None and t > payoff_year:
                added += freed_emi_annual
            for b, w in alloc.items():
                buckets[b] = buckets.get(b, 0.0) + added * w
            contribution *= 1 + step_up_pct / 100.0

        corpus = sum(buckets.values())
        expense_t = annual_expense * (1 + inflation_pct / 100.0) ** t
        target_t = expense_t * swr_multiple
        deflator = (1 + inflation_pct / 100.0) ** t
        rows.append({
            "year": t,
            "corpus": round(corpus, 2),
            "fi_target": round(target_t, 2),
            "annual_expense": round(expense_t, 2),
            "corpus_real": round(corpus / deflator, 2),
            "fi_target_real": round(target_t / deflator, 2),
            "reached": corpus >= target_t,
        })
        # Year 0 counts: someone already past their number is FI today, not
        # in a year's time.
        if crossover is None and corpus >= target_t:
            crossover = t
    return {"rows": rows, "years_to_fi": crossover,
            "fi_number_today": round(annual_expense * swr_multiple, 2),
            "corpus_at_fi": round(rows[crossover]["corpus"], 2) if crossover else None,
            "corpus_at_fi_real": (round(rows[crossover]["corpus_real"], 2)
                                  if crossover else None)}


def scenarios(corpus_by_bucket, annual_investment, annual_expense, *,
              equity_rates=EQUITY_SCENARIOS, returns=None, **kw):
    """The same projection under several equity assumptions.

    Only the equity rate moves: debt, gold and cash do not become twice as
    good because you feel optimistic about shares.
    """
    out = []
    for eq in equity_rates:
        r = dict(DEFAULT_RETURNS)
        r.update(returns or {})
        r["equity"] = float(eq)
        res = project(corpus_by_bucket, annual_investment, annual_expense,
                      returns=r, **kw)
        out.append({"equity_return_pct": float(eq),
                    "years_to_fi": res["years_to_fi"],
                    "corpus_at_fi": res["corpus_at_fi"],
                    "corpus_at_fi_real": res["corpus_at_fi_real"],
                    "rows": res["rows"]})
    return out


def coast_fi(corpus_by_bucket, annual_expense, **kw):
    """If you never invest another rupee, does what you already have get there?"""
    kw.pop("payoff_year", None)
    kw.pop("freed_emi_annual", None)
    return project(corpus_by_bucket, 0.0, annual_expense, **kw)
