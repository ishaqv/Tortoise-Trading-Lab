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

**Schedule:** `9:15 AM` · Runs once daily

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

**Schedule:** `3:35 PM` · Runs once daily

Persists candle data to the database for next-day indicator computation.

- Fetches all candles from the last stored timestamp to the market close
- Appends new candles to the historical buffer
- Evicts oldest candles beyond the limit

---

### Execution Order

```
09:15 AM  →  Warmup   (auth + token cache)
09:20 AM  →  Scan     (setup discovery + alerts)
03:35 PM  →  Backfill (candle data persistence)
```

See [`crontab`](crontab) for the full cron schedule.

---

## ✨ Chart Configuration

* **Entry Timeframe**: 5-minute
* **Indicators**: ATR(14) and Volume SMA 20

---

## ✅ Setup

### 🔹 Setup 1 - Explosive Volume Breakout (EVB)

* Stock opens with explosive volume compared to average

  ![EVB.png](EVB.png)

#### 1. Strong Bullish Breakout Candle

* **Wide body**: Candle body ≥ 60% of total range
* **Small/No upper wick**: Upper wick < 25%

#### 2. Strong Volume

Volume ≥ 15x average volume(SMA 20 volume)

---

### 🔹 Setup 2 — Early Momentum Breakout (EMB)

A stock exhibiting early momentum with tight liquidity conditions.

#### 1. Strong Bullish Breakout Candle

- Candle body spans at least 60% of the total candle range
- Upper wick is less than 25% of the total range

#### 2. Strong Participation

- `MAX_PARTICIPATION_RATE` < 0.5
- Price change between 2% and 6%

> Participation rate refers to the ratio of your order size relative to the volume traded during the breakout candle.

---

### 🔹 Setup 3 - Top Gainers

> **Note:** This is a complementary strategy.

#### Overview

This setup aims to capture early intraday momentum by focusing on the NSE top gainers shortly after market open.

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
  runnning [top_gainers_scanner.py](top_gainers_scanner.py).

> Alternatively, select an index (**NIFTY** or **NIFTY NEXT 50**) and apply the filters manually.

#### Selection Filters

* Avoid stocks with **large gap-ups**
* Avoid stocks where **price has already extended significantly**

#### Goal

Identify a small set of liquid stocks showing early strength and attempt to capitalize on initial momentum moves.


---

## 🔹 Setup 4 — Bull Trap Reversal (BTR)

**Concept:** Identifies stocks that initially showed bullish momentum but failed to sustain it, leading to a reversal.
This setup reuses the same candidates flagged by the Momentum Breakout scanner(from setup 1/2/3), but trades them in the
opposite direction — taking SHORT positions instead of LONG.

![BTR.png](BTR.png)

**Entry Criteria:**

- Wait for the confirmation candle's low to be broken.
- **Do not enter on the first break.** The first break is treated as a trigger only — not an entry.
- Allow price to retest the confirmation candle low level.
- Enter SHORT only when price breaks below this low a **second time**.

**Filter Condition:**

- The confirmation candle's low must be **below the VWAP** for the setup to be valid.

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

### 📎 [Open Position Size Calculator](https://docs.google.com/spreadsheets/d/17a6biT8HTaTvbsJVUkGBKKUIwe4mWcmqgWH95-mGx9c/edit?usp=sharing)

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
No strategy is perfect. Some trades will reverse after reaching T1, reducing the profit on the remaining position, while others will continue trending strongly and reach T2, resulting in significantly larger gains.

Choose the approach that best matches your personality, risk tolerance, and trading style. Whatever you choose, be mentally prepared for both outcomes and avoid judging the strategy based on just a few trades.

As a general guideline, consider using a partial exit strategy when you observe sustained buying demand—for example, multiple high-volume candles trading well above the average volume—as this can indicate a strong trend with the potential for further upside.
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

```Capital = 5L, Backtest Duration = 5 years```

#### Fixed target Backtest Performance

#### Key Metrics

| Metric                          |              Value |
|:--------------------------------|-------------------:|
| **Capital**                     |           ₹500,000 |
| **Risk Per Trade (1R)**         |            ₹12,500 |
| **Total Trades**                |              1,057 |
| **Wins / Losses / BE**          |      457 / 600 / 0 |
| **Win Rate**                    |          **43.2%** |
| **Average Win**                 |          **+1.8R** |
| **Average Win (Theoretical)**   |              +4.0R |
| **Average Loss**                |          **-0.7R** |
| **Average Loss (Theoretical)**  |              -1.0R |
| **Win/Loss Ratio**              |            **2.6** |
| **Expectancy**                  | **+0.4R (₹4,711)** |
| **Profit Factor**               |            **2.0** |
| **Best / Worst Trade**          |      +3.9R / -1.2R |
| **Gross Return**                |            +571.8R |
| **Net Return (After Costs)**    |            +398.4R |
| **Net Profit**                  |     **₹4,979,767** |
| **Max Drawdown**                |             -12.2R |
| **Max Drawdown (₹)**            |           ₹152,559 |
| **Max Drawdown (%)**            |           **8.8%** |
| **Max DD Duration**             |           134 Days |
| **Recovery Factor**             |           **32.6** |
| **Max Losing Streak**           |                 14 |
| **Max Winning Streak**          |                  6 |
| **Average Trade Duration**      |        9.2 Minutes |
| **Average MFE (Execution)**     |              +3.8R |
| **Average MFE (Full Day)**      |             +11.1R |
| **Capture Efficiency**          |          **48.8%** |
| **Average MAE**                 |              -2.1R |
| **Trades with MAE > 0.5R**      |              67.1% |
| **Average Trades / Month**      |               17.8 |
| **Rolling 20-Trade Expectancy** |              +0.3R |
| **Rolling 20-Trade Win Rate**   |              40.0% |

