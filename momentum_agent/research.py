"""Strategy research harness: compare variants, blend sleeves, and stress-test withdrawals.

    python -m momentum_agent.research --csv-dir data_cache_long --start 2010-01-01 --out research_out

Everything runs on cached CSVs (see data.download_yahoo), so results are reproducible offline.
The question this answers is not "which variant has the best CAGR" but "which one can fund
living costs after a layoff without the corpus being wrecked by a bad first year".
"""
import argparse
import dataclasses
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import run_backtest
from .config import Settings, StrategyConfig
from .data import load_csv_dir, to_panel
from .report import summarize
from .universe import load_universe

TRADING_DAYS = 252

# Post-tax yield assumptions for the non-equity sleeves (debt funds are taxed at slab since Apr-2023).
DEBT_YIELD_PRE_TAX = 0.07
SLAB_TAX = 0.312                     # 30% + 4% cess
GOLD_LTCG = 0.125 * 1.04             # gold ETFs held > 12 months
INFLATION = 0.06

# Every variant overrides StrategyConfig defaults; the 10% stop is part of the default config.
VARIANTS = {
    "A_baseline_stop10":   dict(),
    "B_no_stop":           dict(stop_loss_pct=None),
    "C_no_stop_cash":      dict(stop_loss_pct=None, cash_yield=0.045),
    "D_monthly":           dict(stop_loss_pct=None, cash_yield=0.045, rebalance="M"),
    "E_15pos":             dict(stop_loss_pct=None, cash_yield=0.045, num_positions=15, exit_rank=35),
    "F_20pos":             dict(stop_loss_pct=None, cash_yield=0.045, num_positions=20, exit_rank=40),
    "G_skip21":            dict(stop_loss_pct=None, cash_yield=0.045, skip_days=21),
    "H_lowvol_tilt":       dict(stop_loss_pct=None, cash_yield=0.045, lowvol_weight=0.5),
    "I_regime_exit":       dict(stop_loss_pct=None, cash_yield=0.045, regime_exit=True),
    "J_voltarget":         dict(stop_loss_pct=None, cash_yield=0.045, target_vol=0.15),
    "K_combo":             dict(stop_loss_pct=None, cash_yield=0.045, num_positions=15, exit_rank=35,
                                lowvol_weight=0.5, target_vol=0.15),
    "L_combo_stop20":      dict(stop_loss_pct=0.20, cash_yield=0.045, num_positions=15, exit_rank=35,
                                lowvol_weight=0.5, target_vol=0.15),
    # Second round: combine the three ideas that each cut drawdown without hurting return much.
    "M_rexit_lowvol":      dict(stop_loss_pct=None, cash_yield=0.045, regime_exit=True, lowvol_weight=0.5),
    "N_rexit_lowvol_15":   dict(stop_loss_pct=None, cash_yield=0.045, regime_exit=True, lowvol_weight=0.5,
                                num_positions=15, exit_rank=35),
    "O_rexit_lowvol_20":   dict(stop_loss_pct=None, cash_yield=0.045, regime_exit=True, lowvol_weight=0.5,
                                num_positions=20, exit_rank=40),
    "P_N_skip21":          dict(stop_loss_pct=None, cash_yield=0.045, regime_exit=True, lowvol_weight=0.5,
                                num_positions=15, exit_rank=35, skip_days=21),
    "Q_N_monthly":         dict(stop_loss_pct=None, cash_yield=0.045, regime_exit=True, lowvol_weight=0.5,
                                num_positions=15, exit_rank=35, rebalance="M"),
    "R_N_stop10":          dict(stop_loss_pct=0.10, cash_yield=0.045, regime_exit=True, lowvol_weight=0.5,
                                num_positions=15, exit_rank=35),
}

SPLIT_DATE = "2018-01-01"   # robustness: a rule must work in BOTH halves, not just on average


