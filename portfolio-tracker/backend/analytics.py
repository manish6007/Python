"""Pure-python analytics: valuation, allocation, XIRR, surplus, suggestions.

Everything here operates on plain dicts/lists so it can be unit-tested
without streamlit, sqlalchemy, or a database.
"""
from datetime import date

# Which high-level bucket each asset class belongs to (overridable per
# holding via meta["bucket"], and per MF via meta["category"]).
BUCKET_MAP = {
    "mutual_fund": "equity",
    "stock": "equity",
    "gold_physical": "gold",
    "sgb": "gold",
    "gold_etf": "gold",
    "reit": "real_estate",
    "fd": "debt",
    "savings": "cash",
    "epf": "debt",
    "ppf": "debt",
    "nps": "debt",
    "other": "other",
}

MF_CATEGORY_BUCKET = {"equity": "equity", "elss": "equity", "hybrid": "equity",
                      "debt": "debt", "liquid": "cash", "gold": "gold"}

UNIT_PRICED = {"mutual_fund", "stock", "gold_etf", "reit", "sgb", "nps",
               "gold_physical"}
BALANCE_BASED = {"savings", "epf", "ppf", "other"}


def fd_value(principal, annual_rate_pct, start_date, as_of,
             compounding_per_year=4):
    """Quarterly-compounded FD value (bank convention)."""
    if not principal or not start_date or as_of <= start_date:
        return float(principal or 0.0)
    years = (as_of - start_date).days / 365.25
    r = annual_rate_pct / 100.0
    n = compounding_per_year
    return principal * (1 + r / n) ** (n * years)


def balance_accrued(balance, annual_rate_pct, value_date, as_of):
    """Simple accrual on a last-known balance (PPF/EPF/savings)."""
    if not balance:
        return 0.0
    if not value_date or as_of <= value_date or not annual_rate_pct:
        return float(balance)
    years = (as_of - value_date).days / 365.25
    return balance * (1 + annual_rate_pct / 100.0 * years)


def holding_value(h, as_of=None):
    """Current value of a holding dict.

    Expected keys: asset_class, units, avg_cost, manual_value, value_date,
    last_price, rate, start_date.
    """
    as_of = as_of or date.today()
    cls = h.get("asset_class")
    if cls == "fd":
        return fd_value(h.get("avg_cost") or h.get("manual_value") or 0.0,
                        h.get("rate") or 0.0, h.get("start_date"), as_of)
    if cls in BALANCE_BASED:
        return balance_accrued(h.get("manual_value") or 0.0,
                               h.get("rate") or 0.0,
                               h.get("value_date"), as_of)
    if cls in UNIT_PRICED:
        units = h.get("units") or 0.0
        price = h.get("last_price") or 0.0
        if units and price:
            return units * price
        return float(h.get("manual_value") or 0.0)
    return float(h.get("manual_value") or 0.0)


def holding_cost(h):
    cls = h.get("asset_class")
    if cls == "fd":
        return float(h.get("avg_cost") or 0.0)
    if cls in UNIT_PRICED:
        return (h.get("units") or 0.0) * (h.get("avg_cost") or 0.0)
    return float(h.get("manual_value") or 0.0)


def holding_bucket(h):
    meta = h.get("meta") or {}
    if meta.get("bucket"):
        return meta["bucket"]
    if h.get("asset_class") == "mutual_fund":
        cat = (meta.get("category") or "equity").lower()
        return MF_CATEGORY_BUCKET.get(cat, "equity")
    return BUCKET_MAP.get(h.get("asset_class"), "other")


LIQUID_FD_MONTHS = 12


def _months_between(start, end):
    return (end.year - start.year) * 12 + (end.month - start.month)


def _parse_date(value):
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def is_liquid(h, as_of=None, fd_liquid_months=LIQUID_FD_MONTHS):
    """Is this money reachable in an emergency?

    Savings accounts and anything sitting in the cash bucket (liquid funds, or
    a holding the user explicitly re-filed as cash) always count. A fixed
    deposit counts only when it has already matured or matures within
    `fd_liquid_months`: a 5-year tax-saver FD is not emergency money, a
    6-month sweep FD is. An FD with no maturity date recorded is treated as
    locked -- better to under-count the buffer than to claim one that is not
    reachable.
    """
    as_of = as_of or date.today()
    if h.get("asset_class") == "savings" or holding_bucket(h) == "cash":
        return True
    if h.get("asset_class") == "fd":
        maturity = _parse_date((h.get("meta") or {}).get("maturity_date"))
        if maturity:
            return _months_between(as_of, maturity) <= fd_liquid_months
    return False


def liquid_total(holdings, as_of=None, fd_liquid_months=LIQUID_FD_MONTHS):
    as_of = as_of or date.today()
    return sum(holding_value(h, as_of) for h in holdings
               if is_liquid(h, as_of, fd_liquid_months))


