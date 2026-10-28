"""Daily event-driven backtester for the delivery momentum strategy.

Timeline for each trading day:
  1. Execute orders decided at the previous rebalance close, at today's OPEN (+/- slippage).
  2. Stop-loss: if today's LOW touches a holding's stop, exit at the stop (or at the open if it
     gapped below the stop) - this mirrors a GTT stop order sitting with the broker.
  3. Mark the portfolio to today's CLOSE.
  4. On the last trading day of an Indian FY (Apr-Mar), pay capital-gains tax from cash.
  5. On a rebalance day, compute next session's orders from today's close.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import Settings
from .costs import TaxState, financial_year, fy_tax, trade_charges
from .strategy import compute_signals, rebalance_days, select_trades

STALE_DAYS = 10  # a holding with no price for this many sessions is liquidated (suspension/delisting)


@dataclass
class Position:
    qty: int
    cost: float          # total rupees paid incl. charges
    entry_date: pd.Timestamp
    stt_paid: float = 0.0  # STT is not deductible when computing capital gains
    stop_price: float = 0.0


@dataclass
class BacktestResult:
    equity: pd.Series                     # daily net-of-everything portfolio value
    trades: pd.DataFrame                  # one row per completed round trip
    taxes: pd.Series                      # tax paid per FY
    charges_paid: float
    exposure: pd.Series                   # fraction of equity invested each day
    settings: Settings
    notes: list = field(default_factory=list)


def run_backtest(panel: dict[str, pd.DataFrame], index_close: pd.Series | None,
                 settings: Settings, start: str | None = None, end: str | None = None) -> BacktestResult:
    cfg, sched, tax_cfg = settings.strategy, settings.charges, settings.tax
    sig = compute_signals(panel, index_close, cfg)

    opens, closes = panel["open"], panel["close"]
    lows = panel.get("low")
    lows = closes if lows is None or lows.empty else lows.reindex_like(closes)
    dates = closes.index
    if start:
        dates = dates[dates >= pd.Timestamp(start)]
    if end:
        dates = dates[dates <= pd.Timestamp(end)]
    rebal = rebalance_days(dates, cfg.rebalance)
    fy_last_day = set(pd.Series(dates, index=dates).groupby([financial_year(d) for d in dates]).max())

    cash = cfg.initial_capital
    positions: dict[str, Position] = {}
    pending_sells: list[str] = []
    pending_buys: list[tuple[str, float]] = []   # (symbol, target rupee value)
    pending_trims: list[tuple[str, float]] = []  # (symbol, target rupee value) for volatility-targeting trims
    last_close: dict[str, float] = {}
    last_seen: dict[str, pd.Timestamp] = {}
    stopped_until: dict[str, int] = {}           # symbol -> day index before which re-entry is blocked
    realized: dict[int, list[float]] = {}        # FY -> [st_net, lt_net]
    tax_state = TaxState()
    trades, taxes = [], {}
    charges_total = 0.0
    equity_curve, exposure = [], []

    def close_position(sym, price, day, reason, qty=None):
        """Sell `qty` shares (default: the whole position) and book the realised gain."""
        nonlocal cash, charges_total
        pos = positions[sym]
        qty = pos.qty if qty is None or qty >= pos.qty else qty
        frac = qty / pos.qty
        cost, stt_paid = pos.cost * frac, pos.stt_paid * frac
        if qty == pos.qty:
            positions.pop(sym)
        else:
            pos.qty -= qty
            pos.cost -= cost
            pos.stt_paid -= stt_paid
        value = qty * price
        fee = trade_charges("sell", value, sched)
        cash += value - fee
        charges_total += fee
        pnl = value - fee - cost
        taxable = pnl + stt_paid + value * sched.stt_pct
        held = (day - pos.entry_date).days
        bucket = realized.setdefault(financial_year(day), [0.0, 0.0])
        bucket[1 if held > tax_cfg.long_term_days else 0] += taxable
        trades.append({"symbol": sym, "entry_date": pos.entry_date, "exit_date": day,
                       "qty": qty, "cost": cost, "proceeds": value - fee,
                       "pnl": pnl, "return": pnl / cost, "days_held": held, "reason": reason})

    for i, day in enumerate(dates):
        day_open, day_low, day_close = opens.loc[day], lows.loc[day], closes.loc[day]
        if cash > 0 and cfg.cash_yield:
            cash *= 1 + cfg.cash_yield / 252

        # 1. Execute pending orders at the open: sells first, then buys with freed cash.
        still_pending = []
        for sym in pending_sells:
            px = day_open.get(sym, np.nan)
            if sym not in positions:
                continue
            if np.isnan(px):
                still_pending.append(sym)   # halted today; try again next session
                continue
            close_position(sym, px * (1 - cfg.slippage_pct), day, "signal")
        pending_sells = still_pending

        for sym, target in pending_trims:
            px = day_open.get(sym, np.nan)
            if sym not in positions or np.isnan(px):
                continue
            fill = px * (1 - cfg.slippage_pct)
            excess = positions[sym].qty - int(target // fill)
            if excess > 0:
                close_position(sym, fill, day, "trim", qty=excess)
        pending_trims = []

        for sym, target in pending_buys:
            px = day_open.get(sym, np.nan)
            if np.isnan(px) or sym in positions:
                continue
            fill = px * (1 + cfg.slippage_pct)
            budget = min(target, cash)
            qty = int(budget // (fill * (1 + sched.stt_pct + sched.stamp_pct + 0.0001)))
            if qty <= 0:
                continue
            value = qty * fill
            fee = trade_charges("buy", value, sched)
            if value + fee > cash:
                continue
            cash -= value + fee
            charges_total += fee
            stop = fill * (1 - cfg.stop_loss_pct) if cfg.stop_loss_pct else 0.0
            positions[sym] = Position(qty=qty, cost=value + fee, entry_date=day,
                                     stt_paid=value * sched.stt_pct, stop_price=stop)
        pending_buys = []

        # 2. Stop-losses.
        for sym in list(positions):
            stop = positions[sym].stop_price
            low = day_low.get(sym, np.nan)
            if stop and not np.isnan(low) and low <= stop:
                px = min(day_open.get(sym, stop), stop)
                close_position(sym, px * (1 - cfg.slippage_pct), day, "stop-loss")
                stopped_until[sym] = i + cfg.reentry_cooldown_days

        # 3. Mark to market (carry last price through missing bars) and liquidate stale names.
        for sym in list(positions):
            px = day_close.get(sym, np.nan)
            if not np.isnan(px):
                last_close[sym], last_seen[sym] = px, day
            elif sym in last_seen and dates.get_loc(day) - dates.get_loc(last_seen[sym]) >= STALE_DAYS:
                close_position(sym, last_close[sym] * 0.9, day, "stale-data")  # 10% haircut
        invested = sum(p.qty * last_close.get(s, p.cost / p.qty) for s, p in positions.items())

        # 4. Pay tax at FY end.
        if day in fy_last_day:
            fy = financial_year(day)
            st_net, lt_net = realized.pop(fy, [0.0, 0.0])
            tax = fy_tax(st_net, lt_net, fy, tax_state, tax_cfg)
            if tax > 0:
                cash -= tax  # may briefly go negative if fully invested; repaid by the next sells
                taxes[fy] = tax

        equity = cash + invested
        equity_curve.append(equity)
        exposure.append(invested / equity if equity > 0 else 0.0)

        # 5. Rebalance: decide orders for the next session.
        if day in rebal and i + 1 < len(dates):
            sells, buys = select_trades(day, set(positions), sig, cfg)
            pending_sells = sorted(set(pending_sells) | set(sells))
            cap = 1.0 if sig.exposure_cap is None else float(sig.exposure_cap.loc[day])
            target = equity * cap / cfg.num_positions
            pending_buys = [(s, target) for s in buys if stopped_until.get(s, -1) <= i]
            if sig.exposure_cap is not None:
                pending_trims = [(s, target) for s, p in positions.items()
                                 if s not in sells and p.qty * last_close.get(s, 0) > target * (1 + cfg.trim_tolerance)]

    # Settle tax on the final partial FY so the result is truly post-tax.
    if realized:
        for fy, (st_net, lt_net) in sorted(realized.items()):
            tax = fy_tax(st_net, lt_net, fy, tax_state, tax_cfg)
            if tax > 0:
                taxes[fy] = taxes.get(fy, 0.0) + tax
                equity_curve[-1] -= tax

    notes = []
    if positions:
        notes.append(f"{len(positions)} positions still open at end; valued at last close, unrealised gains untaxed.")
    return BacktestResult(
        equity=pd.Series(equity_curve, index=dates, name="equity"),
        trades=pd.DataFrame(trades),
        taxes=pd.Series(taxes, name="tax", dtype=float),
        charges_paid=charges_total,
        exposure=pd.Series(exposure, index=dates, name="exposure"),
        settings=settings,
        notes=notes,
    )
