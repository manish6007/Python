"""Unit tests for the pure-python analytics engine (no external deps)."""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import analytics  # noqa: E402


def test_fd_value_compounds_quarterly():
    v = analytics.fd_value(100000, 8.0, date(2024, 1, 1), date(2025, 1, 1))
    assert 108000 < v < 108400  # ~8.24% effective


def test_holding_value_unit_priced():
    h = {"asset_class": "stock", "units": 10, "last_price": 250.0}
    assert analytics.holding_value(h) == 2500.0


def test_holding_value_balance_based_accrues():
    h = {"asset_class": "ppf", "manual_value": 100000, "rate": 7.1,
         "value_date": date(2025, 1, 1)}
    v = analytics.holding_value(h, date(2026, 1, 1))
    assert 106900 < v < 107300


def test_bucket_mapping_and_override():
    assert analytics.holding_bucket({"asset_class": "sgb"}) == "gold"
    assert analytics.holding_bucket(
        {"asset_class": "mutual_fund", "meta": {"category": "debt"}}) == "debt"
    assert analytics.holding_bucket(
        {"asset_class": "other", "meta": {"bucket": "equity"}}) == "equity"


def test_aggregate_totals():
    hs = [{"asset_class": "stock", "units": 1, "last_price": 100, "owner": "A"},
          {"asset_class": "savings", "manual_value": 50, "owner": "B",
           "value_date": date.today()}]
    agg = analytics.aggregate(hs)
    assert agg["total"] == 150
    assert agg["by_owner"] == {"A": 100.0, "B": 50.0}
    assert agg["by_bucket"]["equity"] == 100.0


def test_allocation_drift_sorted_underweight_first():
    drift = analytics.allocation_drift({"equity": 80, "debt": 20},
                                       {"equity": 60, "debt": 40})
    assert drift[0]["bucket"] == "debt"
    assert abs(drift[0]["gap_amount"] - 20.0) < 1e-6


def test_xirr_simple_doubling():
    flows = [(date(2020, 1, 1), -1000), (date(2027, 1, 1), 2000)]
    r = analytics.xirr(flows)
    assert r is not None and 0.095 < r < 0.11  # ~10.4% doubles in 7y


def test_xirr_degenerate_returns_none():
    assert analytics.xirr([(date(2020, 1, 1), -100)]) is None
    assert analytics.xirr([(date(2020, 1, 1), -100),
                           (date(2021, 1, 1), -50)]) is None


def test_monthly_cashflow_surplus():
    rec = [{"kind": "emi", "amount_monthly": 40000, "counts_as_investment": False},
           {"kind": "sip", "amount_monthly": 30000, "counts_as_investment": True}]
    cf = analytics.monthly_cashflow(840000, 240000, 3, rec)
    assert cf["income_m"] == 280000
    assert cf["expense_m"] == 80000
    assert cf["surplus_m"] == 280000 - 80000 - 40000 - 30000
    assert cf["savings_rate_pct"] > 0


def test_suggestions_priorities():
    ctx = {"surplus_m": 50000, "emergency_fund_target": 600000,
           "liquid_assets": 200000,
           "loans": [{"name": "PL", "kind": "personal", "annual_rate": 14.0,
                      "principal_outstanding": 100000}],
           "drift": [{"bucket": "debt", "drift_pct": -10, "target_pct": 30,
                      "actual_pct": 20, "gap_amount": 100000}]}
    out = analytics.suggestions(ctx)
    titles = " | ".join(s["title"] for s in out)
    assert "emergency fund" in titles.lower()
    assert "high-interest" in titles.lower()
    assert out[0]["priority"] == 1


def test_suggestions_negative_surplus_short_circuits():
    out = analytics.suggestions({"surplus_m": -5000})
    assert len(out) == 1 and out[0]["priority"] == 1


def test_amortization_and_prepay():
    rows, months = analytics.amortization_schedule(1000000, 9.0, 12668)
    assert months is not None and 115 <= months <= 125  # ~10 years
    res = analytics.prepay_vs_invest(1000000, 9.0, 12668, 100000, 12.0)
    assert res["interest_saved"] > 0
    assert res["months_saved"] > 0
    assert res["invest_future_value"] > 100000


def test_emi_not_covering_interest():
    rows, months = analytics.amortization_schedule(1000000, 12.0, 5000)
    assert months is None


def test_expense_average_uses_months_with_data_not_window():
    """One month of expenses in a 3-month window must not be divided by 3."""
    rec = []
    cf = analytics.monthly_cashflow(861000, 33000, 3, rec,
                                    income_months=3, expense_months=1)
    assert cf["income_m"] == 287000        # 3 months of salary -> /3
    assert cf["expense_m"] == 33000        # 1 month of spend   -> /1
    assert cf["surplus_m"] == 287000 - 33000
    assert cf["income_months"] == 3
    assert cf["expense_months"] == 1


def test_cashflow_divisors_fall_back_to_window():
    cf = analytics.monthly_cashflow(300000, 90000, 3, [])
    assert cf["income_m"] == 100000
    assert cf["expense_m"] == 30000


def test_cashflow_zero_months_does_not_divide_by_zero():
    cf = analytics.monthly_cashflow(0, 0, 3, [], income_months=0,
                                    expense_months=0)
    assert cf["income_m"] == 0 and cf["expense_m"] == 0


def test_presets_always_sum_to_100():
    for age in range(18, 96):
        t = analytics.suggest_targets(age=age)
        assert abs(sum(t.values()) - 100.0) < 0.05, age
    for profile in analytics.RISK_PROFILES:
        t = analytics.suggest_targets(profile=profile)
        assert abs(sum(t.values()) - 100.0) < 0.05, profile


def test_equity_for_age_rule_and_clamps():
    assert analytics.equity_for_age(40) == 60.0     # 100 - age
    assert analytics.equity_for_age(10) == 80.0     # capped
    assert analytics.equity_for_age(95) == 20.0     # floored


def test_equity_falls_as_age_rises():
    ages = [25, 40, 55, 70]
    eq = [analytics.suggest_targets(age=a)["equity"] for a in ages]
    assert eq == sorted(eq, reverse=True)


def test_very_high_equity_shrinks_sleeves_not_the_total():
    t = analytics._targets_from_equity(95.0)
    assert abs(sum(t.values()) - 100.0) < 0.05
    assert t["debt"] == 0.0 and t["gold"] < analytics.GOLD_PCT


def test_target_presets_shape():
    presets = analytics.target_presets(age=35)
    assert presets[0]["key"] == "age_rule" and presets[0]["recommended"]
    assert {p["key"] for p in presets} >= set(analytics.RISK_PROFILES)
    assert all(p["targets"] and p["name"] and p["detail"] for p in presets)
    # no age -> no age-based card
    assert all(p["key"] != "age_rule" for p in analytics.target_presets())