def aggregate(holdings, as_of=None):
    """Totals by asset class, by owner, by bucket, and overall."""
    as_of = as_of or date.today()
    by_class, by_owner, by_bucket = {}, {}, {}
    total = 0.0
    for h in holdings:
        v = holding_value(h, as_of)
        total += v
        by_class[h.get("asset_class")] = by_class.get(h.get("asset_class"), 0.0) + v
        owner = h.get("owner") or "Unassigned"
        by_owner[owner] = by_owner.get(owner, 0.0) + v
        b = holding_bucket(h)
        by_bucket[b] = by_bucket.get(b, 0.0) + v
    return {"total": total, "by_class": by_class,
            "by_owner": by_owner, "by_bucket": by_bucket}


def allocation_drift(by_bucket, targets):
    """Actual vs target percentage per bucket.

    Returns list of dicts sorted by most-underweight first.
    """
    total = sum(by_bucket.values()) or 1.0
    rows = []
    buckets = set(list(by_bucket.keys()) + list(targets.keys()))
    for b in buckets:
        actual_pct = 100.0 * by_bucket.get(b, 0.0) / total
        target_pct = float(targets.get(b, 0.0))
        rows.append({"bucket": b, "actual_pct": actual_pct,
                     "target_pct": target_pct,
                     "drift_pct": actual_pct - target_pct,
                     "gap_amount": (target_pct - actual_pct) / 100.0 * total})
    rows.sort(key=lambda r: r["drift_pct"])
    return rows


def xirr(cashflows, guess=0.1):
    """Money-weighted annual return.

    cashflows: list of (date, amount); negative = money in (investment),
    positive = money out (redemption / current value). Returns None when
    it cannot converge or the data is degenerate.
    """
    if len(cashflows) < 2:
        return None
    amounts = [a for _, a in cashflows]
    if all(a >= 0 for a in amounts) or all(a <= 0 for a in amounts):
        return None
    t0 = min(d for d, _ in cashflows)

    def npv(rate):
        return sum(a / (1 + rate) ** ((d - t0).days / 365.25)
                   for d, a in cashflows)

    lo, hi = -0.999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-8:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


# How many months one payment of each frequency covers. A quarterly bill is
# not a monthly bill -- spreading it is the only way a monthly surplus means
# anything.
FREQUENCY_MONTHS = {"monthly": 1, "quarterly": 3, "half_yearly": 6,
                    "yearly": 12}
FREQUENCY_LABELS = {"monthly": "Monthly", "quarterly": "Quarterly",
                    "half_yearly": "Half-yearly", "yearly": "Yearly"}


def to_monthly(amount, frequency):
    """Monthly-equivalent cost of a payment made every `frequency`."""
    return float(amount or 0.0) / FREQUENCY_MONTHS.get(frequency, 1)


def to_annual(amount, frequency):
    """What this outflow actually costs over a year."""
    return to_monthly(amount, frequency) * 12.0


def monthly_cashflow(income_total, expense_total, months, recurring,
                     income_months=None, expense_months=None):
    """Average monthly picture and the investible surplus.

    income_total/expense_total are sums of ad-hoc entries. Each is divided
    by the number of calendar months that actually carry entries
    (income_months/expense_months), NOT by the length of the lookback
    window -- otherwise one month of expenses logged against a 3-month
    window reads as a third of the real spend. `months` is the fallback
    when a caller does not count them. recurring is a list of dicts with
    amount_monthly, kind, counts_as_investment.
    """
    months = max(months, 1)
    # `is None` matters: zero entries is a real answer ("no data yet"), not a
    # missing argument, and must not silently fall back to the window length.
    income_div = months if income_months is None else income_months
    expense_div = months if expense_months is None else expense_months
    income_m = income_total / max(income_div, 1)
    expense_m = expense_total / max(expense_div, 1)
    emi_m = sum(r["amount_monthly"] for r in recurring if r.get("kind") == "emi")
    committed_invest_m = sum(r["amount_monthly"] for r in recurring
                             if r.get("counts_as_investment"))
    other_committed_m = sum(r["amount_monthly"] for r in recurring
                            if r.get("kind") != "emi"
                            and not r.get("counts_as_investment"))
    surplus = income_m - expense_m - emi_m - other_committed_m - committed_invest_m
    return {"income_m": income_m, "expense_m": expense_m, "emi_m": emi_m,
            "income_months": income_div,
            "expense_months": expense_div,
            "committed_invest_m": committed_invest_m,
            "other_committed_m": other_committed_m,
            "surplus_m": surplus,
            "savings_rate_pct": 100.0 * (committed_invest_m + max(surplus, 0.0))
            / income_m if income_m else 0.0}


