# Intraday Breakout Trade Setup Detection

This script analyzes **5-minute intraday candlestick data** to evaluate breakout setups for a given stock. It applies
**price-action and volume-based filters**, and any setup that passes those checks is sent as a
**trade alert via Telegram**.

The scanner **cannot evaluate higher-level context**—such as sector trend, higher-timeframe trend, or nearby supply
zones—so those must be reviewed **manually before taking any trade**.

## Pipeline Overview

The scanner runs as a three-phase daily pipeline, each phase triggered by a separate cron job.


---

## Phase 1 — Warmup

**Schedule:** `9:05 AM` · Runs once daily

Initializes the trading session by authenticating with the broker and preparing all required runtime data.

### 🔧 Responsibilities

* Sends a **Telegram alert** with the login URL
  (`https://kite.zerodha.com/connect/login?v=3&api_key=YOUR_API_KEY`) for manual authentication
* Once authentication is completed, it proceeds to:

    * Fetch liquid symbols from the `d1_historical_data` table based on **Average Daily Volume (ADV)** and save them to
      a
      CSV file
    * Resolve and cache **instrument tokens** for all tracked symbols

---

### 🔑 Manual Authentication (Required)

* Clicking the link from Telegram message starts the login flow for Kite Connect API
* This step **cannot be automated**
* On successful login:

    * A fresh **access token** is generated (valid for the trading day)
    * The token is **cached** in SecretManager for downstream processes

---

### ⚠️ Notes

* If authentication is not completed, all dependent processes will fail
* Ensure the login is completed **before market hours**

---

### Phase 2 — Scan

**Schedule:** `9:20 AM` · Runs once daily

Discovers and alerts potential trade setups.

- Loads cached tokens from Phase 1
- Pulls latest candle data from Kite and append to existing data from DB
- Evaluates setup conditions across all symbols
- Fires alerts for qualifying setups

---

### Phase 3 — Backfill

**Schedule:** `3:35 PM` and `3:45 PM` · Runs twice daily

Persists candle data to the database for next-day indicator computation.

- Fetches all candles from the last stored timestamp to the market close
- Appends new candles to the historical buffer
- Evicts oldest candles beyond the limit
- Runs at 3:35 PM as primary job; 3:45 PM as a safety retry

---

### Execution Order

```
09:05 AM  →  Warmup   (auth + token cache)
09:20 AM  →  Scan     (setup discovery + alerts)
03:35 PM  →  Backfill (candle data persistence)
03:45 PM  →  Backfill (retry / safety run)
```

See [`crontab`](crontab) for the full cron schedule.

---

## ✨ Chart Configuration

* **Entry Timeframe**: 5-minute
* **Indicators**: ATR(14) and Volume SMA 20

---

## ✅ Setup

### 🔹 Setup 1 - Explosive Volume Breakout

* Stock opens with explosive volume compared to average

  ![EVB.png](EVB.png)

#### 1. Strong Bullish Breakout Candle

* **Wide body**: Candle body ≥ 60% of total range
* **Small/No upper wick**: Upper wick < 25%

#### 2. Strong Volume

Volume ≥ 15x average volume(SMA 20 volume)

---

### 🔹 Setup 2 - Early Momentum (Top Gainers)

> **Note:** This is a complementary strategy.

#### Overview

This setup aims to capture early intraday momentum by focusing on the top gainers shortly after market open.

![top_gainers_nse_entry.png](top_gainers_nse_entry.png)

#### Time Window

Scan between **9:20 AM – 9:25 AM** at the start of the trading day. This window captures genuine early movers before the
opening volatility settles.

#### Steps

