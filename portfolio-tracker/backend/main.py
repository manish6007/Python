"""Portfolio Tracker API + static frontend server.

Run:  uvicorn main:app --reload --port 8000
The built React app (frontend/dist) is served at /, the API under /api.
"""
import csv
import io
import json
import os
from datetime import date, datetime

from fastapi import Body, FastAPI, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import analytics
import export as export_mod
import fi as fi_mod
import pricing
import service
from db import (ASSET_CLASS_LABELS, ASSET_CLASSES, ExpenseEntry, Holding,
                IncomeEntry, Loan, Owner, RecurringOutflow, Snapshot,
                Transaction, get_session, get_setting, get_targets,
                set_setting)

app = FastAPI(title="Portfolio Tracker")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

_amfi_cache = {"data": {}, "at": None}


def db():
    s = get_session()
    service.ensure_default_owner(s)
    return s


def parse_date(v):
    if not v:
        return None
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()


# ---------------- meta ----------------
@app.get("/api/meta")
def meta():
    return {"asset_classes": ASSET_CLASSES,
            "asset_class_labels": ASSET_CLASS_LABELS,
            "buckets": ["equity", "debt", "gold", "real_estate", "cash", "other"]}


# ---------------- summary ----------------
@app.get("/api/summary")
def summary():
    s = db()
    data = service.full_pipeline(s)
    agg = data["agg"]
    total_liab = sum(loan["principal_outstanding"] for loan in data["loans"])
    snaps = s.query(Snapshot).order_by(Snapshot.date).all()
    holdings_out = [service.holding_out(h) for h in s.query(Holding).all()]
    resp = {
        "total_assets": round(agg["total"], 2),
        "total_liabilities": round(total_liab, 2),
        "net_worth": round(agg["total"] - total_liab, 2),
        "by_class": {k: round(v, 2) for k, v in agg["by_class"].items()},
        "by_owner": {k: round(v, 2) for k, v in agg["by_owner"].items()},
        "by_bucket": {k: round(v, 2) for k, v in agg["by_bucket"].items()},
        "drift": data["drift"],
        "targets": data["targets"],
        "targets_customized": bool(get_setting(s, "targets", "")),
        "cashflow": data["cashflow"],
        "suggestions": data["suggestions"],
        "holdings": holdings_out,
        "loans": data["loans"],
        "recurring": data["recurring"],
        "lumpy_upcoming": analytics.upcoming_lumpy(data["recurring"]),
        "warnings": data["warnings"],
        "unrealised": analytics.unrealised_positions(data["holdings"]),
        "snapshots": [{"date": sn.date.isoformat(), "net_worth": sn.net_worth,
                       "total_assets": sn.total_assets,
                       "total_liabilities": sn.total_liabilities}
                      for sn in snaps],
    }
    s.close()
    return resp


# ---------------- owners ----------------
@app.get("/api/owners")
def list_owners():
    s = db()
    out = [{"id": o.id, "name": o.name} for o in s.query(Owner).all()]
    s.close()
    return out


@app.post("/api/owners")
def add_owner(payload: dict = Body(...)):
    s = db()
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    if s.query(Owner).filter(Owner.name == name).first():
        raise HTTPException(409, "owner exists")
    o = Owner(name=name)
    s.add(o)
    s.commit()
    out = {"id": o.id, "name": o.name}
    s.close()
    return out


@app.delete("/api/owners/{oid}")
def delete_owner(oid: int):
    s = db()
    o = s.get(Owner, oid)
    if not o:
        raise HTTPException(404, "not found")
    if s.query(Holding).filter(Holding.owner_id == oid).count():
        raise HTTPException(409, "owner has holdings; reassign them first")
    s.delete(o)
    s.commit()
    s.close()
    return {"ok": True}


# ---------------- holdings ----------------
HOLDING_FIELDS = ("asset_class", "name", "identifier", "units", "avg_cost",
                  "manual_value", "last_price", "rate", "notes")


