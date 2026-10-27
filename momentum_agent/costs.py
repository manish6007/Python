"""Transaction charges and Indian capital-gains tax for equity delivery trades."""
from dataclasses import dataclass
from datetime import date

import pandas as pd

from .config import ChargeSchedule, TaxConfig


def trade_charges(side: str, value: float, sched: ChargeSchedule) -> float:
    """Statutory + broker charges in rupees for one delivery order of `value` rupees.

    Slippage is not included here; the backtester applies it to the fill price.
    """
    if value <= 0:
        return 0.0
    brokerage = value * sched.brokerage_pct
    if sched.brokerage_cap:
        brokerage = min(brokerage, sched.brokerage_cap)
    stt = value * sched.stt_pct
    exchange = value * sched.exchange_pct
    sebi = value * sched.sebi_pct
    gst = (brokerage + exchange + sebi) * sched.gst_pct
    stamp = value * sched.stamp_pct if side == "buy" else 0.0
    dp = sched.dp_charge_per_sell if side == "sell" else 0.0
    return brokerage + stt + exchange + sebi + gst + stamp + dp


def financial_year(d) -> int:
    """Indian FY label by its starting year: 15-Jan-2025 -> 2024 (FY 2024-25)."""
    d = pd.Timestamp(d)
    return d.year if d.month >= 4 else d.year - 1


@dataclass
class TaxState:
    st_loss_cf: float = 0.0   # short-term losses carried forward (offset ST or LT gains)
    lt_loss_cf: float = 0.0   # long-term losses carried forward (offset LT gains only)


def fy_tax(st_net: float, lt_net: float, fy_start_year: int, state: TaxState, cfg: TaxConfig) -> float:
    """Tax payable for one financial year given net short/long-term gains.

    Simplifications (documented in README): rates of the regime in force at FY end are
    applied to the whole FY; grandfathering of pre-2018 LTCG is ignored; loss carry-forward
    does not expire within the backtest window.
    """
    fy_end = pd.Timestamp(date(fy_start_year + 1, 3, 31))
    new_regime = fy_end >= pd.Timestamp(cfg.regime_change_date)
    stcg_rate = cfg.stcg_rate_new if new_regime else cfg.stcg_rate_old
    ltcg_rate = cfg.ltcg_rate_new if new_regime else cfg.ltcg_rate_old
    exemption = cfg.ltcg_exemption_new if new_regime else cfg.ltcg_exemption_old
    ltcg_taxable_era = fy_end >= pd.Timestamp(cfg.ltcg_start_date)

    if not ltcg_taxable_era:
        # LTCG exempt (and LT losses neither usable nor carried) before FY2018-19
        lt_net = 0.0

    # Current-year set-off: ST loss can absorb LT gains; LT loss cannot absorb ST gains.
    if st_net < 0 and lt_net > 0:
        used = min(-st_net, lt_net)
        lt_net -= used
        st_net += used

    # Carried-forward losses.
    if st_net > 0 and state.st_loss_cf > 0:
        used = min(st_net, state.st_loss_cf)
        st_net -= used
        state.st_loss_cf -= used
    if lt_net > 0 and state.lt_loss_cf > 0:
        used = min(lt_net, state.lt_loss_cf)
        lt_net -= used
        state.lt_loss_cf -= used
    if lt_net > 0 and state.st_loss_cf > 0:
        used = min(lt_net, state.st_loss_cf)
        lt_net -= used
        state.st_loss_cf -= used

    # Remaining losses roll forward.
    if st_net < 0:
        state.st_loss_cf += -st_net
        st_net = 0.0
    if lt_net < 0:
        state.lt_loss_cf += -lt_net
        lt_net = 0.0

    tax = st_net * stcg_rate + max(0.0, lt_net - exemption) * ltcg_rate
    return tax * (1 + cfg.cess)