1. Open the NSE Top Gainers page:
   [https://www.nseindia.com/market-data/top-gainers-losers](https://www.nseindia.com/market-data/top-gainers-losers)

2. Choose an index:All Securities

3. Filtering logic:

* Sort by **traded value(price * volume)** in DESC
* Filter by **price change %** (2-6%)
* Select the **top 2–3 stocks**

4. Optional:

* Download the CSV file and perform filtering locally by
  runnning [top_gainers_scanner.py](intraday/scanner/m5/top_gainers_scanner.py).

#### Selection Filters

* Avoid stocks with **large gap-ups**
* Avoid stocks where **price has already extended significantly**

#### Goal

Identify a small set of liquid stocks showing early strength and attempt to capitalize on initial momentum moves.


---

### Disclaimer: No setup works forever. Markets evolve, and setups evolve with them. If you fail to adapt, your edge will gradually disappear. ###

The core mindset shift — treat every setup like a product with a lifecycle. It has a launch phase (edge is strong,
market hasn't adapted), a maturity phase (edge stabilizes, you scale it), and a decay phase (edge erodes, you manage it
down). Most traders only notice they're in decay phase 6 months after it started because they're looking at cumulative
PnL which masks it.

#### What actually helps:

Rolling expectancy windows — don't just track yearly stats. Run a 20-trade and 50-trade rolling expectancy for each
setup. The moment setup 20-trade rolling expectancy started dipping below its 50-trade average consistently, that was
the early warning.

#### Always have a setup in observation mode
New setup discovery should be a continuous background process, not a scramble triggered by breakdown.
At any point, maintain at least one setup in observation mode — paper tracking or minimal live size — so that by the
time a primary setup deteriorates, you already have 3–6 months of live data behind the candidate.
---

## 🧮 Position Size Calculator

Position size is calculated using the logic below.

```
  # Buying power (equity × leverage)
    buying_power = TRADING_CAPITAL * INTRADAY_LEVERAGE_MULTIPLIER
    
    # REAL risk (based on equity)
    risk_amount = TRADING_CAPITAL * MAX_RISK_PER_TRADE_PERCENT

    # Risk-based qty
    risk_based_qty = risk_amount / risk_per_share

    # Capital-based qty (using leverage)
    capital_based_qty = buying_power / entry_price

    tradable_qty = min(risk_based_qty, capital_based_qty)

    # Quantity is rounded to the nearest 5 for convenience.
    if tradable_qty > 5:
        tradable_qty = round(tradable_qty / 5.0) * 5
```
### How to Use

### 📎 [Open Position Size Calculator](https://docs.google.com/spreadsheets/d/1dgWrre2iDaxW4oJEYqlwa8DinsedHIv0Q6LEBiSpBtM/edit?usp=sharing)

Enter your **Trading Capital**, **Symbol**, and **ATR** to calculate the recommended **Quantity**, **Stop Loss**, and
**Target**.

> **Entry Price** is preferred. If left blank, the calculator will automatically fetch the symbol's **Day
High** via Google Finance and use it as the entry price.

```
⚠️ This is a shared read-only template. To use it, go to File → Make a copy to save your own version to Google Drive. All changes should be made in your personal copy.
🔗 If the link is unavailable, download the file directly from this repository and open it in Google Sheets.
``` 

---

## 🎯 Entry Strategy

* Entry: Place your buy order at the high of the confirmation candle, adding a small buffer of 0.25× ATR above it.
* Order Type: Use a SL-M (Stop-Loss Market) BUY order with market protection. This ensures your entry is fully filled
  even during fast price moves — unlike an SL-Limit order, which risks partial or missed fills when the market gaps or
  moves quickly.

![SL-M BUY.png](SL-M%20BUY.png)

``⚠️ SL-M orders can experience slippage during periods of low liquidity or high volatility. In such situations, your order may execute at a higher price significantly different from your intended entry price.``

---

## ❄️ Stop Loss (SL)

* SL: Entry - Risk (0.5× ATR)
* Order Type: Use a SL-M (Stop-Loss Market) SELL order with market protection. This ensures you exit cleanly even during
  fast price moves — unlike an SL-Limit order, which risks partial or missed exits when the market gaps or moves
  quickly.

> As trade progresses, shift SL to latest swing low + buffer. Avoid obvious SL zones known to attract stop hunts.


![SL-M SELL.png](SL-M%20SELL.png)

``⚠️ SL-M orders can experience slippage during periods of low liquidity or high volatility. In such situations, your order may execute at a lower price significantly different from your intended exit price.``

---

## 📈 Target Strategy

## 📈 Strategy 1 — Fixed Exit at 3R

* Target: Entry + 3R
* At 3R → Sell 100% of the position
* Best used when the trend lacks strong continuation momentum
* Simple and easy to execute with minimal supervision
* Order Type: Use a Limit SELL order

---

## 📈 Strategy 2 — Partial Exit + Dynamic Trailing

* Primary Target (T1): Entry + 3R
* At 3R → Sell 50% of the position
* Move the SL to breakeven after partial profit booking
* Trail the remaining position below each new swing low to capture extended moves
* Final Target (T2): Exit when T2 is reached, the trailing SL is hit, or the move shows signs of exhaustion.
* Requires active supervision and disciplined trade management
* Order Type: Use a Limit SELL order

### ⚠️ Important

```
No strategy is perfect. Some trades will reverse after hitting T1, reducing the profit on the remaining position. Other
trades will continue trending strongly and reach T2, resulting in significantly larger gains.
Choose the strategy that best fits your personality, risk tolerance, and trading style. You must be mentally prepared for both outcomes and avoid judging the strategy based on a few trades.
```

![LIMIT SELL.png](LIMIT%20SELL.png)

---

## 💰 Risk Management

* **Risk per trade**: < 2% of total capital
* **No revenge trading**
* **You will lose.** Your job is to **lose small, fast and smart** and **never let one trade ruin your day**.
* **SL is a validation stop**, not pain threshold.
* When the trade fails structurally, exit. Don’t wait for confirmation of failure.

### 📊 Strategy Performance Summary (EVB)

```Capital = 5L, Backtest Duration = 3 years```

### Fixed target = 3.5R

| Category              | Metric              | Value      |
|-----------------------|---------------------|------------|
| **Trade Stats**       | Total Trades        | 673        |
|                       | Win Rate            | 42%        |
|                       | Avg Win             | +3.5R      |
|                       | Avg Loss            | -1.0 R     |
|                       | Win/Loss Ratio      | 3.5        |
|                       | Expectancy          | **+0.9 R** |
|                       | Profit Factor       | 2.5        |
|                       | Sharpe (R)          | 0.4        |
|                       | Total Return        | 584 R      |
|                       | Total PnL           | ₹38 L      |
|                       | CAGR                | 64 %       |
|                       | Calmar Ratio        | 6.0        |
| **Risk**              | Max Drawdown        | -10 R      |
|                       | Max Drawdown (%)    | -10.6%     |
|                       | Max Losing Streak   | 10 trades  |
| **Execution Quality** | Avg MFE (Captured)  | +3.1 R     |
|                       | Avg MFE (Available) | +9.5 R     |
|                       | Capture Efficiency  | 47.4 %     |
|                       | Avg MAE             | -2.0 R     |
|                       | MAE > 0.5R          | 69% trades |
|                       | Avg Trade Duration  | 9.3 min    |

---

### Dynaic Target - 50% at 3.5R and 50% at 10R

| Category              | Metric              | Value      |
|-----------------------|---------------------|------------|
| **Trade Stats**       | Total Trades        | 663        |
|                       | Win Rate            | 42%        |
|                       | Avg Win             | +3.8 R     |
|                       | Avg Loss            | -1.0 R     |
|                       | Win/Loss Ratio      | 3.8        |
|                       | Expectancy          | **+1.0 R** |
|                       | Profit Factor       | 2.8        |
|                       | Sharpe (R)          | 0.4        |
|                       | Total Return        | 670 R      |
|                       | Total PnL           | ₹44.5L     |
|                       | CAGR                | 69 %       |
|                       | Calmar Ratio        | 6.3        |
| **Risk**              | Max Drawdown        | -10 R      |
|                       | Max Drawdown (%)    | -11%       |
|                       | Max Losing Streak   | 10 trades  |
| **Execution Quality** | Avg MFE (Captured)  | +4R        |
|                       | Avg MFE (Available) | +9.5 R     |
|                       | Capture Efficiency  | 53 %       |
|                       | Avg MAE             | -2.2 R     |
|                       | MAE > 0.5R          | 76% trades |
|                       | Avg Trade Duration  | 15 min     |

> **Disclaimer:** Backtesting assumes perfect trade execution, ideal fills, and zero slippage. It does not account for
> human errors, emotional decisions, execution delays, or real market conditions. Therefore, backtest results should not
> be blindly trusted and should only be treated as an indication of how the strategy performed historically.

#### You can be wrong 60% of the time and still make money, if your winners are bigger than your losers.A trader’s edge isn’t in how often they win, but in how little they lose.

![win_loss.png](win_loss.png)

---

#### Stay consistent. Follow the rules. Let the edge play out.
