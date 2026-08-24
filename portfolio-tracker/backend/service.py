"""Service layer: ORM <-> dict conversion and the computation pipeline."""
from datetime import date

import analytics
from db import (ExpenseEntry, Holding, IncomeEntry, Loan, Owner,
                RecurringOutflow, get_setting, get_targets)


def holding_to_dict(h):
    return {
        "id": h.id,
        "owner": h.owner.name if h.owner else "Unassigned",
        "owner_id": h.owner_id,
        "asset_class": h.asset_class,
        "name": h.name,
        "identifier": h.identifier,
        "units": h.units,
        "avg_cost": h.avg_cost,
        "manual_value": h.manual_value,
        "value_date": h.value_date,
        "last_price": h.last_price,
        "price_date": h.price_date,
        "rate": h.rate,
        "start_date": h.start_date,
        "meta": h.meta_dict(),
        "notes": h.notes,
    }


def holding_out(h):
    """JSON-safe holding dict enriched with computed value/cost/bucket."""
    d = holding_to_dict(h)
    d["current_value"] = round(analytics.holding_value(d), 2)
    d["invested"] = round(analytics.holding_cost(d), 2)
    d["bucket"] = analytics.holding_bucket(d)
    for k in ("value_date", "price_date", "start_date"):
        d[k] = d[k].isoformat() if d[k] else None
    return d


def loan_to_dict(loan):
    return {
        "id": loan.id, "owner_id": loan.owner_id, "name": loan.name,
        "kind": loan.kind,
        "principal_outstanding": loan.principal_outstanding,
        "annual_rate": loan.annual_rate, "emi": loan.emi,
        "tenure_months_remaining": loan.tenure_months_remaining,
        "notes": loan.notes,
    }


def load_all(session):
    holdings = [holding_to_dict(h) for h in session.query(Holding).all()]
    loans = [loan_to_dict(loan) for loan in session.query(Loan).all()]
    recurring = [{"id": r.id, "name": r.name, "kind": r.kind,
                  "amount_monthly": r.amount_monthly,
                  "counts_as_investment": bool(r.counts_as_investment)}
                 for r in session.query(RecurringOutflow).all()]
    return holdings, loans, recurring


def _window_start(months):
    """First day of the calendar month `months - 1` back from this one."""
    today = date.today()
    y, m = today.year, today.month - (months - 1)
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def _month_span(rows):
    """How many distinct calendar months actually carry entries."""
    return len({(r.date.year, r.date.month) for r in rows})


def cashflow_summary(session, recurring, months=3):
    since = _window_start(months)
    inc_rows = session.query(IncomeEntry).filter(IncomeEntry.date >= since).all()
    exp_rows = session.query(ExpenseEntry).filter(ExpenseEntry.date >= since).all()
    return analytics.monthly_cashflow(
        sum(e.amount for e in inc_rows), sum(e.amount for e in exp_rows),
        months, recurring,
        income_months=_month_span(inc_rows),
        expense_months=_month_span(exp_rows))


def float_setting(session, key, default=0.0):
    try:
        return float(get_setting(session, key, "") or default)
    except ValueError:
        return default


def build_suggestion_context(session, holdings, loans, cashflow):
    agg = analytics.aggregate(holdings)
    targets = get_targets(session)
    drift = analytics.allocation_drift(agg["by_bucket"], targets)
    liquid = sum(analytics.holding_value(h) for h in holdings
                 if h["asset_class"] == "savings"
                 or analytics.holding_bucket(h) == "cash")
    idle_savings = sum(analytics.holding_value(h) for h in holdings
                       if h["asset_class"] == "savings")
    ctx = {
        "surplus_m": cashflow["surplus_m"],
        "emergency_fund_target": float_setting(session, "emergency_fund_target"),
        "liquid_assets": liquid,
        "drift": drift,
        "loans": loans,
        "idle_savings": idle_savings,
        "savings_threshold": float_setting(session, "savings_float"),
    }
    for key in ("tax_80c_used", "tax_80ccd1b_used"):
        raw = get_setting(session, key, "")
        if raw != "":
            try:
                ctx[key] = float(raw)
            except ValueError:
                pass
    return ctx, drift, targets, agg


def full_pipeline(session):
    holdings, loans, recurring = load_all(session)
    cashflow = cashflow_summary(session, recurring)
    ctx, drift, targets, agg = build_suggestion_context(
        session, holdings, loans, cashflow)
    sugg = analytics.suggestions(ctx)
    return {"holdings": holdings, "loans": loans, "recurring": recurring,
            "cashflow": cashflow, "drift": drift, "targets": targets,
            "suggestions": sugg, "agg": agg}


def ensure_default_owner(session):
    if not session.query(Owner).count():
        session.add(Owner(name="Me"))
        session.commit()
