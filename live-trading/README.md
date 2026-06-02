## Expectancy Tracking

Track strategy performance using **expectancy**, not just win rate.

A strategy with a lower win rate can still outperform if the average winner is significantly larger than the average
loser.

### Formula

```text
Expectancy_R = (WinRate × AvgWin_R) - ((1 - WinRate) × AvgLoss_R)
```

Where:

* `WinRate` → Percentage of winning trades
* `AvgWin_R` → Average reward from winning trades (in R)
* `AvgLoss_R` → Average loss from losing trades (in R)

---

## Live Tracking Sheet

Track all setup statistics, expectancy, drawdowns, and performance metrics here:

[Expectancy Tracking Google Sheet](https://docs.google.com/spreadsheets/d/10WRBuktABYwAD0QQYfSim0K6ubuYza9dsZYush0jgZU/edit?usp=sharing)

---

## Why Expectancy Matters

Win rate alone is misleading.

| Win Rate | Avg Win | Avg Loss | Expectancy |
|----------|---------|----------|------------|
| 80%      | 0.5R    | 2R       | Negative   |
| 40%      | 3R      | 1R       | Positive   |

The second system is superior despite the lower accuracy.

---

## Expectancy Interpretation

| Expectancy (R) | Meaning          |
|----------------|------------------|
| `< 0`          | Losing system    |
| `0 – 0.2`      | Weak edge        |
| `0.2 – 0.5`    | Tradable edge    |
| `0.5 – 1.0`    | Strong edge      |
| `> 1.0`        | Exceptional edge |

---

## Metrics Tracked

The tracker records:

* Total trades
* Win rate
* Average win (R)
* Average loss (R)
* Total R
* Profit factor
* Max drawdown
* Net PnL
* Expectancy per trade

---

## Example

| Setup | Trades | WinRate | AvgWin_R | AvgLoss_R | Expectancy_R |
|-------|--------|---------|----------|-----------|--------------|
| EVB   | 758    | 44%     | 3.0      | -1.0      | 0.8          |

Interpretation:

* Average trade expectancy = `+0.8R`
* Over 100 trades, expected outcome ≈ `+80R`
* Profitability comes from reward asymmetry, not prediction accuracy

---

## Core Principle

Long-term profitability comes from:

* Controlled downside
* Positive expectancy
* Consistent execution
* Avoiding large drawdowns

A trader does not need a high win rate to compound capital effectively.
