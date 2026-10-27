"""Performance metrics, framed around the goal of Rs 500-1000 net profit per trading day."""
import numpy as np
import pandas as pd

TRADING_DAYS = 252


def _max_drawdown(equity: pd.Series) -> tuple[float, int]:
    peak = equity.cummax()
    dd = equity / peak - 1
    underwater = (dd < 0).astype(int)
    # longest run of consecutive underwater days
    runs = underwater.groupby((underwater == 0).cumsum()).sum()
    return float(dd.min()), int(runs.max() if len(runs) else 0)


def summarize(equity: pd.Series, risk_free: float = 0.065) -> dict:
    rets = equity.pct_change().dropna()
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan
    vol = rets.std() * np.sqrt(TRADING_DAYS)
    downside = rets[rets < 0].std() * np.sqrt(TRADING_DAYS)
    mdd, dd_days = _max_drawdown(equity)
    excess = rets.mean() * TRADING_DAYS - risk_free
    return {
        "start": equity.index[0].date(), "end": equity.index[-1].date(), "years": round(years, 2),
        "final_value": equity.iloc[-1], "cagr": cagr, "volatility": vol,
        "sharpe": excess / vol if vol else np.nan,
        "sortino": excess / downside if downside else np.nan,
        "max_drawdown": mdd, "longest_drawdown_days": dd_days,
        "calmar": cagr / abs(mdd) if mdd else np.nan,
    }


def daily_income_view(equity: pd.Series, capital: float, targets=(500, 1000)) -> dict:
    """What 'Rs X per day' actually looks like for this return stream at a given capital."""
    rets = equity.pct_change().dropna()
    pnl = rets * capital  # P&L if capital were held constant (no compounding) - the honest per-day view
    monthly = (1 + rets).resample("ME").prod() - 1
    cagr = summarize(equity)["cagr"]
    out = {
        "capital": capital,
        "avg_daily_pnl": pnl.mean(),
        "median_daily_pnl": pnl.median(),
        "pct_days_positive": (pnl > 0).mean(),
        "p10_day": pnl.quantile(0.10), "p90_day": pnl.quantile(0.90),
        "worst_day": pnl.min(), "best_day": pnl.max(),
        "worst_month": monthly.min() * capital,
        "pct_months_negative": (monthly < 0).mean(),
    }
    for t in targets:
        out[f"pct_days_ge_{t}"] = (pnl >= t).mean()
        # capital needed so that the long-run average equals the target per trading day
        out[f"capital_for_avg_{t}_per_day"] = t * TRADING_DAYS / cagr if cagr and cagr > 0 else np.inf
    return out


def trade_stats(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"num_trades": 0}
    wins = trades[trades.pnl > 0]
    losses = trades[trades.pnl <= 0]
    return {
        "num_trades": len(trades),
        "win_rate": len(wins) / len(trades),
        "avg_win_pct": wins["return"].mean() if len(wins) else 0.0,
        "avg_loss_pct": losses["return"].mean() if len(losses) else 0.0,
        "profit_factor": wins.pnl.sum() / -losses.pnl.sum() if losses.pnl.sum() < 0 else np.inf,
        "avg_days_held": trades.days_held.mean(),
        "pct_long_term": (trades.days_held > 365).mean(),
    }


def yearly_returns(equity: pd.Series) -> pd.Series:
    yearly = equity.resample("YE").last()
    first = pd.Series([equity.iloc[0]], index=[equity.index[0]])
    return pd.concat([first, yearly]).pct_change().dropna().rename(lambda d: d.year)


def _fmt(v):
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


def render(result, benchmark: pd.Series | None = None) -> str:
    cfg = result.settings.strategy
    eq = result.equity
    s = summarize(eq)
    d = daily_income_view(eq, cfg.initial_capital)
    t = trade_stats(result.trades)
    lines = ["=" * 64, "MOMENTUM STRATEGY BACKTEST (net of charges, slippage and tax)", "=" * 64]
    lines += [f"Period            : {s['start']} -> {s['end']} ({s['years']} yrs)",
              f"Starting capital  : Rs {cfg.initial_capital:,.0f}",
              f"Final value       : Rs {s['final_value']:,.0f}",
              f"CAGR (post-tax)   : {s['cagr']:.2%}",
              f"Volatility        : {s['volatility']:.2%}",
              f"Sharpe / Sortino  : {s['sharpe']:.2f} / {s['sortino']:.2f}",
              f"Max drawdown      : {s['max_drawdown']:.2%} (longest underwater {s['longest_drawdown_days']} days)",
              f"Avg exposure      : {result.exposure.mean():.0%}",
              f"Charges paid      : Rs {result.charges_paid:,.0f}",
              f"Tax paid          : Rs {result.taxes.sum():,.0f}"]
    if benchmark is not None and len(benchmark.dropna()) > 1:
        b = summarize(benchmark.dropna())
        lines.append(f"Benchmark (Nifty 50 B&H, pre-tax, no costs): CAGR {b['cagr']:.2%}, "
                     f"max DD {b['max_drawdown']:.2%}")
    lines += ["", "--- Trades ---"]
    lines += [f"{k:<18}: {_fmt(v)}" for k, v in t.items()]
    lines += ["", "--- Yearly returns ---"]
    lines += [f"{y}: {r:+.1%}" for y, r in yearly_returns(eq).items()]
    lines += ["", f"--- 'Daily income' reality check on Rs {d['capital']:,.0f} (constant capital) ---",
              f"Average day       : Rs {d['avg_daily_pnl']:,.0f}",
              f"Median day        : Rs {d['median_daily_pnl']:,.0f}",
              f"Days positive     : {d['pct_days_positive']:.0%}",
              f"10% / 90% day     : Rs {d['p10_day']:,.0f} / Rs {d['p90_day']:,.0f}",
              f"Worst day / month : Rs {d['worst_day']:,.0f} / Rs {d['worst_month']:,.0f}",
              f"Months negative   : {d['pct_months_negative']:.0%}",
              f"Days >= Rs 500    : {d['pct_days_ge_500']:.0%}",
              f"Days >= Rs 1000   : {d['pct_days_ge_1000']:.0%}",
              f"Capital needed for Rs 500/day average : Rs {d['capital_for_avg_500_per_day']:,.0f}",
              f"Capital needed for Rs 1000/day average: Rs {d['capital_for_avg_1000_per_day']:,.0f}"]
    lines += [f"NOTE: {n}" for n in result.notes]
    return "\n".join(lines)
