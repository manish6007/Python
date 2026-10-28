# Layoff-Resilient Strategy: 60/20/20 Momentum + Gold + Debt

**Goal:** a system that grows while you are employed and can pay ₹15–30k a month if you are
laid off, without being wrecked by a bad first year. The question is not only "what makes the
most money" but "what survives a layoff that starts in the worst possible month".

All numbers come from `python -m momentum_agent.research` on 2010-01 → 2026-10 (16.8 years,
182 NSE stocks, Yahoo data). They are after Zerodha delivery charges, 0.1% slippage and
capital-gains tax, unless marked pre-tax. Reproduce with:

```bash
python -m momentum_agent.research --csv-dir data_cache_long --start 2010-01-01 --out research_out
```

## 1. The recommendation

| Sleeve | Weight | What to hold | Why |
|---|---|---|---|
| Momentum stocks | 60% | 10 stocks from `signals` (weekly, rules below) | Growth engine: ~22% CAGR alone |
| Gold | 20% | Gold ETF (e.g. GOLDBEES) | Rose in the years momentum fell: 2011 (+30% vs −9%), 2018 (+7% vs −6%), 2025 (+72% vs −17%), 2026 (+6% vs −9%) |
| Debt / cash | 20% | Arbitrage fund (better post-tax than debt funds at a 30% slab) or liquid fund | Stable source of money for withdrawals; dry powder |

**Rebalance at month-end** when any sleeve drifts more than 5 points (`cli allocate`).
Rebalancing automatically books momentum profits into gold/debt after strong runs and refills
momentum after crashes.

**Separately, outside this portfolio:** 3 months of expenses in a savings/sweep FD. That money
is for day 1 of a layoff; the portfolio funds month 4 onward.

### Momentum sleeve rules (unchanged engine, two setting changes)

- Universe ~180 liquid NSE large/mid caps; score = 6M + 12M return ÷ volatility (Nifty200 Momentum 30 style)
- Buy top 10 that are above their 200-DMA; sell when rank falls below 25 or below 200-DMA
- No new buys while Nifty 50 is below its 200-DMA
- **No fixed 10% stop-loss** (see §3): `--stop-loss 0`
- **Idle cash parked in a liquid ETF** (LIQUIDCASE/LIQUIDBEES) rather than left in the account

## 2. Results

| Portfolio | CAGR | Max drawdown | Worst year | Worst 3-yr CAGR | 2010–17 CAGR | 2018–26 CAGR |
|---|---|---|---|---|---|---|
| Nifty 50 (pre-tax, no costs) | 9.1% | −38.4% | −24.6% | −5.0% | 9.2% | 9.2% |
| Momentum alone, 10% stop (old default) | 20.1% | −38.1% | −20.4% | −0.7% | 18.0% | 22.2% |
| Momentum alone, no stop + cash yield | 22.7% | −34.7% | −17.4% | +1.3% | 21.1% | 24.4% |
| **60/20/20 mix (recommended)** | **17.2%** | **−18.9%** | **−3.2%** | **+4.1%** | **14.6%** | **19.6%** |
| 60/20/20 with 3%/yr haircut on momentum | 15.3% | −19.0% | −4.6% | — | — | — |
| 60/20/20 with 5%/yr haircut on momentum | 13.9% | −19.1% | — | — | — | — |

The mix gives up ~5% a year of return versus momentum alone, but **halves the drawdown and
turns a −17% worst year into −3%**. For a layoff fund that trade is the whole point: you never
want to be selling stocks at −35% to pay rent.

Mix yearly returns: 2011 +1%, 2012 +19%, 2013 +7%, 2014 +37%, 2015 +8%, 2016 +9%, 2017 +26%,
2018 −1%, 2019 +16%, 2020 +67%, 2021 +45%, 2022 +6%, 2023 +42%, 2024 +21%, 2025 +1%, 2026 −3%.

## 3. What was tested and rejected

