# NSE Equity Momentum Agent (delivery only, no F&O)

A rule-based **swing/positional momentum** system for NSE cash equities, with a realistic
backtester that deducts Zerodha-style delivery charges, slippage and Indian capital-gains
tax, then reports what "Rs 500–1000 a day" really looks like for the resulting return stream.

## Quick start

```bash
pip install -r momentum_agent/requirements.txt
python -m momentum_agent.cli backtest --years 10 --capital 1000000      # downloads from Yahoo, caches CSVs
python -m momentum_agent.cli backtest --csv-dir my_data/                  # or use your own <SYMBOL>.csv files
python -m momentum_agent.cli signals --capital 1000000 --holdings holdings.csv   # this week's orders
python -m pytest momentum_agent/tests -q
```

Useful knobs: `--positions 10 --exit-rank 25 --rebalance W|M --skip-days 21 --no-regime`.
Everything else lives in `config.py`.

## The strategy (one strategy, chosen on purpose)

Cross-sectional, risk-adjusted momentum — the approach behind the NSE **Nifty200 Momentum 30**
index, Andreas Clenow's *Stocks on the Move*, and decades of academic evidence
(Jegadeesh & Titman 1993; momentum works in Indian equities too).

| Step | Rule |
|---|---|
| Universe | ~180 liquid NSE large/mid caps (`universe.py`), price ≥ Rs 50, 20-day median turnover ≥ Rs 5 cr |
| Score | `0.5·z(6M return / 1Y vol) + 0.5·z(12M return / 1Y vol)`, cross-sectional z-scores |
| Entry | Top-10 rank, stock above its 200-DMA, no >15% single-day move in 90 days |
| Regime filter | No new buys while Nifty 50 is below its 200-DMA (existing positions run) |
| Exit | Rank falls below 25 (buffer cuts churn) **or** stock closes below its 200-DMA |
| Sizing | Equal weight: equity / 10 per slot, whole shares |
| Schedule | Signals on Friday close, orders at Monday open (no look-ahead) |
| Product | CNC/delivery only. No intraday, no F&O, no leverage |

## Research: what top momentum traders actually agree on

1. **Rank, don't predict.** Buy the strongest stocks relative to the rest; don't guess tops.
   (Clenow, O'Neil's relative strength, NSE momentum indices.)
2. **Risk-adjust momentum.** Return ÷ volatility prefers smooth trends over lottery-ticket spikes,
   and avoids one-day gap stories (hence the gap filter).
3. **Trade with the market tide.** Momentum crashes happen after bear markets
   (Daniel & Moskowitz 2016). An index 200-DMA filter is the simplest defence.
4. **Cut losers, let winners run.** Exits are rule-based (rank/trend), not profit targets.
   Expect a ~35–45% win rate with winners several times larger than losers.
5. **Control turnover.** A rank buffer (buy top 10, sell below 25) keeps most of the edge
   while cutting costs. Weekly checks, not daily.
6. **Position sizing and diversification beat entry tricks.** 10+ names, equal or
   volatility-weighted, no single stock above ~10–12%.
7. **Process over P&L.** Minervini/Clenow/Weinstein all stress the same thing: follow the
   rules through drawdowns — most retail failure is abandoning the system after a bad quarter.

## Challenges to the original brief (please read)

**1. "Rs 500–1000 every day" is the wrong target for this (or any honest) strategy.**
Momentum returns are lumpy: most of a year's profit comes from a handful of weeks, and you
will regularly have months that are negative. The report prints the *distribution* of daily
P&L so you can see this. Treat the goal as **Rs 1.25–2.5 lakh per year net** (≈ 250 trading days).
A daily target creates pressure to overtrade, which is the main way retail traders lose money
(SEBI's FY23 study: ~70% of intraday equity traders lost money).

**2. The capital required is the real question.** If the strategy nets ~15–20% a year after
tax, then Rs 500/day average needs roughly **Rs 6–8 lakh**, Rs 1000/day needs **Rs 12–17 lakh**.
With Rs 1–2 lakh, hitting Rs 500/day would need 60–125% annual returns — not realistic without
leverage, which is how accounts blow up. The backtest prints the exact capital needed.

**3. Expect deep drawdowns.** Indian momentum strategies have historically had 25–35%
drawdowns (2018 mid-cap crash, March 2020, 2024–25 correction). On Rs 10 lakh that means
watching Rs 3 lakh disappear on paper. Decide now whether you'd keep following the rules.

**4. Costs and tax are a big drag at this turnover.** Delivery round trip ≈ 0.24% statutory +
~0.2% slippage. Nearly all gains are STCG (20% + cess). Both are modelled; ignore any backtest
that doesn't.

**5. Backtest results will be optimistic.** The universe is today's list (survivorship bias —
names that collapsed are missing), Yahoo data has gaps, and fills at the open are idealised.
Mentally haircut backtested CAGR by 3–5 points. Better: supply point-in-time Nifty 200
constituents via `--universe-file`.

**6. Why not intraday?** Intraday equity has lower STT but needs a statistical edge measured in
basis points per trade against costs, slippage and HFT competition. A delivery momentum system
needs to be right only a few times a year, on big moves.

## Cost & tax model

* Charges (`config.ChargeSchedule`): brokerage 0, STT 0.1% buy+sell, NSE txn 0.00297%,
  SEBI Rs 10/cr, stamp duty 0.015% (buy), GST 18% on brokerage+exchange+SEBI, DP Rs 15.93/scrip/sell.
  Plus 0.10% slippage per side on the fill price.
* Tax (`config.TaxConfig`): STCG 15% → 20% and LTCG 10% (>1L) → 12.5% (>1.25L) from 23-Jul-2024,
  4% cess, LTCG exempt before FY2018-19, loss set-off and carry-forward, STT not deductible.
  Tax is paid out of the portfolio on the last trading day of each FY.
* Simplifications: the regime in force at FY end is applied to the whole FY; LTCG grandfathering
  is ignored; dividends are reinvested via adjusted prices and not taxed separately; idle cash
  earns nothing (a liquid fund would add ~6% on the uninvested portion).

## Files

| File | Purpose |
|---|---|
| `config.py` | strategy, charges and tax parameters |
| `universe.py` | default symbol list / loader |
| `data.py` | Yahoo download with CSV cache, or load your own CSVs |
| `strategy.py` | momentum score, filters, regime, trade selection |
| `backtest.py` | daily event-driven engine (next-open fills, charges, FY tax) |
| `report.py` | metrics + "daily income" reality check |
| `cli.py` | `backtest` and `signals` commands |

## Roadmap (scale-up path)

1. Run the 10-year backtest; do a parameter sensitivity sweep (positions 8/10/15, weekly vs
   monthly, skip 0/21) — pick a robust *region*, not the single best number.
2. Walk-forward test on the last 2 years held out.
3. Paper-trade the `signals` output for 2–3 months.
4. Go live with a fraction of capital; automate orders via Kite Connect (GTT/AMO).
5. Add a Claude-powered weekly review: summarise signals, flag news/corporate actions on
   holdings, and check rule adherence. Claude explains and audits; the rules decide.

*Not investment advice. Past performance does not guarantee future results.*