---

#### Trading Costs

| Metric                   |          Value |
|:-------------------------|---------------:|
| Brokerage & Taxes        |       ₹960,180 |
| Slippage Cost            |     ₹1,207,173 |
| **Total Trading Cost**   | **₹2,167,353** |
| **Average Cost / Trade** |     **₹2,050** |
| **Cost Drag**            |      **30.3%** |

---

#### Risk & Capital

| Metric                      |           Value |
|:----------------------------|----------------:|
| Risk Per Trade              | 2.5% of Capital |
| Leverage Constrained Trades |           96.7% |

---

#### Setup Performance

| Setup   | Trades | Win Rate | Avg Win | Avg Loss | Expectancy | Gross R |  Net R |    Net PnL | Profit Factor | Max DD |
|:--------|-------:|---------:|--------:|---------:|-----------:|--------:|-------:|-----------:|--------------:|-------:|
| **EMB** |    404 |    43.8% |   +2.1R |    -0.8R |      +0.5R |  257.0R | 191.3R | ₹2,391,156 |           2.0 | -12.9R |
| **EVB** |    653 |    42.9% |   +1.6R |    -0.6R |      +0.3R |  314.8R | 207.1R | ₹2,588,612 |           1.9 |  -7.6R |

---

#### Year-wise Performance

| Year | Setup | Trades | Win Rate | Expectancy | Net R |  Net PnL | Profit Factor |
|:----:|:-----:|-------:|---------:|-----------:|------:|---------:|--------------:|
| 2021 |  EMB  |     25 |    44.0% |      +0.5R | 12.0R | ₹149,544 |           2.0 |
| 2021 |  EVB  |     26 |    38.5% |      +0.1R |  3.1R |  ₹38,251 |           1.3 |
| 2022 |  EMB  |     33 |    42.4% |      +0.4R | 13.6R | ₹169,743 |           1.9 |
| 2022 |  EVB  |     67 |    41.8% |      +0.3R | 22.3R | ₹279,271 |           1.9 |
| 2023 |  EMB  |     43 |    39.5% |      +0.4R | 18.9R | ₹236,243 |           1.9 |
| 2023 |  EVB  |    120 |    45.8% |      +0.4R | 44.1R | ₹551,857 |           2.1 |
| 2024 |  EMB  |    119 |    40.3% |      +0.4R | 45.1R | ₹563,755 |           1.7 |
| 2024 |  EVB  |    186 |    39.2% |      +0.2R | 40.4R | ₹504,833 |           1.6 |
| 2025 |  EMB  |    104 |    47.1% |      +0.5R | 53.9R | ₹674,102 |           2.3 |
| 2025 |  EVB  |    154 |    46.1% |      +0.4R | 59.7R | ₹746,794 |           2.2 |
| 2026 |  EMB  |     80 |    47.5% |      +0.6R | 47.8R | ₹597,769 |           2.5 |
| 2026 |  EVB  |    100 |    43.0% |      +0.4R | 37.4R | ₹467,606 |           2.0 |

---

### Partial Exit Target - 50% at T1 and 50% at T2

### 📈 Backtest Performance Summary

#### Key Metrics