def apply_holding_payload(h, payload):
    for f in HOLDING_FIELDS:
        if f in payload and payload[f] is not None:
            setattr(h, f, payload[f])
    if "owner_id" in payload and payload["owner_id"]:
        h.owner_id = int(payload["owner_id"])
    for f in ("start_date", "value_date", "price_date"):
        if f in payload:
            setattr(h, f, parse_date(payload[f]))
    if "meta" in payload and isinstance(payload["meta"], dict):
        # Merge, don't clobber: setting a bucket must not wipe an MF's
        # category. An empty value clears that key.
        merged = h.meta_dict()
        for k, v in payload["meta"].items():
            if v in (None, ""):
                merged.pop(k, None)
            else:
                merged[k] = v
        h.meta = json.dumps(merged)


@app.get("/api/holdings")
def list_holdings():
    s = db()
    out = [service.holding_out(h) for h in s.query(Holding).all()]
    s.close()
    return out


@app.post("/api/holdings")
def add_holding(payload: dict = Body(...)):
    s = db()
    if payload.get("asset_class") not in ASSET_CLASSES:
        raise HTTPException(400, "bad asset_class")
    if not (payload.get("name") or "").strip():
        raise HTTPException(400, "name required")
    h = Holding(owner_id=payload.get("owner_id") or s.query(Owner).first().id,
                asset_class=payload["asset_class"], name=payload["name"])
    apply_holding_payload(h, payload)
    if not h.value_date:
        h.value_date = date.today()
    if h.asset_class in analytics.UNIT_PRICED and not h.last_price:
        h.last_price = h.avg_cost or 0.0
        h.price_date = date.today()
    s.add(h)
    s.commit()
    out = service.holding_out(h)
    s.close()
    return out


@app.put("/api/holdings/{hid}")
def update_holding(hid: int, payload: dict = Body(...)):
    s = db()
    h = s.get(Holding, hid)
    if not h:
        raise HTTPException(404, "not found")
    apply_holding_payload(h, payload)
    if "manual_value" in payload:
        h.value_date = date.today()
    if "last_price" in payload:
        h.price_date = date.today()
    s.commit()
    out = service.holding_out(h)
    s.close()
    return out


@app.delete("/api/holdings/{hid}")
def delete_holding(hid: int):
    s = db()
    h = s.get(Holding, hid)
    if not h:
        raise HTTPException(404, "not found")
    s.delete(h)
    s.commit()
    s.close()
    return {"ok": True}


@app.post("/api/holdings/import")
async def import_holdings(file: UploadFile):
    s = db()
    text = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    owners = {o.name: o.id for o in s.query(Owner).all()}
    added, errors = 0, []
    for i, r in enumerate(reader):
        try:
            oname = (r.get("owner") or "Me").strip()
            if oname not in owners:
                o = Owner(name=oname)
                s.add(o)
                s.commit()
                owners[oname] = o.id
            cls = (r.get("asset_class") or "").strip()
            if cls not in ASSET_CLASSES:
                raise ValueError("bad asset_class %r" % cls)
            h = Holding(
                owner_id=owners[oname], asset_class=cls,
                name=(r.get("name") or "").strip(),
                identifier=(r.get("identifier") or "").strip(),
                units=float(r.get("units") or 0),
                avg_cost=float(r.get("avg_cost") or 0),
                manual_value=float(r.get("manual_value") or 0),
                rate=float(r.get("rate") or 0),
                start_date=parse_date((r.get("start_date") or "").strip()),
                value_date=date.today(),
                meta=json.dumps({
                    k: v for k, v in (
                        ("category", (r.get("category") or "").strip()),
                        ("bucket", (r.get("bucket") or "").strip()),
                        ("maturity_date", (r.get("maturity_date") or "").strip()),
                        ("purchase_date", (r.get("purchase_date") or "").strip()),
                    ) if v}))
            if cls in analytics.UNIT_PRICED:
                h.last_price = float(r.get("last_price") or 0) or h.avg_cost
                h.price_date = date.today()
            if not h.name:
                raise ValueError("name required")
            s.add(h)
            added += 1
        except (ValueError, TypeError, KeyError) as ex:
            errors.append("row %d: %s" % (i + 2, ex))
    s.commit()
    s.close()
    return {"added": added, "errors": errors}