def _inr(x):
    """Indian-grouped amount string: 12,34,567."""
    x = int(round(x))
    neg = x < 0
    s = str(abs(x))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-" if neg else "") + "\u20b9" + s


def suggestions(context):
    """Rule-based, generic (deliberately not product-specific) suggestions.

    context keys: surplus_m, emergency_fund_target, liquid_assets,
    drift (from allocation_drift), loans (list of dicts with kind,
    annual_rate, principal_outstanding), idle_savings, savings_threshold,
    tax_80c_used, tax_80ccd1b_used.
    Returns ordered list of {priority, title, detail} dicts.
    """
    out = []
    surplus = context.get("surplus_m", 0.0)

    if surplus <= 0:
        out.append({
            "priority": 1, "title": "Cashflow is negative or zero",
            "detail": "Expenses plus EMIs consume your full income. Review "
                      "the top expense categories before planning investments."})
        return out

    ef_target = context.get("emergency_fund_target", 0.0)
    liquid = context.get("liquid_assets", 0.0)
    if ef_target and liquid < ef_target:
        gap = ef_target - liquid
        out.append({
            "priority": 1, "title": "Fill the emergency fund first",
            "detail": "Liquid assets (savings + liquid funds) are "
                      "%s short of your %s target. Route the surplus "
                      "to a liquid fund / sweep FD until covered."
                      % (_inr(gap), _inr(ef_target))})

    for loan in context.get("loans", []):
        if loan.get("annual_rate", 0) >= 10.0 and loan.get("principal_outstanding", 0) > 0:
            out.append({
                "priority": 1,
                "title": "Prepay high-interest debt: %s" % loan.get("name", loan.get("kind", "loan")),
                "detail": "At %.1f%% this loan likely costs more than "
                          "post-tax investment returns. Prepaying is a "
                          "risk-free return at that rate." % loan["annual_rate"]})

    used_80c = context.get("tax_80c_used")
    if used_80c is not None and used_80c < 150000:
        out.append({
            "priority": 2, "title": "Section 80C headroom (old regime)",
            "detail": "%s of the \u20b91,50,000 80C limit is unused this FY "
                      "(ELSS / PPF / EPF top-up count)." % _inr(150000 - used_80c)})
    used_1b = context.get("tax_80ccd1b_used")
    if used_1b is not None and used_1b < 50000:
        out.append({
            "priority": 2, "title": "NPS 80CCD(1B) headroom (old regime)",
            "detail": "%s of the extra \u20b950,000 NPS deduction is unused "
                      "this FY." % _inr(50000 - used_1b)})

    drift = context.get("drift", [])
    under = [d for d in drift if d["drift_pct"] < -2.0 and d["target_pct"] > 0]
    if under:
        worst = under[0]
        out.append({
            "priority": 2,
            "title": "Rebalance: %s is underweight" % worst["bucket"],
            "detail": "Actual %.1f%% vs target %.1f%%. Direct roughly "
                      "%s of new money to %s before topping up "
                      "overweight classes." % (worst["actual_pct"],
                                               worst["target_pct"],
                                               _inr(max(worst["gap_amount"], 0.0)),
                                               worst["bucket"])})

    idle = context.get("idle_savings", 0.0)
    threshold = context.get("savings_threshold", 0.0)
    if threshold and idle > threshold:
        out.append({
            "priority": 3, "title": "Idle money in savings accounts",
            "detail": "%s sits in savings beyond your %s float. A "
                      "liquid fund or sweep FD earns 2-4%% more with "
                      "similar access." % (_inr(idle - threshold), _inr(threshold))})

    if not out:
        out.append({
            "priority": 3, "title": "On track",
            "detail": "Emergency fund covered, allocation within band, no "
                      "expensive debt. Continue SIPs and invest the surplus "
                      "of %s/month per your target allocation." % _inr(surplus)})
    out.sort(key=lambda s: s["priority"])
    return out


def amortization_schedule(principal, annual_rate_pct, emi, max_months=600):
    """Month-by-month schedule; returns list of dicts and payoff months."""
    r = annual_rate_pct / 100.0 / 12.0
    bal = principal
    rows = []
    month = 0
    while bal > 0 and month < max_months:
        month += 1
        interest = bal * r
        principal_part = emi - interest
        if principal_part <= 0:
            return rows, None  # EMI doesn't even cover interest
        principal_part = min(principal_part, bal)
        bal -= principal_part
        rows.append({"month": month, "interest": interest,
                     "principal": principal_part, "balance": bal})
    return rows, month


