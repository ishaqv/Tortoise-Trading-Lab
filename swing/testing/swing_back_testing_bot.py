import csv
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta

import pandas as pd

from swing.scanner.swing_breakout_scanner_bot import analyze_stock_for_setup, add_technical_indicators
from util.global_variables import SWING_TARGET_MULTIPLIER, SWING_CANDLE_LIMIT, BREAKOUT_CANDLE_IDX, \
    MASTER_SHARIAH_SYMBOL_FILE_PATH, MASTER_SHARIAH_SYMBOL_TOKEN_FILE_PATH
from util.kite_util import get_kite_object
from util.shariah_stock_filter import get_filtered_nse_shariah_stocks_with_instrument_token
from util.trade_logger import initialize_logger
from util.trade_type import TradeType

# ---------------- CONFIG ----------------
INTERVAL = "day"
DAYS = 200  # Max allowed per Kite API
DATA_FOLDER = f"data/{INTERVAL}"


def fetch_back_testing_data(symbol, instrument_token, period_days=3650):
    """
        Fetches ~5 years of historical OHLCV data for a given stock symbol using the Kite API.
        Loops until ~period_days worth of data is fetched (default: 1825 days = 5 years).
    """
    kite = get_kite_object()
    to_date = datetime.today()
    ohlcv_data_list = []
    total_days_fetched = 0

    try:
        while total_days_fetched < period_days:
            # Fetch in chunks
            chunk_days = min(DAYS, period_days - total_days_fetched)
            from_date = to_date - timedelta(days=chunk_days)

            print(f"Fetching {INTERVAL} data for {symbol} from {from_date.date()} to {to_date.date()}")
            time.sleep(1)  # avoid rate limits

            ohlcv_data = kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval=INTERVAL,
                continuous=False
            )

            if not ohlcv_data:
                print("No data returned for this chunk.")
                break
            else:
                ohlcv_data_list.extend(list(ohlcv_data))

            total_days_fetched += chunk_days
            to_date = from_date - timedelta(days=1)

        # Convert to DataFrame
        df = pd.DataFrame(ohlcv_data_list)

        # Dedupe and sort
        df.drop_duplicates(subset=['date'], inplace=True)
        df.sort_values('date', inplace=True)
        df.reset_index(drop=True, inplace=True)

        # Save to CSV
        file_path = get_file_path(symbol)
        df.to_csv(file_path, index=False)
        trading_days = len(df)
        print(f"Saved {trading_days} days of historic data ({symbol}) to {file_path}")

    except Exception as e:
        print(f"Error fetching data: {e}")


