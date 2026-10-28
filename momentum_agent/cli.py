"""Command line entry point.

    python -m momentum_agent.cli backtest --years 10 --capital 550000
    python -m momentum_agent.cli backtest --csv-dir my_data/       # use your own OHLCV CSVs
    python -m momentum_agent.cli signals --holdings holdings.csv   # this week's orders
    python -m momentum_agent.cli allocate --momentum 330000 --gold 110000 --debt 110000  # month-end sleeve check
"""
import argparse
import dataclasses
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .backtest import run_backtest
from .config import Settings, StrategyConfig
from .data import download_yahoo, load_csv_dir, to_panel
from .report import render
from .strategy import compute_signals, select_trades
from .universe import load_universe

WARMUP_DAYS = 420  # calendar days of history needed before the first signal (252 trading days + MA)


def _load(args, settings, start):
    symbols = load_universe(args.universe_file) + [settings.index_symbol]
    if args.csv_dir:
        frames = load_csv_dir(args.csv_dir, set(symbols))
    else:
        frames = download_yahoo(symbols, start=start, end=None, cache_dir=args.cache_dir,
                                refresh=args.refresh)
    index_frame = frames.pop(settings.index_symbol, None)
    if not frames:
        raise SystemExit("No price data loaded. Check network access / --csv-dir.")
    print(f"Loaded {len(frames)} symbols.")
    return to_panel(frames), (index_frame["Close"] if index_frame is not None else None)


def _settings(args) -> Settings:
    overrides = {k: v for k, v in {
        "initial_capital": args.capital, "num_positions": args.positions,
        "exit_rank": args.exit_rank, "rebalance": args.rebalance, "skip_days": args.skip_days,
        "stop_loss_pct": args.stop_loss,
    }.items() if v is not None}
    if args.no_regime:
        overrides["use_regime_filter"] = False
    return Settings(strategy=dataclasses.replace(StrategyConfig(), **overrides))


def cmd_backtest(args):
    settings = _settings(args)
    bt_start = date.today() - timedelta(days=int(365.25 * args.years))
    panel, index_close = _load(args, settings, start=str(bt_start - timedelta(days=WARMUP_DAYS)))
    result = run_backtest(panel, index_close, settings, start=str(bt_start))
    bench = None
    if index_close is not None:
        bench = index_close[index_close.index >= pd.Timestamp(bt_start)]
    print(render(result, bench))
    out = Path(args.out)
    out.mkdir(exist_ok=True)
    result.equity.to_csv(out / "equity.csv")
    result.trades.to_csv(out / "trades.csv", index=False)
    print(f"\nEquity curve and trade log written to {out}/")


def cmd_signals(args):
    settings = _settings(args)
    cfg = settings.strategy
    start = str(date.today() - timedelta(days=WARMUP_DAYS + 30))
    args.refresh = True
    panel, index_close = _load(args, settings, start=start)
    sig = compute_signals(panel, index_close, cfg)
    day = panel["close"].index[-1]

    holdings = set()
    if args.holdings and Path(args.holdings).exists():
        holdings = set(pd.read_csv(args.holdings)["symbol"].str.upper())
    sells, buys = select_trades(day, holdings, sig, cfg)
    close = panel["close"].loc[day]
    print(f"Signals as of close {day.date()}  |  market regime: "
          f"{'RISK-ON' if sig.regime_on.loc[day] else 'RISK-OFF (no new buys)'}")
    print("\nSELL at next open:", ", ".join(sorted(sells)) or "none")
    target = cfg.initial_capital / cfg.num_positions
    print(f"\nBUY at next open (Rs {target:,.0f} each):")
    for sym in buys:
        line = f"  {sym:<12} rank {int(sig.rank.loc[day, sym]):>3}  ~{int(target // close[sym])} sh @ ~{close[sym]:,.2f}"
        if cfg.stop_loss_pct:
            line += f"  -> after fill, set GTT stop at fill x {1 - cfg.stop_loss_pct:.2f} (~{close[sym] * (1 - cfg.stop_loss_pct):,.2f})"
        print(line)
    print("\nTop 20 ranking:")
    top = sig.rank.loc[day].dropna().sort_values().head(20)
    for sym, r in top.items():
        flag = "held" if sym in holdings else ("ok" if sig.buy_ok.loc[day, sym] else "filtered")
        print(f"  {int(r):>3}. {sym:<12} score {sig.score.loc[day, sym]:+.2f}  [{flag}]")


