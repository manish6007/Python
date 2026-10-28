"""All tunable parameters in one place. Change these, not the engine."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class StrategyConfig:
    # --- Portfolio ---
    initial_capital: float = 550_000.0     # Rs 5.5 lakh
    num_positions: int = 10                # hold the top-N ranked stocks, equal weight
    exit_rank: int = 25                    # rank buffer: only sell a holding once it drops below this rank

    # --- Ranking (Nifty200 Momentum 30 style: return / volatility, 6M + 12M blend) ---
    lookbacks: tuple = (126, 252)          # ~6 and ~12 months of trading days
    lookback_weights: tuple = (0.5, 0.5)
    vol_window: int = 252                  # volatility of daily returns used to risk-adjust momentum
    skip_days: int = 0                     # skip the most recent N days (21 = classic "12-1" momentum)
    lowvol_weight: float = 0.0             # extra weight on z(-volatility): >0 tilts toward calmer stocks (Alpha-LowVol style)

    # --- Filters ---
    trend_ma: int = 200                    # stock must close above its own 200-DMA to be bought
    exit_below_ma: bool = True             # also sell a holding when it closes below its trend MA on a rebalance day
    min_price: float = 50.0                # avoid penny stocks
    min_median_turnover: float = 5e7       # median daily traded value over 20 days >= Rs 5 crore
    max_gap_pct: float = 0.15              # ignore stocks with a >15% single-day move in the last 90 days (gappy / event-driven)

    # --- Risk ---
    stop_loss_pct: float = 0.10            # hard stop 10% below entry fill (a GTT sell order at Zerodha); None = off
    reentry_cooldown_days: int = 20        # after a stop-out, skip that stock for ~1 month to avoid whipsaws
    target_vol: float | None = None        # volatility targeting: invest min(1, target_vol / Nifty 63-day vol) of equity; None = off
    trim_tolerance: float = 0.25           # with target_vol, trim a holding only when it is >25% above its target value

    # --- Market regime filter ---
    use_regime_filter: bool = True         # no NEW buys when the index is below its 200-DMA
    regime_ma: int = 200
    regime_exit: bool = False              # also SELL everything on a rebalance day when the regime is off

    # --- Idle cash ---
    cash_yield: float = 0.0                # post-tax annual yield on uninvested cash (e.g. parked in a liquid ETF)

    # --- Schedule ---
    rebalance: str = "W"                   # "W" weekly (first trading day of week) or "M" monthly

    # --- Execution ---
    slippage_pct: float = 0.001            # 0.10% adverse fill on each side (impact + spread)


@dataclass(frozen=True)
class ChargeSchedule:
    """Zerodha-style equity DELIVERY charges (verified Oct 2026; re-check zerodha.com/charges)."""
    brokerage_pct: float = 0.0             # delivery brokerage is zero at Zerodha
    brokerage_cap: float = 0.0             # flat cap per order (e.g. 20 for brokers that charge delivery)
    stt_pct: float = 0.001                 # 0.1% on buy AND sell for delivery
    exchange_pct: float = 0.0000297        # NSE transaction charge
    sebi_pct: float = 0.000001             # Rs 10 per crore
    stamp_pct: float = 0.00015             # 0.015% on buy only
    gst_pct: float = 0.18                  # on brokerage + exchange + SEBI fees
    dp_charge_per_sell: float = 15.93      # CDSL Rs 13.50 + 18% GST, per scrip per sell day


@dataclass(frozen=True)
class TaxConfig:
    """Indian capital gains on listed equity (STT paid). Rates by date of sale."""
    stcg_rate_old: float = 0.15            # sales before 23-Jul-2024
    stcg_rate_new: float = 0.20            # sales on/after 23-Jul-2024
    ltcg_rate_old: float = 0.10
    ltcg_rate_new: float = 0.125
    ltcg_exemption_old: float = 100_000.0
    ltcg_exemption_new: float = 125_000.0
    cess: float = 0.04                     # health & education cess on the tax
    regime_change_date: str = "2024-07-23"
    ltcg_start_date: str = "2018-04-01"    # LTCG on listed equity was tax-free before FY2018-19
    long_term_days: int = 365              # held > 12 months => long term


@dataclass(frozen=True)
class Settings:
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    charges: ChargeSchedule = field(default_factory=ChargeSchedule)
    tax: TaxConfig = field(default_factory=TaxConfig)
    index_symbol: str = "^NSEI"            # Nifty 50, used for regime filter + benchmark