def metrics_row(name: str, equity: pd.Series, trades: pd.DataFrame | None = None) -> dict:
    s = summarize(equity)
    rets = equity.pct_change().dropna()
    yearly = equity.resample("YE").last().pct_change().dropna()
    roll3 = (equity / equity.shift(3 * TRADING_DAYS)) ** (1 / 3) - 1
    row = {"variant": name, "cagr": s["cagr"], "vol": s["volatility"], "sharpe": s["sharpe"],
           "max_dd": s["max_drawdown"], "calmar": s["calmar"], "dd_days": s["longest_drawdown_days"],
           "worst_year": yearly.min(), "pct_years_neg": (yearly < 0).mean(),
           "worst_3y_cagr": roll3.min(), "worst_month": ((1 + rets).resample("ME").prod() - 1).min()}
    for label, part in (("1st", equity[equity.index < SPLIT_DATE]), ("2nd", equity[equity.index >= SPLIT_DATE])):
        if len(part) > TRADING_DAYS:
            ps = summarize(part)
            row[f"cagr_{label}"], row[f"dd_{label}"] = ps["cagr"], ps["max_drawdown"]
    if trades is not None and len(trades):
        row["trades_per_year"] = len(trades) / s["years"]
    return row


def corpus_needed(equity: pd.Series, monthly: float, months: int, keep: float = 0.6) -> float:
    """Smallest corpus that can fund `monthly` for `months` starting in ANY historical month and
    still hold >= `keep` of its starting value at the end (so it can recover and be reused)."""
    lo, hi = monthly, monthly * 1000
    for _ in range(40):
        mid = (lo + hi) / 2
        if withdrawal_test(equity, mid, monthly, months)["worst_end"] >= keep * mid:
            hi = mid
        else:
            lo = mid
    return hi


def sustainable_rate(equity: pd.Series, years: int = 8, inflation: float = INFLATION) -> float:
    """Highest starting withdrawal rate (inflation-indexed) that kept the REAL corpus intact over
    `years` for every historical start month - the 'live off it indefinitely' rate."""
    m = equity.resample("ME").last().pct_change().dropna()
    months = years * 12
    worst = []
    for start in range(len(m) - months + 1):
        lo, hi = 0.0, 0.5
        for _ in range(30):
            rate = (lo + hi) / 2
            bal, draw = 1.0, rate / 12
            for j in range(months):
                bal = bal * (1 + m.iloc[start + j]) - draw
                if j % 12 == 11:
                    draw *= 1 + inflation
            if bal >= (1 + inflation) ** years:
                lo = rate
            else:
                hi = rate
        worst.append(lo)
    return float(min(worst)) if worst else float("nan")


def blend(sleeves: dict[str, pd.Series], weights: dict[str, float], gold_symbol="gold") -> pd.Series:
    """Monthly-rebalanced mix of sleeve equity curves (each already post-tax except gold).

    Gold gains realised by rebalancing pay 12.5% LTCG; the momentum sleeve's taxes are inside
    its own curve; debt is modelled as a post-tax constant yield.
    """
    rets = pd.DataFrame({k: v.pct_change() for k, v in sleeves.items()}).dropna()
    month_end = set(pd.Series(rets.index, index=rets.index).groupby(rets.index.to_period("M")).max())
    value = {k: w for k, w in weights.items()}
    gold_basis = value.get(gold_symbol, 0.0)
    curve = []
    for day, r in rets.iterrows():
        for k in value:
            value[k] *= 1 + r[k]
        total = sum(value.values())
        if day in month_end:
            if gold_symbol in value and value[gold_symbol] > weights[gold_symbol] * total:
                sold = value[gold_symbol] - weights[gold_symbol] * total
                gain_frac = max(0.0, 1 - gold_basis / value[gold_symbol])
                tax = sold * gain_frac * GOLD_LTCG
                gold_basis *= 1 - sold / value[gold_symbol]
                total -= tax
            elif gold_symbol in value:
                gold_basis += weights[gold_symbol] * total - value[gold_symbol]
            value = {k: weights[k] * total for k in weights}
        curve.append(total)
    return pd.Series(curve, index=rets.index)