| Idea | Result | Verdict |
|---|---|---|
| 10% hard stop | −1.7%/yr CAGR, *deeper* drawdown (−38% vs −35%); win rate 51%→39% in the 10-yr run | Rejected: sells normal dips in winners |
| 15% / 20% stops | Still worse than no stop | Rejected |
| Volatility targeting (Barroso/Santa-Clara style, 15% target) | −4.4%/yr CAGR, little DD benefit | Rejected for India: Nifty vol spikes are brief, so it sold near bottoms |
| Low-vol tilt / regime exit / more positions, *each alone* | Cut DD to −28…−31% at ~same CAGR | Good, but… |
| …*stacked together* | CAGR fell to 15–16% with DD only to −25% | Rejected: more rules, more churn (50–70 trades/yr) |
| Monthly instead of weekly | Similar CAGR, worse 2nd-half DD | Not worth changing |
| Skip last month (12-1 momentum) | Best CAGR (23.9%) but 653-day drawdown | Not adopted: likely overfit |

Rule of thumb from this: **diversify across assets, not across extra stock-picking rules.**

## 4. What this means for a layoff

Corpus needed so that a layoff starting in the **worst historical month** can be funded and the
portfolio still holds ≥60% of its value afterwards (so it recovers and can be reused):

| Monthly need | 12-month layoff | 24-month layoff |
|---|---|---|
| ₹15,000 | ₹6.0 L | ₹10.9 L |
| ₹30,000 | ₹12.0 L | ₹21.8 L |

(Momentum alone needs ₹14.6 L / ₹33.8 L for the ₹15k row: its crashes force selling low.)

**With ₹5.5 L today:** a 12-month ₹15k layoff starting in the worst month left ₹3.16 L, so it can
be funded, but it uses up a lot of the corpus. ₹30k a month is not fundable yet.

**Getting there** (projection at a conservative 13–15% CAGR):

| Monthly SIP | Reach ₹11 L | Reach ₹22 L |
|---|---|---|
| ₹20,000 | ~20 months | ~4 years |
| ₹40,000 | ~12 months | ~2.5 years |

**Living off it indefinitely** is a different question: Indian studies put the safe withdrawal
rate at ~3–3.5% a year (Raju & Saraogi, "Balancing Acts"). ₹30k/month forever needs roughly
₹1 Cr. This system is a **layoff bridge**, not early retirement, until the corpus is that size.

## 5. Routine

| When | What | Time |
|---|---|---|
| Friday evening | `signals --capital <momentum sleeve value> --stop-loss 0 --holdings holdings.csv` | 5 min |
| Monday 9:30–10:00 | Place sells, then buys (CNC limit orders) | 15 min |
| Month-end | `allocate --momentum X --gold Y --debt Z`; move money only if it says so; add SIP | 10 min |
| **Layoff mode** | `allocate ... --withdraw 15000` each month; it takes cash from whichever sleeves are over target | 10 min |

## 6. Honest caveats

1. **Survivorship bias.** The universe is *today's* large/mid caps; stocks that collapsed out of
   the index are under-represented. That inflates the momentum sleeve, probably by 2–5% a year,
   which is why the haircut rows exist. Plan on the 5% haircut numbers (~14% CAGR).
2. **Gold's 2nd half was exceptional** (18% CAGR 2018–26 vs 6% in 2010–17; +72% in 2025 alone,
   which is what kept the mix flat that year). Don't count on it repeating; it is there to
   hedge, not to earn.
3. **Backtest rebalanced the sleeves every month exactly;** the 5% band in `allocate` trades
   less and should do slightly better after costs, but this was not simulated.
4. **Recent momentum is weak:** 2025 and 2026 were flat to negative for the mix. A system
   like this has multi-year stretches of not much; the rules only work if you keep following them.
5. Debt sleeve modelled as 7% pre-tax at a 31.2% tax rate (4.8% net). Arbitrage funds should do
   a bit better; that upside is not counted.
6. Yahoo data has some bad prints (cleaned automatically; see `data._drop_glitches`) and
   demergers (VEDL 2026, ABFRL 2025) recorded as losses. That is conservative.
7. This is research, not investment advice. Paper trade it for 3 months before putting money in.