def prepay_vs_invest(principal, annual_rate_pct, emi, lumpsum,
                     invest_return_pct):
    """Compare prepaying `lumpsum` against investing it.

    Returns dict with interest saved + months shaved by prepaying, and the
    future value of investing the lumpsum over the loan's remaining life.
    """
    base_rows, base_months = amortization_schedule(principal, annual_rate_pct, emi)
    if base_months is None:
        return None
    base_interest = sum(r["interest"] for r in base_rows)
    pre_rows, pre_months = amortization_schedule(
        max(principal - lumpsum, 0.0), annual_rate_pct, emi)
    pre_interest = sum(r["interest"] for r in pre_rows)
    years = base_months / 12.0
    fv_invest = lumpsum * (1 + invest_return_pct / 100.0) ** years
    return {"interest_saved": base_interest - pre_interest,
            "months_saved": base_months - (pre_months or 0),
            "invest_future_value": fv_invest,
            "invest_gain": fv_invest - lumpsum,
            "horizon_months": base_months}


# ---------------------------------------------------------------------------
# Target-allocation presets
#
# These follow conventions commonly used by Indian fee-only planners and SEBI
# RIA material. They are starting points for a conversation, not advice, and
# every number is meant to be edited by the user:
#   * Equity via the classic "100 minus age" rule, floored at 20% and capped
#     at 80% so neither extreme of age lands somewhere silly.
#   * Gold 10% -- the midpoint of the 5-15% diversifier range most planners
#     and the World Gold Council quote for Indian portfolios.
#   * Cash 5% -- a working float; the real emergency fund is sized in months
#     of expenses, tracked separately in Settings.
#   * Real estate 5% -- REITs/InvITs only. A home you live in is not an
#     investment allocation and is deliberately excluded.
#   * Debt takes the remainder: EPF, PPF, FDs, debt funds, NPS-G.
# ---------------------------------------------------------------------------

GOLD_PCT = 10.0
CASH_PCT = 5.0
REAL_ESTATE_PCT = 5.0
EQUITY_FLOOR, EQUITY_CAP = 20.0, 80.0

RISK_PROFILES = {
    "conservative": (30.0, "Capital protection first; short horizons or "
                           "near/in retirement."),
    "balanced": (50.0, "Middle path \u2014 growth with a large stability cushion."),
    "growth": (70.0, "Long horizon and the stomach for deep drawdowns."),
}


def _targets_from_equity(equity_pct):
    """Fill the remaining buckets around a chosen equity weight."""
    equity = min(max(float(equity_pct), 0.0), 100.0)
    fixed = GOLD_PCT + CASH_PCT + REAL_ESTATE_PCT
    debt = max(100.0 - equity - fixed, 0.0)
    # If equity is so high the fixed sleeves cannot all fit, shrink them
    # proportionally rather than letting the total drift off 100.
    if equity + fixed > 100.0:
        room = max(100.0 - equity, 0.0)
        scale = room / fixed if fixed else 0.0
        out = {"equity": round(equity, 1), "debt": 0.0,
               "gold": round(GOLD_PCT * scale, 1),
               "real_estate": round(REAL_ESTATE_PCT * scale, 1),
               "cash": round(CASH_PCT * scale, 1), "other": 0.0}
    else:
        out = {"equity": round(equity, 1), "debt": round(debt, 1),
               "gold": GOLD_PCT, "real_estate": REAL_ESTATE_PCT,
               "cash": CASH_PCT, "other": 0.0}
    return _normalise_to_100(out)


def _normalise_to_100(targets):
    """Push any rounding residual into the largest bucket so the total is
    exactly 100 -- the UI refuses to save anything else."""
    residual = round(100.0 - sum(targets.values()), 1)
    if residual:
        biggest = max(targets, key=lambda k: targets[k])
        targets[biggest] = round(targets[biggest] + residual, 1)
    return targets


def equity_for_age(age):
    """The '100 minus age' rule, clamped to a sane band."""
    return min(max(100.0 - float(age), EQUITY_FLOOR), EQUITY_CAP)


def suggest_targets(age=None, profile=None):
    """Targets for one preset: age rule when `age` given, else a risk profile."""
    if age is not None:
        return _targets_from_equity(equity_for_age(age))
    equity, _ = RISK_PROFILES.get(profile or "balanced",
                                  RISK_PROFILES["balanced"])
    return _targets_from_equity(equity)


def target_presets(age=None):
    """All presets the UI offers, age-based one first when an age is known."""
    out = []
    if age is not None:
        eq = equity_for_age(age)
        out.append({
            "key": "age_rule",
            "name": "Age-based (100 \u2212 age)",
            "detail": "At %d that puts %.0f%% in equity \u2014 the rule Indian "
                      "planners most often start from." % (int(age), eq),
            "targets": suggest_targets(age=age),
            "recommended": True,
        })
    for key, (equity, detail) in RISK_PROFILES.items():
        out.append({
            "key": key,
            "name": key.capitalize(),
            "detail": detail,
            "targets": suggest_targets(profile=key),
            "recommended": False,
        })
    return out