# ---------------- transactions (optional, powers XIRR) ----------------
@app.get("/api/holdings/{hid}/transactions")
def list_txns(hid: int):
    s = db()
    out = [{"id": t.id, "date": t.date.isoformat(), "type": t.type,
            "amount": t.amount, "units": t.units}
           for t in s.query(Transaction).filter(Transaction.holding_id == hid)
           .order_by(Transaction.date)]
    s.close()
    return out


@app.post("/api/holdings/{hid}/transactions")
def add_txn(hid: int, payload: dict = Body(...)):
    s = db()
    if not s.get(Holding, hid):
        raise HTTPException(404, "holding not found")
    t = Transaction(holding_id=hid, date=parse_date(payload["date"]),
                    type=payload.get("type", "buy"),
                    amount=float(payload["amount"]),
                    units=float(payload.get("units") or 0))
    s.add(t)
    s.commit()
    s.close()
    return {"ok": True}


@app.get("/api/xirr")
def portfolio_xirr():
    """Overall + per-holding XIRR from recorded transactions."""
    s = db()
    today = date.today()
    all_flows = []
    per = []
    for h in s.query(Holding).all():
        txns = list(h.transactions)
        if not txns:
            continue
        flows = []
        for t in txns:
            sign = -1 if t.type in ("buy", "contribution") else 1
            flows.append((t.date, sign * t.amount))
        cur = analytics.holding_value(service.holding_to_dict(h), today)
        flows.append((today, cur))
        all_flows.extend(flows[:-1])
        r = analytics.xirr(flows)
        per.append({"holding_id": h.id, "name": h.name,
                    "xirr_pct": round(r * 100, 2) if r is not None else None})
        all_flows.append((today, cur))
    overall = analytics.xirr(all_flows) if all_flows else None
    s.close()
    return {"overall_pct": round(overall * 100, 2) if overall is not None else None,
            "holdings": per}


# ---------------- prices ----------------
@app.post("/api/prices/refresh")
def refresh_prices():
    s = db()
    navs = pricing.fetch_amfi_navs()
    mf_updated = stock_updated = 0
    failed = []
    if navs:
        _amfi_cache["data"], _amfi_cache["at"] = navs, datetime.now()
        for h in s.query(Holding).filter(Holding.asset_class == "mutual_fund"):
            info = navs.get(str(h.identifier).strip())
            if info:
                h.last_price, h.price_date = info["nav"], info["date"]
                mf_updated += 1
    for h in s.query(Holding).filter(Holding.asset_class == "stock"):
        px, pd_ = pricing.fetch_stock_price(h.identifier or h.name)
        if px:
            h.last_price, h.price_date = px, pd_
            stock_updated += 1
        else:
            failed.append(h.name)
    s.commit()
    s.close()
    return {"amfi_reachable": bool(navs), "mf_updated": mf_updated,
            "stocks_updated": stock_updated, "stock_failed": failed}


@app.get("/api/amfi/search")
def amfi_search(q: str):
    if not _amfi_cache["data"]:
        _amfi_cache["data"] = pricing.fetch_amfi_navs()
        _amfi_cache["at"] = datetime.now()
    hits = pricing.search_amfi(_amfi_cache["data"], q)
    return [{"code": c, "name": i["name"], "nav": i["nav"],
             "date": i["date"].isoformat()} for c, i in hits]


# ---------------- income / expenses / recurring ----------------
def _entry_rows(s, model):
    rows = (s.query(model).order_by(model.date.desc()).limit(500).all())
    owners = {o.id: o.name for o in s.query(Owner).all()}
    out = []
    for e in rows:
        d = {"id": e.id, "owner": owners.get(e.owner_id, "?"),
             "owner_id": e.owner_id, "date": e.date.isoformat(),
             "category": e.category, "amount": e.amount, "notes": e.notes}
        if hasattr(e, "fixed"):
            d["fixed"] = bool(e.fixed)
        out.append(d)
    return out


@app.get("/api/income")
def list_income():
    s = db()
    out = _entry_rows(s, IncomeEntry)
    s.close()
    return out