def process_symbol(symbol, instrument_token, holding_days=32):
    """
    Swing backtesting with realistic execution:

    1. Entry must trigger within ENTRY_VALID_DAYS
    2. If price hits SL after entry → Loss
    3. If price hits target after entry → Win
    4. If holding_days end without SL/Target → Breakeven
    5. If entry never triggers → SKIP TRADE

    Logs MaxR achieved AFTER entry.
    """

    entry_candle_limit = 10  # Entry must trigger within this window (5 days)
    entry_candle_count = 0
    initialize_logger(TradeType.SWING, "d1", log_to_console=True)

    file_path = get_file_path(symbol)
    if not os.path.isfile(file_path) or os.path.getsize(file_path) == 0:
        fetch_back_testing_data(symbol, instrument_token)

    df = pd.read_csv(file_path)
    df.columns = df.columns.str.strip()
    df['date'] = pd.to_datetime(df['date'])
    df['day'] = df['date'].dt.date

    add_technical_indicators(df)

    results = []

    for idx in range(SWING_CANDLE_LIMIT, len(df)):
        atr_value = df.at[idx, 'atr']
        if pd.isna(atr_value) or atr_value == 0.0:
            continue

        df_slice = df.iloc[idx - SWING_CANDLE_LIMIT:idx + 1]
        result = analyze_stock_for_setup(
            symbol, df_slice, is_backtesting=True
        )
        if result is None:
            continue

        # Future candles after breakout
        df_future = df[df['date'] > df_slice.iloc[BREAKOUT_CANDLE_IDX]['date']]
        df_post_entry = df_future.iloc[:holding_days]

        if df_post_entry.empty:
            continue

        entry_price = result.get("Entry")
        risk = result.get("Risk")
        position_size = result["Qty"]

        if not entry_price or not risk or risk == 0:
            continue

        stop_loss = entry_price - risk
        target = entry_price + SWING_TARGET_MULTIPLIER * risk

        entry_filled = False
        entry_time = None

        exit_price = exit_time = pnl_r = trade_status = None
        max_r = float("-inf")

        for row in df_post_entry.itertuples():
            high, low, dt = row.high, row.low, row.date

            # ⏳ Entry window control
            if not entry_filled:
                entry_candle_count += 1
                if entry_candle_count > entry_candle_limit:
                    break

                # ✅ Limit entry fill
                if low <= entry_price <= high:
                    entry_filled = True
                    entry_time = dt
                else:
                    continue

            # 📈 MaxR only AFTER entry
            intraday_r = (high - entry_price) / risk
            max_r = max(max_r, intraday_r)

            # 🛑 Stop Loss
            if low <= stop_loss:
                exit_price = stop_loss
                pnl_r = -1
                trade_status = "Loss"
                exit_time = dt
                break

            # 🎯 Target
            if high >= target:
                exit_price = target
                pnl_r = SWING_TARGET_MULTIPLIER
                trade_status = "Win"
                exit_time = dt
                break

        # ❌ Entry never triggered → SKIP TRADE
        if not entry_filled:
            continue

        # ⏳ Entry happened but no SL/Target → Breakeven
        if trade_status is None:
            last_row = df_post_entry.iloc[-1]

            exit_price = last_row.close
            pnl_r = (exit_price - entry_price) / risk

            trade_status = "Win" if pnl_r > 0 else "Loss"
            exit_time = last_row.date

        result.update({
            "Entry Time": entry_time,
            "Exit Time": exit_time,
            "Exit": round(exit_price, 1),
            "R:R": pnl_r,
            "MaxR": round(max_r, 2),
            "Status": trade_status,
            "HoldingDays": holding_days,
            "Profit Amount": round(pnl_r * risk * position_size, 2) if pnl_r > 0 else 0,
            "Loss Amount": round(abs(pnl_r * risk * position_size), 2) if pnl_r < 0 else 0
        })

        results.append(result)

    return results


