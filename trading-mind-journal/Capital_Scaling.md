## Capital Scaling & Trade Splitting

### The Problem

A single full-capital entry stops working once your capital crosses a threshold. Two things break:

1. **Market impact** — your order becomes large enough relative to the order book that you move the price against
   yourself before you're fully filled
2. **Opportunity cost** — with all capital locked in one trade, you miss other setups that appear during the session

This is not a discipline problem. It is a structural problem that requires a structural solution.

---

### The Threshold Rule

Before placing any trade, verify:

```
MIN_BREAKOUT_VOLUME = buying_power × 100
MAX_ORDER_SIZE      = breakout_candle_volume × 0.02  (2% participation cap)
```

- `buying_power` = capital allocated to this trade × leverage
- `breakout_candle_volume` = rupee volume of the specific breakout candle, not the day's total
- If the breakout candle volume is below `MIN_BREAKOUT_VOLUME`, **skip the trade**
- Your order must never exceed 2% of that candle's volume

This rule acts as an automatic liquidity filter. You cannot take a trade in a thin stock — the math blocks you before
you even look at the chart.

---

### Capital Split — Single Account, Multiple Entries

Once capital exceeds ~₹5L (with 5X leverage), split capital across two independent entries within the same account.

```
Total capital: ₹10L
├── Entry 1 (primary):   ₹5L  →  ₹22.5L buying power(with 4.5X leverage)
├── Entry 2 (secondary): ₹5L  →  ₹22.5L buying power(with 4.5X leverage)
```

**60/40 is the default split.** Equal split (₹5L / ₹5L) is acceptable when conviction is equal across both setups.

Each entry is managed independently — separate SL order, separate target, separate decision to exit. Treat them as if
they belong to two different traders sharing one terminal.

---

### Stock Selection Rules

Each entry must be in a **different stock from a different sector**. This is non-negotiable.

| Rule                    | Reason                                                                                 |
|-------------------------|----------------------------------------------------------------------------------------|
| Different stocks        | Avoids concentration in a single name                                                  |
| Different sectors       | A single macro event (RBI, FII flow, crude) cannot take out both trades simultaneously |
| Ensure enough liquidity | Ensures both entries comfortably clear the 2% participation rule                       |

**Invalid:** Entry 1 long HDFC Bank, Entry 2 long Kotak Mahindra — same sector, same risk  
**Valid:** Entry 1 long HDFC Bank (banking), Entry 2 long Infosys (IT)

---

### Risk Limits

Combined loss 2% of capital
*(Based on ₹10L capital, 50/50 split, 4.5X leverage)*
**Daily loss limit: ₹20,000 (2% of capital).** If both entries stop out, close all positions and stop trading for the
day.

---

### Pre-Trade Checklist

Before placing either entry:

- [ ] Entry 1 and Entry 2 are in **different sectors**
- [ ] Breakout candle volume ≥ 50× buying power allocated to that entry
- [ ] Order size ≤ 2% of that breakout candle's volume
- [ ] SL-M order placed immediately after entry fills
- [ ] Combined worst-case loss (both entries stopped) is within daily limit

---

### Why Not More Than Two Entries?

Managing more than 2 simultaneous intraday positions degrades execution quality — missed entries, misplaced stops,
premature exits under pressure. Two focused entries with full attention outperform five positions with divided
attention. Capital scaling is solved through **position sizing and sector diversification**, not through increasing the
number of concurrent trades.

---

### Capital Hard Cap — ₹10L

**₹10L is the maximum effective capital for this intraday strategy. Deploying more does not improve returns — it
actively degrades them.**

With 4.5X leverage, ₹10L already commands ₹45L buying power split across two entries of ₹22.5L each. At this size, the
2%
participation rule requires ₹11.25Cr breakout volume per entry — a threshold that comfortably fits the top 15–20 Nifty
50 stocks on any normal trading day. The strategy is already operating near the ceiling of what retail intraday
liquidity supports.

Beyond ₹10L, each rupee of additional capital creates diminishing returns:

**More capital does not mean more trades.** The number of entries stays at two. It does not mean larger positions
either — the participation rule caps order size regardless of capital. What it actually means is a shrinking universe of
qualifying stocks, fewer setups per session, and worse average fill quality on both entry and exit.