@app.post("/api/income")
def add_income(payload: dict = Body(...)):
    s = db()
    s.add(IncomeEntry(owner_id=payload.get("owner_id") or s.query(Owner).first().id,
                      date=parse_date(payload.get("date")) or date.today(),
                      category=payload.get("category") or "Salary",
                      amount=float(payload["amount"]),
                      notes=payload.get("notes") or ""))
    s.commit()
    s.close()
    return {"ok": True}


@app.delete("/api/income/{eid}")
def delete_income(eid: int):
    s = db()
    e = s.get(IncomeEntry, eid)
    if e:
        s.delete(e)
        s.commit()
    s.close()
    return {"ok": True}


@app.get("/api/expenses")
def list_expenses():
    s = db()
    out = _entry_rows(s, ExpenseEntry)
    s.close()
    return out


@app.post("/api/expenses")
def add_expense(payload: dict = Body(...)):
    s = db()
    s.add(ExpenseEntry(owner_id=payload.get("owner_id") or s.query(Owner).first().id,
                       date=parse_date(payload.get("date")) or date.today(),
                       category=payload.get("category") or "Household",
                       amount=float(payload["amount"]),
                       fixed=1 if payload.get("fixed") else 0,
                       notes=payload.get("notes") or ""))
    s.commit()
    s.close()
    return {"ok": True}


@app.delete("/api/expenses/{eid}")
def delete_expense(eid: int):
    s = db()
    e = s.get(ExpenseEntry, eid)
    if e:
        s.delete(e)
        s.commit()
    s.close()
    return {"ok": True}


@app.get("/api/recurring")
def list_recurring():
    s = db()
    out = [service.recurring_to_dict(r)
           for r in s.query(RecurringOutflow).all()]
    s.close()
    return out


@app.post("/api/recurring")
def add_recurring(payload: dict = Body(...)):
    s = db()
    kind = payload.get("kind") or "sip"
    freq = payload.get("frequency") or "monthly"
    if freq not in analytics.FREQUENCY_MONTHS:
        raise HTTPException(400, "bad frequency %r" % freq)
    # accept either the per-payment amount or a legacy monthly figure
    amount = payload.get("amount")
    if amount is None:
        amount = payload.get("amount_monthly", 0)
    amount = float(amount)
    r = RecurringOutflow(
        name=payload["name"], kind=kind, amount=amount, frequency=freq,
        next_due=parse_date(payload.get("next_due")),
        amount_monthly=analytics.to_monthly(amount, freq),
        counts_as_investment=1 if payload.get("counts_as_investment",
                                              kind == "sip") else 0)
    s.add(r)
    s.commit()
    out = service.recurring_to_dict(r)
    s.close()
    return out


@app.put("/api/recurring/{rid}")
def update_recurring(rid: int, payload: dict = Body(...)):
    s = db()
    r = s.get(RecurringOutflow, rid)
    if not r:
        raise HTTPException(404, "not found")
    for f in ("name", "kind"):
        if f in payload and payload[f] is not None:
            setattr(r, f, payload[f])
    if payload.get("frequency"):
        if payload["frequency"] not in analytics.FREQUENCY_MONTHS:
            raise HTTPException(400, "bad frequency %r" % payload["frequency"])
        r.frequency = payload["frequency"]
    if "next_due" in payload:
        r.next_due = parse_date(payload["next_due"])
    if payload.get("amount") is not None:
        r.amount = float(payload["amount"])
    elif payload.get("amount_monthly") is not None:
        r.amount = analytics.to_monthly(
            float(payload["amount_monthly"]) * 12, "yearly")
    r.amount_monthly = analytics.to_monthly(r.amount, r.frequency or "monthly")
    if "counts_as_investment" in payload:
        r.counts_as_investment = 1 if payload["counts_as_investment"] else 0
    s.commit()
    out = service.recurring_to_dict(r)
    s.close()
    return out


@app.delete("/api/recurring/{rid}")
def delete_recurring(rid: int):
    s = db()
    r = s.get(RecurringOutflow, rid)
    if r:
        s.delete(r)
        s.commit()
    s.close()
    return {"ok": True}