def withdrawal_test(equity: pd.Series, capital: float, monthly: float, months: int,
                    inflation: float = INFLATION) -> dict:
    """Start a layoff in every month of history; withdraw `monthly` (inflation-indexed) for `months`.

    Reports how the corpus looks when the withdrawals stop, across all start dates.
    """
    m = equity.resample("ME").last()
    mret = m.pct_change().dropna()
    ends = []
    for start in range(len(mret) - months + 1):
        bal, draw = capital, monthly
        for j in range(months):
            bal = bal * (1 + mret.iloc[start + j]) - draw
            if j % 12 == 11:
                draw *= 1 + inflation
            if bal <= 0:
                bal = 0.0
                break
        ends.append(bal)
    ends = np.array(ends)
    return {"scenarios": len(ends), "depleted_pct": float((ends <= 0).mean()),
            "worst_end": float(ends.min()), "p10_end": float(np.quantile(ends, 0.10)),
            "median_end": float(np.median(ends)), "pct_end_below_half": float((ends < capital / 2).mean())}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv-dir", default="data_cache_long")
    p.add_argument("--start", default="2010-01-01")
    p.add_argument("--capital", type=float, default=550_000)
    p.add_argument("--out", default="research_out")
    p.add_argument("--only", nargs="*", help="variant names to run (default: all)")
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(exist_ok=True)

    universe = set(load_universe())
    frames = load_csv_dir(args.csv_dir)
    index_close = frames["^NSEI"]["Close"]
    gold = frames["GOLDBEES"]["Close"]
    panel = to_panel({s: f for s, f in frames.items() if s in universe})
    print(f"Universe: {len(panel['close'].columns)} stocks, data {panel['close'].index[0].date()} -> "
          f"{panel['close'].index[-1].date()}")

    rows, curves = [], {}
    for name, overrides in VARIANTS.items():
        if args.only and name not in args.only:
            continue
        cfg = dataclasses.replace(StrategyConfig(initial_capital=args.capital), **overrides)
        res = run_backtest(panel, index_close, Settings(strategy=cfg), start=args.start)
        curves[name] = res.equity
        rows.append(metrics_row(name, res.equity, res.trades))
        print(f"  {name:<20} CAGR {rows[-1]['cagr']:.1%}  maxDD {rows[-1]['max_dd']:.1%}")

    nifty = index_close[index_close.index >= pd.Timestamp(args.start)]
    curves["Nifty50_pretax"] = nifty / nifty.iloc[0] * args.capital
    rows.append(metrics_row("Nifty50_pretax", curves["Nifty50_pretax"]))
    g = gold[gold.index >= pd.Timestamp(args.start)].reindex(nifty.index).ffill()
    curves["Gold_pretax"] = g / g.iloc[0] * args.capital
    rows.append(metrics_row("Gold_pretax", curves["Gold_pretax"]))

    debt_daily = (1 + DEBT_YIELD_PRE_TAX * (1 - SLAB_TAX)) ** (1 / TRADING_DAYS) - 1
    debt = pd.Series((1 + debt_daily) ** np.arange(len(nifty)), index=nifty.index) * args.capital

    best = [n for n in ("N_rexit_lowvol_15", "C_no_stop_cash", "M_rexit_lowvol") if n in curves]
    for core in best:
        for w_eq, w_gold, w_debt in ((0.7, 0.15, 0.15), (0.6, 0.2, 0.2), (0.5, 0.2, 0.3)):
            name = f"MIX_{core.split('_')[0]}_{int(w_eq*100)}/{int(w_gold*100)}/{int(w_debt*100)}"
            curves[name] = blend({"eq": curves[core], "gold": curves["Gold_pretax"], "debt": debt},
                                 {"eq": w_eq, "gold": w_gold, "debt": w_debt}) * args.capital
            rows.append(metrics_row(name, curves[name]))

    table = pd.DataFrame(rows).set_index("variant")
    table.to_csv(out / "variants.csv")
    pd.DataFrame(curves).to_csv(out / "equity_curves.csv")
    with pd.option_context("display.width", 200, "display.max_columns", 20,
                           "display.float_format", "{:,.3f}".format):
        print("\n", table)

    # Layoff stress test: what if the layoff starts in the worst possible month?
    wd_rows = []
    for name in [n for n in curves if n.startswith(("MIX_", "N_", "C_", "Nifty"))]:
        row = {"portfolio": name, "sustainable_rate_8y": sustainable_rate(curves[name])}
        for monthly in (15_000, 30_000):
            r = withdrawal_test(curves[name], args.capital, monthly, 12)
            row[f"worst_end_5.5L_{monthly//1000}k_12m"] = r["worst_end"]
            for months in (12, 24):
                row[f"corpus_{monthly//1000}k_{months}m"] = corpus_needed(curves[name], monthly, months)
        wd_rows.append(row)
    wd = pd.DataFrame(wd_rows).set_index("portfolio")
    wd.to_csv(out / "withdrawals.csv")
    with pd.option_context("display.width", 200, "display.max_columns", 20,
                           "display.float_format", "{:,.2f}".format):
        print("\n", wd)


if __name__ == "__main__":
    main()