#### What to do with profits beyond ₹10L

Excess capital beyond the ₹10L trading allocation should not remain idle in the trading account where it creates
psychological pressure to deploy it. Route it elsewhere:

```
Trading P&L → hits ₹10L threshold
                    │
        ┌───────────┴───────────┐
        │                       │
  Keep ₹10L in          Move excess to
  trading account       separate appreciating assets 
                        (mutual funds, stocks, gold etc.)
```

This keeps the intraday strategy running at peak efficiency while compounding surplus capital through a different
instrument with different liquidity constraints.

#### Summary

> The edge in intraday trading is speed and selectivity. Both degrade as capital grows beyond the liquidity ceiling of
> your strategy. ₹10L is not a limitation — it is the optimal operating point for this framework on NSE.

---

### Capital Channelization — What to Do With Trading Profits

The intraday trading account is a **machine, not a savings account.** It runs at ₹10L permanently. Profits are not
reinvested into it — they are withdrawn monthly and routed systematically into a separate wealth-building stack.

No loans. No credit. No EMI. Every asset is acquired from accumulated surplus only.

---

#### The Two-Engine Model

```
Engine 1: Intraday Trading
├── Capital: ₹10L (permanent, never grows)
├── Output: monthly P&L withdrawal
└── Job: generate consistent cash flow

Engine 2: Wealth Stack
├── Funded entirely by Engine 1 surplus
├── No capital ceiling — compounds indefinitely
└── Job: build long-term wealth and fund life goals
```

These two engines run in parallel and never mix. A bad month in Engine 1 does not touch Engine 2. A good month in Engine
1 does not get redeployed back into trading.

---

#### Priority Order for Monthly Surplus

Every rupee of trading profit flows through this sequence in order:

```
Monthly P&L withdrawal
        │
        ▼
① Emergency fund full?
  └── No  → fill it first (target: 6 months of expenses)
  └── Yes → move to next
        │
        ▼
② Living expenses covered?
  └── No  → cover them
  └── Yes → move to next
        │
        ▼
③ SIP — Nifty 50 / Flexicap index fund (60–70% of surplus)
        │
        ▼
④ Gold — Gold ETF (10–15% of surplus)
        │
        ▼
⑤ Goal corpus — liquid fund tagged to specific target
   (car fund, property fund, etc.)
```

---

#### Building Towards Large Purchases — No Loan Model

| Goal                    | Target corpus | Monthly allocation                  | Approx timeline |
|-------------------------|---------------|-------------------------------------|-----------------|
| Car (₹15–20L)           | ₹18L          | ₹8–10K/month in liquid fund         | 18–24 months    |
| Home (₹50–80L)          | ₹65L          | ₹20K/month in index fund @ 12% CAGR | 10–12 years     |
| Early retirement corpus | ₹2–3Cr        | ₹25K/month in index fund @ 12% CAGR | 15–18 years     |

Each goal gets its own tagged allocation. They do not compete with each other — they are funded sequentially as surplus
grows.

---

#### Why Not Grow the Trading Account Instead?

This is the most common mistake — reinvesting profits back into the trading account hoping to compound returns. It does
not work for this strategy because:

- Beyond ₹10L, the qualifying stock universe shrinks and edge degrades
- More capital does not produce proportionally more trades or better setups
- The strategy's return is bounded by market liquidity, not by capital size

Compounding happens in Engine 2 — index funds have no liquidity ceiling for a passive holder. The intraday strategy
generates the fuel. Index funds do the compounding.

---

#### The Mental Separation

| Trading account                   | Wealth stack                     |
|-----------------------------------|----------------------------------|
| ₹10L — fixed forever              | Grows every month                |
| High attention, active            | Zero attention, automatic SIP    |
| Daily P&L matters                 | Daily NAV is irrelevant          |
| Withdraw profits monthly          | Never withdraw — let it compound |
| Measured in daily/monthly returns | Measured in years and decades    |

> Treat the trading account like a business and the wealth stack like a pension. The business pays you. The pension is
> untouchable until the goal is reached.