# ---------------- loans ----------------
@app.get("/api/loans")
def list_loans():
    s = db()
    out = [service.loan_to_dict(loan) for loan in s.query(Loan).all()]
    s.close()
    return out


@app.post("/api/loans")
def add_loan(payload: dict = Body(...)):
    s = db()
    loan = Loan(owner_id=payload.get("owner_id") or s.query(Owner).first().id,
                name=payload["name"], kind=payload.get("kind") or "home",
                principal_outstanding=float(payload["principal_outstanding"]),
                annual_rate=float(payload["annual_rate"]),
                emi=float(payload.get("emi") or 0),
                tenure_months_remaining=int(payload.get("tenure_months_remaining") or 0),
                notes=payload.get("notes") or "")
    s.add(loan)
    s.commit()
    out = service.loan_to_dict(loan)
    s.close()
    return out


@app.put("/api/loans/{lid}")
def update_loan(lid: int, payload: dict = Body(...)):
    s = db()
    loan = s.get(Loan, lid)
    if not loan:
        raise HTTPException(404, "not found")
    for f in ("name", "kind", "principal_outstanding", "annual_rate", "emi",
              "tenure_months_remaining", "notes"):
        if f in payload and payload[f] is not None:
            setattr(loan, f, payload[f])
    s.commit()
    out = service.loan_to_dict(loan)
    s.close()
    return out


@app.delete("/api/loans/{lid}")
def delete_loan(lid: int):
    s = db()
    loan = s.get(Loan, lid)
    if loan:
        s.delete(loan)
        s.commit()
    s.close()
    return {"ok": True}


@app.post("/api/loans/prepay-vs-invest")
def prepay_vs_invest(payload: dict = Body(...)):
    res = analytics.prepay_vs_invest(
        float(payload["principal"]), float(payload["annual_rate"]),
        float(payload["emi"]), float(payload["lumpsum"]),
        float(payload.get("invest_return_pct") or 12.0))
    if res is None:
        raise HTTPException(400, "EMI does not cover the monthly interest")
    return {k: round(v, 2) for k, v in res.items()}


@app.get("/api/loans/{lid}/schedule")
def loan_schedule(lid: int):
    s = db()
    loan = s.get(Loan, lid)
    if not loan:
        raise HTTPException(404, "not found")
    rows, months = analytics.amortization_schedule(
        loan.principal_outstanding, loan.annual_rate, loan.emi)
    s.close()
    return {"months_to_close": months,
            "total_interest": round(sum(r["interest"] for r in rows), 2),
            "schedule": [{k: round(v, 2) for k, v in r.items()}
                         for r in rows[:360]]}


# ---------------- snapshots ----------------
@app.post("/api/snapshots")
def take_snapshot():
    s = db()
    data = service.full_pipeline(s)
    agg = data["agg"]
    total_liab = sum(loan["principal_outstanding"] for loan in data["loans"])
    existing = s.query(Snapshot).filter(Snapshot.date == date.today()).first()
    if existing:
        s.delete(existing)
    s.add(Snapshot(date=date.today(), total_assets=agg["total"],
                   total_liabilities=total_liab,
                   net_worth=agg["total"] - total_liab,
                   by_class_json=json.dumps(agg["by_class"]),
                   by_owner_json=json.dumps(agg["by_owner"])))
    s.commit()
    s.close()
    return {"ok": True}


# ---------------- settings ----------------
SETTING_KEYS = ("emergency_fund_target", "savings_float", "tax_80c_used",
                "tax_80ccd1b_used", "age", "income_basis",
                "inflation_pct", "step_up_pct", "swr_multiple")


@app.get("/api/targets/presets")
def targets_presets(age: int = None):
    """Suggested target allocations. Age-based card appears when age given."""
    s = db()
    if age is None:
        raw = get_setting(s, "age", "")
        if raw:
            try:
                age = int(float(raw))
            except ValueError:
                age = None
    s.close()
    if age is not None and not (10 <= age <= 100):
        raise HTTPException(400, "age must be between 10 and 100")
    return {"age": age, "presets": analytics.target_presets(age)}


