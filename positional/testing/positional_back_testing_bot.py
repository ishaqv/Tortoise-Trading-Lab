import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta

import pandas as pd

from positional.scanner.positional_w1_breakout_scanner_bot import (
    add_technical_indicators, analyze_stock_for_setup, get_position_size,
)
from util.global_variables import (
    TRADING_CAPITAL, MAX_RISK_PER_TRADE_PERCENT,
    LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH, POSITIONAL_CANDLE_LIMIT,
)
from util.kite_util import get_kite
from util.shariah_stock_filter import get_symbol_instrument_token
from util.trade_logger import initialize_logger
from util.trade_type import TradeType

# ---------------- CONFIG ----------------
DATA_FOLDER = "data/week"
REPORT_FOLDER = "reports"
BACKTEST_YEARS = 10  # delete data/week/*.csv if you change this
DAYS_PER_CHUNK = 2000  # Kite's max span for the day interval

TARGET_R = 5.0
HOLDING_PERIOD_WEEKS = 25
MAX_ENTRY_GAP_ATR = 1.0  # skip if next week opens more than 1 ATR above signal close
entry_slippage_bp = 5
stop_slippage_bp = 4

R = TRADING_CAPITAL * MAX_RISK_PER_TRADE_PERCENT


# ---------------- COSTS ----------------
def calculate_round_trip_cost(entry_price, exit_price, quantity):
    """Delivery costs: STT both legs, exchange, SEBI, stamp (buy), GST, flat DP charge."""
    buy, sell = entry_price * quantity, exit_price * quantity
    turnover = buy + sell
    stt = turnover * 0.001
    exchange = turnover * 0.0000345
    sebi = turnover * 0.000001
    stamp = buy * 0.00015
    gst = exchange * 0.18
    dp_charge = 15.34
    return stt + exchange + sebi + stamp + gst + dp_charge


# ---------------- DATA ----------------
def naive(series):
    """Drop timezone info so all dates compare cleanly."""
    return pd.to_datetime(series).dt.tz_localize(None).dt.normalize()


def get_file_path(symbol):
    os.makedirs(DATA_FOLDER, exist_ok=True)
    return os.path.join(DATA_FOLDER, f"NSE_{symbol}.csv")


def fetch_back_testing_data(symbol, instrument_token):
    """Download daily candles from Kite and build Monday-start weekly candles
    (Kite's own weekly interval doesn't match Kite Chart)."""
    kite = get_kite()
    end_date = datetime.today()
    start_date = end_date - timedelta(days=365 * BACKTEST_YEARS)

    rows, to_date = [], end_date
    try:
        while to_date > start_date:
            from_date = max(to_date - timedelta(days=DAYS_PER_CHUNK), start_date)
            time.sleep(1)
            data = kite.historical_data(instrument_token, from_date, to_date, "day")
            if data:
                rows.extend(data)
            to_date = from_date - timedelta(days=1)

        if not rows:
            print(f"No data for {symbol}")
            return False

        daily = pd.DataFrame(rows).rename(columns={"date": "trade_date"})
        daily["trade_date"] = naive(daily["trade_date"])
        daily = daily.drop_duplicates("trade_date").sort_values("trade_date")
        daily["week"] = daily["trade_date"] - pd.to_timedelta(daily["trade_date"].dt.weekday, unit="D")

        weekly = daily.groupby("week", as_index=False).agg(
            open=("open", "first"), high=("high", "max"), low=("low", "min"),
            close=("close", "last"), volume=("volume", "sum"), days=("trade_date", "count"),
        ).rename(columns={"week": "trade_date"})

        # Drop the unfinished current week and holiday-broken weeks (<3 trading days)
        today = pd.Timestamp.today().normalize()
        this_week = today - pd.Timedelta(days=today.weekday())
        if today.weekday() >= 5:
            this_week += pd.Timedelta(days=7)
        weekly = weekly[(weekly["trade_date"] < this_week) & (weekly["days"] >= 3)]
        weekly.drop(columns="days").to_csv(get_file_path(symbol), index=False)
        return True

    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return False