SLEEVES = {"momentum": 0.60, "gold": 0.20, "debt": 0.20}   # see STRATEGY.md for why


def cmd_allocate(args):
    """Month-end check of the 60/20/20 sleeves; only acts when a sleeve drifts past the band."""
    values = {"momentum": args.momentum, "gold": args.gold, "debt": args.debt}
    total = sum(values.values()) - args.withdraw
    if total <= 0:
        raise SystemExit("Nothing left to allocate.")
    print(f"Portfolio Rs {sum(values.values()):,.0f}"
          + (f", withdrawing Rs {args.withdraw:,.0f} this month" if args.withdraw else ""))
    drift = {k: values[k] / sum(values.values()) - w for k, w in SLEEVES.items()}
    if not args.withdraw and max(abs(d) for d in drift.values()) < args.band:
        print(f"All sleeves within +/-{args.band:.0%} of target - no action.")
        for k, w in SLEEVES.items():
            print(f"  {k:<9} {values[k] / sum(values.values()):6.1%}  (target {w:.0%})")
        return
    print("Move money so each sleeve is back on target:")
    for k, w in SLEEVES.items():
        delta = w * total - values[k]
        verb = "ADD   " if delta > 0 else "REMOVE"
        print(f"  {k:<9} now Rs {values[k]:>10,.0f}  target Rs {w * total:>10,.0f}  -> {verb} Rs {abs(delta):,.0f}")
    print("Momentum sleeve: pass the new target as --capital to the next 'signals' run "
          "(sells/buys there absorb the change). Withdrawals come from whichever sleeve is over target.")


def main():
    p = argparse.ArgumentParser(description="NSE delivery momentum strategy")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("backtest", "signals"):
        sp = sub.add_parser(name)
        sp.add_argument("--capital", type=float)
        sp.add_argument("--positions", type=int)
        sp.add_argument("--exit-rank", type=int)
        sp.add_argument("--rebalance", choices=["W", "M"])
        sp.add_argument("--skip-days", type=int)
        sp.add_argument("--stop-loss", type=float, help="per-trade stop as a fraction, e.g. 0.10; 0 disables")
        sp.add_argument("--no-regime", action="store_true")
        sp.add_argument("--universe-file")
        sp.add_argument("--csv-dir", help="folder of <SYMBOL>.csv files instead of downloading")
        sp.add_argument("--cache-dir", default="data_cache")
        sp.add_argument("--refresh", action="store_true")
    sub.choices["backtest"].add_argument("--years", type=float, default=10)
    sub.choices["backtest"].add_argument("--out", default="results")
    sub.choices["signals"].add_argument("--holdings", help="CSV with a 'symbol' column")
    al = sub.add_parser("allocate", help="month-end 60/20/20 sleeve rebalance check")
    al.add_argument("--momentum", type=float, required=True, help="current value of momentum stocks + their cash")
    al.add_argument("--gold", type=float, required=True, help="current value of gold ETF")
    al.add_argument("--debt", type=float, required=True, help="current value of arbitrage/liquid fund")
    al.add_argument("--withdraw", type=float, default=0.0, help="cash to take out this month (layoff mode)")
    al.add_argument("--band", type=float, default=0.05, help="rebalance only when a sleeve drifts this far")
    args = p.parse_args()
    {"backtest": cmd_backtest, "signals": cmd_signals, "allocate": cmd_allocate}[args.cmd](args)


if __name__ == "__main__":
    main()
