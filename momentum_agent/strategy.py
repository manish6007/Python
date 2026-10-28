"""Momentum ranking and trade-selection rules.

Score (modelled on the NSE Nifty200 Momentum 30 methodology):
    ratio_L = (L-day price return) / (annualised volatility of daily returns)
    z_L     = cross-sectional z-score of ratio_L across eligible stocks on that day
    score   = sum(weight_L * z_L)
Highest score = rank 1. All signals use data up to and including the signal day's close;
the backtester fills them at the NEXT day's open, so there is no look-ahead.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import StrategyConfig


@dataclass
class Signals:
    score: pd.DataFrame      # momentum score, NaN when not rankable
    rank: pd.DataFrame       # 1 = strongest
    buy_ok: pd.DataFrame     # bool, passes every entry filter
    below_ma: pd.DataFrame   # bool, close below trend MA (exit trigger)
    regime_on: pd.Series     # bool, index above its MA (new buys allowed)
    exposure_cap: pd.Series | None = None  # fraction of equity to invest (volatility targeting); None = 1.0


def _zscore_rows(df: pd.DataFrame) -> pd.DataFrame:
    mean = df.mean(axis=1)
    std = df.std(axis=1).replace(0, np.nan)
    return df.sub(mean, axis=0).div(std, axis=0)


def compute_signals(panel: dict[str, pd.DataFrame], index_close: pd.Series | None,
                    cfg: StrategyConfig) -> Signals:
    close, volume = panel["close"], panel["volume"]
    rets = close.pct_change(fill_method=None)

    min_obs = int(cfg.vol_window * 0.8)
    vol = rets.rolling(cfg.vol_window, min_periods=min_obs).std() * np.sqrt(252)
    trend_ma = close.rolling(cfg.trend_ma, min_periods=cfg.trend_ma).mean()
    turnover = (close * volume).rolling(20, min_periods=15).median()
    max_move = rets.abs().rolling(90, min_periods=60).max()

    has_history = close.notna() & close.shift(max(cfg.lookbacks) + cfg.skip_days).notna()
    tradable = has_history & (close >= cfg.min_price) & (turnover >= cfg.min_median_turnover)

    score = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    for lookback, weight in zip(cfg.lookbacks, cfg.lookback_weights):
        past_ret = close.shift(cfg.skip_days) / close.shift(cfg.skip_days + lookback) - 1
        ratio = (past_ret / vol).where(tradable)
        score += weight * _zscore_rows(ratio)
    if cfg.lowvol_weight:
        score += cfg.lowvol_weight * _zscore_rows((-vol).where(tradable))
    score = score.where(tradable)

    rank = score.rank(axis=1, ascending=False, method="first")
    below_ma = close < trend_ma
    buy_ok = tradable & score.notna() & ~below_ma & (max_move <= cfg.max_gap_pct)

    if cfg.use_regime_filter and index_close is not None:
        idx = index_close.reindex(close.index).ffill()
        regime_on = idx > idx.rolling(cfg.regime_ma, min_periods=cfg.regime_ma).mean()
    else:
        regime_on = pd.Series(True, index=close.index)

    exposure_cap = None
    if cfg.target_vol and index_close is not None:
        idx_rets = index_close.reindex(close.index).ffill().pct_change(fill_method=None)
        idx_vol = idx_rets.rolling(63, min_periods=40).std() * np.sqrt(252)
        exposure_cap = (cfg.target_vol / idx_vol).clip(upper=1.0).fillna(1.0)

    return Signals(score=score, rank=rank, buy_ok=buy_ok, below_ma=below_ma, regime_on=regime_on,
                   exposure_cap=exposure_cap)


def rebalance_days(index: pd.DatetimeIndex, freq: str) -> set:
    """Last trading day of each week/month: signals are computed on its close."""
    s = pd.Series(index, index=index)
    key = index.to_period("W" if freq == "W" else "M")
    return set(s.groupby(key).max())


def select_trades(day, holdings: set, sig: Signals, cfg: StrategyConfig) -> tuple[list, list]:
    """Decide (sells, buys) for a rebalance day. Buys are ordered best-first."""
    rank = sig.rank.loc[day]
    below = sig.below_ma.loc[day]
    if cfg.regime_exit and not bool(sig.regime_on.loc[day]):
        return sorted(holdings), []
    sells = []
    for sym in holdings:
        r = rank.get(sym, np.nan)
        if np.isnan(r) or r > cfg.exit_rank or (cfg.exit_below_ma and bool(below.get(sym, False))):
            sells.append(sym)

    buys = []
    slots = cfg.num_positions - (len(holdings) - len(sells))
    if slots > 0 and bool(sig.regime_on.loc[day]):
        ok = sig.buy_ok.loc[day]
        candidates = rank[ok & rank.notna()].sort_values()
        for sym in candidates.index:
            if sym in holdings:
                continue
            if candidates[sym] > cfg.num_positions:
                break  # only enter genuine top-N names, never "best of the rest"
            buys.append(sym)
            if len(buys) == slots:
                break
    return sells, buys
