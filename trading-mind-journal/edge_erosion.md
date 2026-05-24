## Edge Erosion — Mindset & Management

Every setup has a lifecycle. It has a **launch phase** (edge is strong, market hasn't adapted), a **maturity phase** (
edge stabilizes, you scale it), and a **decay phase** (edge erodes, you manage it down). Most traders only notice
they're in decay phase 6 months after it started — because cumulative PnL masks it until it's obvious.

The goal of this section is to catch decay early, respond systematically, and always have the next setup ready before
you need it.

---

### 1. Monitor rolling expectancy, not just yearly stats

Yearly aggregates are too coarse. A setup can silently deteriorate across 60 trades within a year and the annual report
will still look acceptable.

**What to track instead:**

- **20-trade rolling expectancy** — short-term signal quality. Sensitive to recent market behavior.
- **50-trade rolling expectancy** — medium-term baseline. Smooths out variance.

The warning sign is when the 20-trade rolling expectancy consistently dips below the 50-trade average. That divergence
is the early signal — not the annual summary.

> **CRB example:** Win rate dropped from 59% (2022) → 43% (2023) → 37% (2024) → 29% (2025) in a straight line. A rolling
> expectancy monitor would have flagged this drift by mid-2023. The yearly view made it visible only in hindsight.

---

### 2. Separate signal quality from execution drift

Before concluding a setup is broken, verify your entry criteria haven't drifted.

Pull a sample of trades from the setup's best year and compare them chart-by-chart against recent trades. Ask:

- Is the compression zone tighter or looser than it used to be?
- Are you taking B-grade versions of the setup alongside A-grade ones?
- Has your definition of "breakout" widened over time?

Filter creep is common — you started taking marginal setups alongside clean ones because you needed the activity. That
alone can drop win rate by 10–15% without the underlying edge changing at all.

---

### 3. Let position size respond to expectancy

When expectancy declines, size should scale down in proportion. This is non-negotiable.
A setup with 0.2R expectancy and full position sizing bleeds capital slowly enough to feel fine — until it doesn't.
Reduced size keeps you in the game while the setup either recovers or confirms it's broken.

---

### 4. Always have a setup in observation mode

New setup discovery should be a continuous background process, not a scramble triggered by breakdown.

At any point, maintain at least one setup in **observation mode** — paper tracking or minimal live size — so that by the
time a primary setup deteriorates, you already have 3–6 months of live data behind the candidate. Trading a new setup
under pressure, with no prior data, is how you compound one problem into two.

The observation pipeline:

1. **Hypothesis** — identify a pattern with a plausible structural reason to work
2. **Backtest** — validate across multiple years and market regimes
3. **Paper / minimal size** — 50–100 live trades, track every metric
4. **Promotion** — move to full size only when expectancy and profit factor are confirmed live

---

### 5. Watch how price moves, not just whether the setup works

This is the deeper skill. A setup is a bet on a specific price behavior following a specific condition. When the setup
stops working, ask what price is *actually* doing now in that condition — not just whether your trade made money.

For a breakout setup specifically:

- Are breakouts getting follow-through, or getting faded within the same candle?
- Is volume confirming the move, or is the breakout happening on thin participation?
- Has the typical post-breakout behaviour changes compared to prior years?

Sometimes the setup pattern is still valid but the directional bet has flipped. A compression zone that used to resolve
as a breakout may now resolve as a mean-reversion. Same entry condition, opposite trade.

---

### 6. Set a hard suspension threshold

Define in advance the metric level at which you formally suspend a setup — before you're emotionally attached to a bad
run.

A reasonable rule:

> *If the 20-trade rolling expectancy reaches 0.2R or below, the setup is suspended. Risk budget is reallocated to the
highest-expectancy active setup until the suspended setup shows recovery over a minimum of 30 forward trades at reduced
size.*

Writing this down before the situation arises removes the decision from the moment. Sunk cost and recency bias make
in-the-moment suspension decisions unreliable.

---

### Summary

| Principle                          | Practical action                                    |
|------------------------------------|-----------------------------------------------------|
| Treat setups as having a lifecycle | Expect decay; don't be surprised by it              |
| Monitor rolling expectancy         | 20-trade and 50-trade windows, tracked continuously |
| Check for filter creep             | Compare recent trades vs. best-year trades visually |
| Size to expectancy                 | Scale down as edge weakens                          |
| Keep a candidate in observation    | Always 1–2 setups in the pipeline                   |
| Watch price behavior, not just P&L | Understand *why* the setup is failing               |
| Pre-define suspension rules        | Remove the decision from the emotional moment       |