def backtest_historical_data_parallel(symbols_dict, max_workers=8):
    """

    Setup  Trades  WinRate(%)  AvgWin(R)  AvgLoss(R)  Expectancy(R)  AvgWin(₹)  AvgLoss(₹)  Expectancy(₹)  MaxLosingStreak(Days)
    CRB      66       43.94       2.52       -0.99           0.55      63043       24739          13832                      6
    VEB      42       33.33       2.55       -0.97           0.20      63679       24101           5156                     10

    """


    all_results = []

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_symbol, sym, token): sym
            for sym, token in symbols_dict.items()
        }

        for future in as_completed(futures):
            result = future.result()
            if result:
                all_results.append(pd.DataFrame(result))

    if not all_results:
        print("No trades found.")
        return

    final_result_df = pd.concat(all_results, ignore_index=True)

    # Save raw trades
    file_path = "swing_backtest_results.csv"
    final_result_df.replace('\n', '', regex=True).to_csv(
        file_path,
        index=False,
        quoting=csv.QUOTE_NONE,
        escapechar='\\'
    )

    # =========================
    # OVERALL METRICS
    # =========================
    wins = final_result_df[final_result_df["Status"] == "Win"]
    losses = final_result_df[final_result_df["Status"] == "Loss"]

    total_trades = len(final_result_df)

    overall_win_rate = round(len(wins) / total_trades * 100, 2)
    loss_rate = 100 - overall_win_rate

    overall_avg_win_r = round(wins["R:R"].mean(), 2) if not wins.empty else 0
    overall_avg_loss_r = round(losses["R:R"].mean(), 2) if not losses.empty else 0

    overall_expectancy_r = round(
        (overall_win_rate/100 * overall_avg_win_r) +
        (loss_rate/100 * overall_avg_loss_r), 2
    )

    overall_avg_profit_amt = round(wins["Profit Amount"].mean()) if not wins.empty else 0
    overall_avg_loss_amt = round(losses["Loss Amount"].mean()) if not losses.empty else 0

    overall_expectancy_rupees = round(
        (overall_win_rate/100 * overall_avg_profit_amt) -
        (loss_rate/100 * overall_avg_loss_amt)
    )

    print(f"\n------ Overall Strategy Expectancy ------")
    print(f"Total Trades       : {total_trades}")
    print(f"Win Rate           : {overall_win_rate:.2f}%")
    print(f"Avg Win (R)        : {overall_avg_win_r}")
    print(f"Avg Loss (R)       : {overall_avg_loss_r}")
    print(f"Expectancy (R)     : {overall_expectancy_r}")
    print(f"Avg Profit Amount  : ₹{overall_avg_profit_amt}")
    print(f"Avg Loss Amount    : ₹{overall_avg_loss_amt}")
    print(f"Expectancy (₹)     : ₹{overall_expectancy_rupees}")
    print("----------------------------------------\n")

    # =========================
    # SETUP-WISE METRICS
    # =========================
    setup_stats = []

    final_result_df["TradeDate"] = pd.to_datetime(
        final_result_df["Entry Time"]
    ).dt.date

    for setup, group in final_result_df.groupby("Setup"):

        group = group.sort_values("TradeDate")

        wins = group[group["Status"] == "Win"]
        losses = group[group["Status"] == "Loss"]

        trades = len(group)

        win_rate = round(len(wins) / trades * 100, 2)
        loss_rate = 100 - win_rate

        avg_win_r = round(wins["R:R"].mean(), 2)
        avg_loss_r = round(losses["R:R"].mean(), 2)

        expectancy_r = round(
            (win_rate/100 * avg_win_r) +
            (loss_rate/100 * avg_loss_r), 2
        )

        avg_win_amt = round(wins["Profit Amount"].mean())
        avg_loss_amt = round(losses["Loss Amount"].mean())

        expectancy_rupees = round(
            (win_rate/100 * avg_win_amt) -
            (loss_rate/100 * avg_loss_amt)
        )

        # =====================
        # MAX LOSING STREAK (DAYS)
        # =====================
        day_results = (
            group.groupby("TradeDate")["Status"]
            .apply(lambda x: "Win" if "Win" in x.values else "Loss")
            .reset_index()
        )

        max_losing_streak = 0
        current_streak = 0

        for status in day_results["Status"]:
            if status == "Loss":
                current_streak += 1
                max_losing_streak = max(max_losing_streak, current_streak)
            else:
                current_streak = 0

        setup_stats.append({
            "Setup": setup,
            "Trades": trades,
            "WinRate(%)": win_rate,
            "AvgWin(R)": avg_win_r,
            "AvgLoss(R)": avg_loss_r,
            "Expectancy(R)": expectancy_r,
            "AvgWin(₹)": avg_win_amt,
            "AvgLoss(₹)": avg_loss_amt,
            "Expectancy(₹)": expectancy_rupees,
            "MaxLosingStreak(Days)": max_losing_streak
        })

    setup_df = pd.DataFrame(setup_stats)
    setup_df.to_csv("setup_expectancy_summary.csv", index=False)

    print("\n------ Setup-wise Performance ------")
    print(setup_df.to_string(index=False))


def get_file_path(symbol):
    """Returns the file path for CSV data for a symbol."""
    os.makedirs(DATA_FOLDER, exist_ok=True)
    return os.path.join(DATA_FOLDER, f"NSE_{symbol}_{INTERVAL}.csv")


if __name__ == "__main__":
    initialize_logger(TradeType.SWING, "d1", log_to_console=True)
    shariah_compliant_stock_dict = get_filtered_nse_shariah_stocks_with_instrument_token(
        MASTER_SHARIAH_SYMBOL_FILE_PATH, MASTER_SHARIAH_SYMBOL_TOKEN_FILE_PATH)
    backtest_historical_data_parallel(shariah_compliant_stock_dict)