@app.get("/api/settings")
def get_settings():
    s = db()
    out = {"targets": get_targets(s),
           "targets_customized": bool(get_setting(s, "targets", ""))}
    for k in SETTING_KEYS:
        out[k] = get_setting(s, k, "")
    s.close()
    return out


@app.put("/api/settings")
def put_settings(payload: dict = Body(...)):
    s = db()
    if "targets" in payload:
        set_setting(s, "targets", json.dumps(payload["targets"]))
    for k in SETTING_KEYS:
        if k in payload:
            set_setting(s, k, str(payload[k]))
    s.close()
    return {"ok": True}


# ---------------- financial independence ----------------
@app.get("/api/fi")
def fi_projection(years: int = 40, inflation_pct: float = None,
                  step_up_pct: float = None, swr_multiple: float = None):
    """FI projection under three equity assumptions, from live data."""
    s = db()
    data = service.full_pipeline(s)
    agg = data["agg"]
    cf = data["cashflow"]

    inflation = (inflation_pct if inflation_pct is not None
                 else service.float_setting(s, "inflation_pct",
                                            fi_mod.DEFAULT_INFLATION))
    step_up = (step_up_pct if step_up_pct is not None
               else service.float_setting(s, "step_up_pct",
                                          fi_mod.DEFAULT_STEP_UP))
    multiple = (swr_multiple if swr_multiple is not None
                else service.float_setting(s, "swr_multiple",
                                           fi_mod.DEFAULT_SWR_MULTIPLE))

    # What is actually invested every month, and what will be once the loan
    # closes. Expenses here already exclude EMI, which is what post-FI
    # spending looks like.
    annual_investment = cf["committed_invest_m"] * 12
    annual_expense = cf["expense_m"] * 12
    payoff_year, freed_emi = fi_mod.loan_payoff_year(
        data["loans"], analytics.amortization_schedule)

    targets = data["targets"]
    kw = dict(target_allocation=targets, inflation_pct=inflation,
              step_up_pct=step_up, swr_multiple=multiple, years=years,
              payoff_year=payoff_year, freed_emi_annual=freed_emi)

    scen = fi_mod.scenarios(agg["by_bucket"], annual_investment,
                            annual_expense, **kw)
    coast = fi_mod.coast_fi(agg["by_bucket"], annual_expense,
                            target_allocation=targets, inflation_pct=inflation,
                            step_up_pct=step_up, swr_multiple=multiple,
                            years=years)

    notes = []
    if annual_expense <= 0:
        notes.append("No expenses recorded, so the FI target is zero and the "
                     "projection is meaningless. Log a month of spending first.")
    if annual_investment <= 0:
        notes.append("No monthly investing recorded, so only existing corpus "
                     "compounds.")
    if payoff_year is None and data["loans"]:
        notes.append("A loan's EMI does not cover its interest, so the payoff "
                     "year could not be computed and no freed EMI is assumed.")
    elif payoff_year:
        notes.append("The loan closes in about %d years; from then on %s/year "
                     "of freed EMI is assumed to be invested."
                     % (payoff_year, analytics._inr(freed_emi)))
    s.close()
    return {
        "assumptions": {
            "inflation_pct": inflation, "step_up_pct": step_up,
            "swr_multiple": multiple, "years": years,
            "returns_pct": fi_mod.DEFAULT_RETURNS,
            "annual_investment": round(annual_investment, 2),
            "annual_expense": round(annual_expense, 2),
            "new_money_allocation_pct": targets,
            "loan_payoff_year": payoff_year,
            "freed_emi_annual": round(freed_emi, 2),
        },
        "fi_number_today": round(annual_expense * multiple, 2),
        "corpus_today": round(agg["total"], 2),
        "scenarios": scen,
        "coast": {"years_to_fi": coast["years_to_fi"]},
        "notes": notes,
    }