| Metric                          |              Value |
|:--------------------------------|-------------------:|
| **Capital**                     |           ₹500,000 |
| **Risk Per Trade (1R)**         |            ₹12,500 |
| **Total Trades**                |              1,057 |
| **Wins / Losses / BE**          |      457 / 600 / 0 |
| **Win Rate**                    |          **43.2%** |
| **Average Win**                 |          **+1.8R** |
| **Average Win (Theoretical)**   |              +4.2R |
| **Average Loss**                |          **-0.7R** |
| **Average Loss (Theoretical)**  |              -1.0R |
| **Win/Loss Ratio**              |            **2.7** |
| **Expectancy**                  | **+0.4R (₹5,010)** |
| **Profit Factor**               |            **2.0** |
| **Best / Worst Trade**          |      +5.9R / -1.2R |
| **Gross Return**                |            +616.0R |
| **Net Return (After Costs)**    |            +423.6R |
| **Net Profit**                  |     **₹5,295,111** |
| **Max Drawdown**                |             -14.3R |
| **Max Drawdown (₹)**            |           ₹178,352 |
| **Max Drawdown (%)**            |           **8.6%** |
| **Max DD Duration**             |           163 Days |
| **Recovery Factor**             |           **29.7** |
| **Max Losing Streak**           |                 14 |
| **Max Winning Streak**          |                  7 |
| **Average Trade Duration**      |       17.5 Minutes |
| **Average MFE (Execution)**     |              +4.6R |
| **Average MFE (Full Day)**      |             +11.1R |
| **Capture Efficiency**          |          **54.2%** |
| **Average MAE**                 |              -2.4R |
| **Trades with MAE > 0.5R**      |              77.0% |
| **Average Trades / Month**      |               17.8 |
| **Rolling 20-Trade Expectancy** |              +0.6R |
| **Rolling 20-Trade Win Rate**   |              40.0% |

---

#### Trading Costs

| Metric                   |          Value |
|:-------------------------|---------------:|
| Brokerage & Taxes        |       ₹960,502 |
| Slippage Cost            |     ₹1,444,291 |
| **Total Trading Cost**   | **₹2,404,793** |
| **Average Cost / Trade** |     **₹2,275** |
| **Cost Drag**            |      **31.2%** |

---

#### Target Performance

| Outcome          | Trades | % of Trades | Average R | Average Duration |
|:-----------------|-------:|------------:|----------:|-----------------:|
| **Hit T2**       |    248 |   **23.5%** |    +2.71R |         25.0 min |
| **Hit T1 Only**  |    204 |   **19.3%** |    +0.77R |         29.1 min |
| **Never Hit T1** |    605 |   **57.2%** |    -0.67R |         10.6 min |

---

#### Risk & Capital

| Metric                      |           Value |
|:----------------------------|----------------:|
| Risk Per Trade              | 2.5% of Capital |
| Leverage Constrained Trades |           96.7% |

---

#### Setup Performance

| Setup   | Trades | Win Rate | Avg Win | Avg Loss | Expectancy | Gross R |  Net R |    Net PnL | Profit Factor | Max DD |
|:--------|-------:|---------:|--------:|---------:|-----------:|--------:|-------:|-----------:|--------------:|-------:|
| **EMB** |    404 |    43.8% |   +2.2R |    -0.8R |      +0.5R |  282.3R | 209.6R | ₹2,619,429 |           2.1 | -12.2R |
| **EVB** |    653 |    42.9% |   +1.6R |    -0.6R |      +0.3R |  333.6R | 214.1R | ₹2,675,682 |           1.9 |  -8.4R |

---

#### Year-wise Performance

| Year | Setup | Trades | Win Rate | Expectancy | Net R |  Net PnL | Profit Factor |
|:----:|:-----:|-------:|---------:|-----------:|------:|---------:|--------------:|
| 2021 |  EMB  |     25 |    44.0% |      +0.7R | 17.9R | ₹223,273 |           2.4 |
| 2021 |  EVB  |     26 |    38.5% |      +0.1R |  3.4R |  ₹41,956 |           1.3 |
| 2022 |  EMB  |     33 |    42.4% |      +0.5R | 15.3R | ₹191,701 |           2.0 |
| 2022 |  EVB  |     67 |    41.8% |      +0.4R | 24.0R | ₹299,611 |           2.0 |
| 2023 |  EMB  |     43 |    39.5% |      +0.3R | 11.1R | ₹138,240 |           1.5 |
| 2023 |  EVB  |    120 |    45.8% |      +0.3R | 39.3R | ₹491,216 |           2.0 |
| 2024 |  EMB  |    119 |    40.3% |      +0.4R | 51.7R | ₹645,890 |           1.9 |
| 2024 |  EVB  |    186 |    39.2% |      +0.2R | 41.5R | ₹519,103 |           1.6 |
| 2025 |  EMB  |    104 |    47.1% |      +0.6R | 63.4R | ₹792,001 |           2.5 |
| 2025 |  EVB  |    154 |    46.1% |      +0.4R | 63.3R | ₹790,893 |           2.2 |
| 2026 |  EMB  |     80 |    47.5% |      +0.6R | 50.3R | ₹628,323 |           2.6 |
| 2026 |  EVB  |    100 |    43.0% |      +0.4R | 42.6R | ₹532,904 |           2.2 |

> **Disclaimer:** Backtesting assumes perfect trade execution, ideal fills, and decent slippage. It does not account for
> human errors, emotional decisions, execution delays, or real market conditions. Therefore, backtest results should not
> be blindly trusted and should only be treated as an indication of how the strategy performed historically.

#### You can be wrong 60% of the time and still make money, if your winners are bigger than your losers.A trader’s edge isn’t in how often they win, but in how little they lose.

![win_loss.png](win_loss.png)

---

#### Stay consistent. Follow the rules. Let the edge play out.