# ---------------- SIMULATION ----------------
def process_symbol(symbol, instrument_token, lookup=50):
    initialize_logger(TradeType.POSITIONAL, "w1", True)

    file_path = get_file_path(symbol)
    if not os.path.isfile(file_path) or os.path.getsize(file_path) == 0:
        if not fetch_back_testing_data(symbol, instrument_token):
            return []

    df = pd.read_csv(file_path)
    df["trade_date"] = naive(df["trade_date"])
    df = df.drop_duplicates("trade_date").sort_values("trade_date").reset_index(drop=True)
    add_technical_indicators(df)

    n = len(df)
    results = []
    i = max(lookup, POSITIONAL_CANDLE_LIMIT - 1)

    # Signal is known at the CLOSE of week i. We buy at the OPEN of week i+1.
    while i < n - 1:
        signal = analyze_stock_for_setup(symbol, df.iloc[: i + 1], is_backtesting=True)
        if signal is None:
            i += 1
            continue

        e = i + 1
        entry_open = float(df.at[e, "open"])
        stop = signal["Stop"]

        # Gapped through the stop, or gapped too far up to chase: skip
        if entry_open <= stop or entry_open > signal["Signal Close"] + MAX_ENTRY_GAP_ATR * signal["ATR"]:
            i += 1
            continue

        entry = entry_open * (1 + entry_slippage_bp / 10000)
        risk = entry - stop
        qty = get_position_size(entry, risk)
        if qty <= 0:
            i += 1
            continue

        target = entry + TARGET_R * risk
        last = min(e + HOLDING_PERIOD_WEEKS - 1, n - 1)
        max_r = mae_r = 0.0
        reason = None

        for j in range(e, last + 1):
            c = df.iloc[j]
            high, low, opn = float(c["high"]), float(c["low"]), float(c["open"])
            max_r = max(max_r, (high - entry) / risk)
            mae_r = min(mae_r, (low - entry) / risk)

            if low <= stop:  # stop first if both hit in the same week
                exit_price = stop if j == e else min(opn, stop)  # gap down fills at the open
                reason = "STOP"
            elif high >= target:
                exit_price, reason = target, "TARGET"

            if reason:
                exit_idx = j
                break
        else:
            exit_idx = last
            exit_price = float(df.at[last, "close"])
            # Not enough data left for the full holding period = trade still open
            reason = "OPEN" if e + HOLDING_PERIOD_WEEKS - 1 > n - 1 else "TIME_EXIT"

        if reason == "STOP":
            exit_price *= 1 - stop_slippage_bp / 10000

        gross = (exit_price - entry) * qty
        cost = calculate_round_trip_cost(entry, exit_price, qty)
        pnl = gross - cost

        results.append({
            "Symbol": symbol,
            "Setup": signal["Setup"],
            "Entry Time": df.at[e, "trade_date"],
            "Exit Time": df.at[exit_idx, "trade_date"],
            "Entry Price": entry,
            "Exit Price": exit_price,
            "Stop Price": stop,
            "Target Price": target,
            "Risk Per Share": risk,
            "Position Size": qty,
            "Exit Reason": reason,
            "R": pnl / R,
            "R_Gross": gross / R,
            "PnL": pnl,
            "Cost": cost,
            "MAE_R": mae_r,
            "MaxR": max_r,
            "Duration_Days": (df.at[exit_idx, "trade_date"] - df.at[e, "trade_date"]).days,
        })

        i = exit_idx + 1  # no overlapping trades in the same symbol

    return results


# ---------------- REPORT ----------------
def print_key_metrics_table(df):
    wins, losses = df[df["R"] > 0], df[df["R"] < 0]
    gross_profit, gross_loss = wins["PnL"].sum(), abs(losses["PnL"].sum())

    rows = [
        ("Total Trades", len(df)),
        ("Win Rate", f"{len(wins) / len(df):.1%}"),
        ("Avg Win / Avg Loss (R)", f"{wins['R'].mean():.2f} / {losses['R'].mean():.2f}"),
        ("Expectancy Gross (R)", f"{df['R_Gross'].mean():.2f}"),
        ("Expectancy Net (R)", f"{df['R'].mean():.2f}"),
        ("Profit Factor", f"{gross_profit / gross_loss:.2f}" if gross_loss else "inf"),
        ("Total R (Net)", f"{df['R'].sum():.2f}"),
        ("Total PnL (₹, net)", f"₹{df['PnL'].sum():,.0f}"),
        ("Max Drawdown (R)", f"{df['DD_R'].min():.2f}"),
        ("Max Drawdown (%)", f"{df['Drawdown_%'].min():.2f}%"),
        ("Avg MFE / MAE (R)", f"{df['MaxR'].mean():.2f} / {df['MAE_R'].mean():.2f}"),
        ("Avg Duration (days)", f"{df['Duration_Days'].mean():.0f}"),
        ("Total Costs (₹)", f"₹{df['Cost'].sum():,.0f}"),
    ]
    table = pd.DataFrame(rows, columns=["Metric", "Value"])
    print("\n===== KEY METRICS (POSITIONAL / WEEKLY) =====")
    print(table.to_string(index=False))

    by_year = df.groupby(df["Entry Time"].dt.year)["R"].agg(Trades="size", ExpectancyR="mean", TotalR="sum").round(2)
    by_exit = df.groupby("Exit Reason")["R"].agg(Trades="size", AvgR="mean", TotalR="sum").round(2)
    print("\n--- By year ---\n", by_year.to_string())
    print("\n--- By exit ---\n", by_exit.to_string())

    os.makedirs(REPORT_FOLDER, exist_ok=True)
    table.to_csv(os.path.join(REPORT_FOLDER, "key_metrics_summary.csv"), index=False)


def backtest_historical_data_parallel(symbols_dict, max_workers=8):
    all_results = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_symbol, s, t): s for s, t in symbols_dict.items()}
        for future in as_completed(futures):
            try:
                result = future.result()
                if result:
                    all_results.append(pd.DataFrame(result))
            except Exception as e:
                print(f"Error processing {futures[future]}: {e}")

    if not all_results:
        print("No trades found.")
        return

    df = pd.concat(all_results, ignore_index=True)
    open_count = (df["Exit Reason"] == "OPEN").sum()
    df = df[df["Exit Reason"] != "OPEN"]  # unfinished trades would distort results
    print(f"{open_count} still-open trades excluded.")

    df = df.sort_values("Exit Time").reset_index(drop=True)
    df["Equity_R"] = df["R"].cumsum()
    df["DD_R"] = df["Equity_R"] - df["Equity_R"].cummax()
    equity = df["PnL"].cumsum()
    df["Drawdown_%"] = (equity - equity.cummax()) / TRADING_CAPITAL * 100

    print_key_metrics_table(df)
    df.to_csv("positional_w1_backtest_results.csv", index=False)


if __name__ == "__main__":
    initialize_logger(TradeType.POSITIONAL, "w1", True)
    backtest_historical_data_parallel(get_symbol_instrument_token(LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH))
