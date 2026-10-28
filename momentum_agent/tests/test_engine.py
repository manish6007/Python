"""Correctness tests. Synthetic prices here only exercise the mechanics - they say nothing
about whether the strategy makes money."""
import dataclasses

import numpy as np
import pandas as pd
import pytest

from momentum_agent.backtest import run_backtest
from momentum_agent.config import ChargeSchedule, Settings, StrategyConfig, TaxConfig
from momentum_agent.costs import TaxState, financial_year, fy_tax, trade_charges


def test_delivery_charges_round_trip():
    s = ChargeSchedule()
    buy = trade_charges("buy", 100_000, s)
    sell = trade_charges("sell", 100_000, s)
    # STT 100 + stamp 15 + exchange ~2.97 + SEBI 0.1 + GST ~0.55 = ~118.6
    assert buy == pytest.approx(118.63, abs=0.05)
    # STT 100 + exchange + SEBI + GST + DP 15.93 = ~119.55
    assert sell == pytest.approx(119.55, abs=0.05)
    # ~0.24% round trip at Rs 1 lakh: every rotation costs about this much before slippage
    assert (buy + sell) / 100_000 == pytest.approx(0.0024, abs=0.0001)


def test_financial_year():
    assert financial_year("2025-03-31") == 2024
    assert financial_year("2025-04-01") == 2025


def test_tax_new_regime_and_setoff():
    cfg = TaxConfig()
    st = TaxState()
    # FY2025-26: 1L STCG @20%, 2L LTCG with 1.25L exemption @12.5%, plus 4% cess
    tax = fy_tax(100_000, 200_000, 2025, st, cfg)
    assert tax == pytest.approx((20_000 + 75_000 * 0.125) * 1.04)
    # Short-term loss absorbs long-term gain; leftover loss is carried forward
    st = TaxState()
    assert fy_tax(-300_000, 200_000, 2025, st, cfg) == 0
    assert st.st_loss_cf == pytest.approx(100_000)
    # ...and is used next year
    assert fy_tax(150_000, 0, 2026, st, cfg) == pytest.approx(50_000 * 0.20 * 1.04)


def test_ltcg_exempt_before_2018():
    assert fy_tax(0, 500_000, 2016, TaxState(), TaxConfig()) == 0


def _synthetic_panel(n_days=900, n_stocks=30, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-01", periods=n_days)
    drifts = np.linspace(-0.0005, 0.0015, n_stocks)
    rets = rng.normal(drifts, 0.015, size=(n_days, n_stocks))
    close = pd.DataFrame(500 * np.exp(np.cumsum(rets, axis=0)), index=dates,
                         columns=[f"S{i:02d}" for i in range(n_stocks)])
    open_ = close.shift(1).fillna(close) * (1 + rng.normal(0, 0.002, close.shape))
    volume = pd.DataFrame(1_000_000.0, index=dates, columns=close.columns)
    index_close = close.mean(axis=1)
    return {"open": open_, "close": close, "volume": volume}, index_close


def _settings(**kw):
    return Settings(strategy=dataclasses.replace(StrategyConfig(), **kw))


def test_backtest_runs_and_prefers_strong_trends():
    panel, idx = _synthetic_panel()
    res = run_backtest(panel, idx, _settings(num_positions=5, max_gap_pct=1.0))
    assert len(res.equity) == len(panel["close"])
    assert not res.trades.empty
    held = res.trades.symbol.str[1:].astype(int)
    assert held.mean() > 15  # higher-drift names (higher index) should dominate selections
    # FY-end tax paid while fully invested can push cash marginally negative (an overdraft that
    # the next sell repays); equity is still reduced by the full tax.
    assert (res.exposure <= 1.01).all()


def test_no_free_money_without_costs():
    """With zero charges/slippage/tax and flat prices, equity must stay exactly at capital."""
    panel, idx = _synthetic_panel()
    flat = {k: v.copy() for k, v in panel.items()}
    flat["open"] = flat["close"] = pd.DataFrame(100.0, index=panel["close"].index,
                                                columns=panel["close"].columns)
    zero = ChargeSchedule(stt_pct=0, exchange_pct=0, sebi_pct=0, stamp_pct=0, dp_charge_per_sell=0)
    s = Settings(strategy=dataclasses.replace(StrategyConfig(), slippage_pct=0.0,
                                              use_regime_filter=False), charges=zero)
    res = run_backtest(flat, None, s)
    assert res.equity.iloc[-1] == pytest.approx(s.strategy.initial_capital)


def test_no_lookahead_fill_is_next_open():
    panel, idx = _synthetic_panel()
    res = run_backtest(panel, idx, _settings(num_positions=5, max_gap_pct=1.0, slippage_pct=0.0))
    first = res.trades.sort_values("entry_date").iloc[0]
    # Entry must be on the session after a rebalance (weeks end Friday => Monday entry)
    assert first.entry_date.dayofweek == 0


def test_stop_loss_exits_at_stop_and_blocks_reentry():
    panel, idx = _synthetic_panel()
    s = _settings(num_positions=5, max_gap_pct=1.0, slippage_pct=0.0, stop_loss_pct=0.10)
    base = run_backtest(panel, idx, s)
    first = base.trades.sort_values("entry_date").iloc[0]
    sym, entry = first.symbol, first.entry_date

    # Crash that stock 30% intraday (low only) two sessions after entry; it closes unchanged.
    crash_day = panel["close"].index[panel["close"].index.get_loc(entry) + 2]
    panel = {k: v.copy() for k, v in panel.items()}
    panel["low"] = panel["close"].copy()
    panel["low"].loc[crash_day, sym] = panel["open"].loc[crash_day, sym] * 0.7

    res = run_backtest(panel, idx, s)
    stops = res.trades[res.trades.reason == "stop-loss"]
    hit = stops[(stops.symbol == sym) & (stops.exit_date == crash_day)]
    assert len(hit) == 1
    entry_fill = panel["open"].loc[entry, sym]
    exit_px = hit.iloc[0].proceeds / hit.iloc[0].qty
    assert exit_px == pytest.approx(entry_fill * 0.90, rel=0.002)  # stop price, minus sell charges
    # Not re-bought within the cooldown window
    reentries = res.trades[(res.trades.symbol == sym) & (res.trades.entry_date > crash_day)]
    if len(reentries):
        gap = panel["close"].index.get_loc(reentries.entry_date.min()) - panel["close"].index.get_loc(crash_day)
        assert gap >= s.strategy.reentry_cooldown_days