# ---------------- export ----------------
def _fi_for_export(s, data):
    """Compact FI block for the export: assumptions plus the headline result."""
    cf = data["cashflow"]
    annual_expense = cf["expense_m"] * 12
    annual_investment = cf["committed_invest_m"] * 12
    multiple = service.float_setting(s, "swr_multiple",
                                     fi_mod.DEFAULT_SWR_MULTIPLE)
    inflation = service.float_setting(s, "inflation_pct",
                                      fi_mod.DEFAULT_INFLATION)
    step_up = service.float_setting(s, "step_up_pct", fi_mod.DEFAULT_STEP_UP)
    payoff_year, freed = fi_mod.loan_payoff_year(
        data["loans"], analytics.amortization_schedule)
    scen = fi_mod.scenarios(
        data["agg"]["by_bucket"], annual_investment, annual_expense,
        target_allocation=data["targets"], inflation_pct=inflation,
        step_up_pct=step_up, swr_multiple=multiple, years=40,
        payoff_year=payoff_year, freed_emi_annual=freed)
    return {
        "fi_number_today": round(annual_expense * multiple, 2),
        "corpus_today": round(data["agg"]["total"], 2),
        "assumptions": {
            "annual_expense_excludes_emi": True,
            "expense_multiple": multiple,
            "inflation_pct": inflation,
            "sip_step_up_pct": step_up,
            "returns_pct_by_bucket": fi_mod.DEFAULT_RETURNS,
            "new_money_allocated_at": data["targets"],
            "loan_payoff_year": payoff_year,
        },
        "years_to_fi_by_equity_return": {
            str(s_["equity_return_pct"]): s_["years_to_fi"] for s_ in scen},
        "caveat": "Straight-line compounding; ignores sequence-of-returns "
                  "risk and any post-FI change in spending beyond inflation.",
    }


def build_snapshot(privacy: bool):
    s = db()
    data = service.full_pipeline(s)
    snap = export_mod.build_snapshot(
        data["holdings"], data["loans"], data["cashflow"], data["drift"],
        data["suggestions"], data["targets"], privacy_safe=privacy,
        recurring=data["recurring"], warnings=data["warnings"],
        income_basis=get_setting(s, "income_basis", ""),
        fi=_fi_for_export(s, data))
    s.close()
    return snap


@app.get("/api/export/json")
def export_json(privacy: int = 1):
    return build_snapshot(bool(privacy))


@app.get("/api/export/ai-package")
def export_ai(privacy: int = 1):
    return Response(export_mod.to_ai_package(build_snapshot(bool(privacy))),
                    media_type="text/plain")


@app.get("/api/export/pdf")
def export_pdf(privacy: int = 1):
    pdf = export_mod.to_pdf(build_snapshot(bool(privacy)))
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition":
            "attachment; filename=portfolio_snapshot_%s.pdf"
            % date.today().isoformat()})


# ---------------- demo data ----------------
@app.post("/api/demo-data")
def load_demo():
    from demo_data import seed
    s = db()
    seed(s)
    s.close()
    return {"ok": True}


@app.delete("/api/demo-data")
def clear_demo():
    """Remove everything the demo seeder created (names/notes marked DEMO)."""
    s = db()
    removed = 0
    for model in (Holding, Loan, RecurringOutflow):
        for row in s.query(model).filter(model.name.like("DEMO %")):
            s.delete(row)
            removed += 1
    for model in (IncomeEntry, ExpenseEntry):
        for row in s.query(model).filter(model.notes == "DEMO"):
            s.delete(row)
            removed += 1
    s.commit()
    s.close()
    return {"removed": removed}


@app.post("/api/reset")
def reset_all(payload: dict = Body(...)):
    """Wipe ALL data. Requires {"confirm": "ERASE"} to guard against slips."""
    if payload.get("confirm") != "ERASE":
        raise HTTPException(400, "pass {\"confirm\": \"ERASE\"} to wipe all data")
    s = db()
    for model in (Transaction, Holding, Loan, RecurringOutflow, IncomeEntry,
                  ExpenseEntry, Snapshot, Owner):
        s.query(model).delete()
    s.commit()
    service.ensure_default_owner(s)
    s.close()
    return {"ok": True}


# Serve the built React app if present (production single-process mode).
DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "frontend", "dist")
if os.path.isdir(DIST):
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
