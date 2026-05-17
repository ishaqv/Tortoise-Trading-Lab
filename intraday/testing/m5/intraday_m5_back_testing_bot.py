import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta

import matplotlib.pyplot as plt
import pandas as pd

from intraday.scanner.m5.intraday_m5_breakout_scanner_bot import analyze_stock_for_setup, add_technical_indicators
from util.entry_type import EntryType
from util.exit_model_util import ExitModel
from util.global_variables import INTRADAY_M5_CANDLE_SIZE, TRADING_CAPITAL, MAX_RISK_PER_TRADE_PERCENT, \
    INTRADAY_LEVERAGE_MULTIPLIER, \
    EVB_SCAN_CANDLE_TIME, LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH, INTRADAY_M5_TARGET_MULTIPLIER, INTRADAY_M5_CANDLE_LIMIT
from util.kite_util import get_kite
from util.shariah_stock_filter import get_symbol_instrument_token
from util.trade_logger import initialize_logger
from util.trade_type import TradeType

# ================= CONFIG =================
INTERVAL = "5minute"
DAYS = 100  # Max allowed per Kite API
DATA_FOLDER = f"data/{INTERVAL}"
REPORT_FOLDER = "reports"

# ─── Breakout windows ─────────────────────────────────────────────────────────
BREAKOUT_WINDOWS = [
    {
        "name": "EVB",
        "start": EVB_SCAN_CANDLE_TIME,
        "end": EVB_SCAN_CANDLE_TIME
    }
]


def get_file_path(symbol):
    """Returns the file path for CSV data for a symbol."""
    os.makedirs(DATA_FOLDER, exist_ok=True)
    return os.path.join(DATA_FOLDER, f"NSE_{symbol}.csv")


def fetch_back_testing_data(symbol, instrument_token, from_year=None, to_year=None, num_years=None):
    """
    Fetch historical OHLCV data. Two modes:
      - Specify from_year & to_year  → fetches that exact range  (e.g. from_year=2026, to_year=2026)
      - Specify num_years            → fetches last N years from today (e.g. num_years=10)
      - Neither specified            → defaults to last 10 years
    """
    kite = get_kite()
    to_day = datetime.today()
    # --- Resolve date range ---
    if from_year and to_year:
        start_date = datetime(from_year, 1, 1)
        end_date = datetime(to_year, 12, 31)
    elif num_years:
        end_date = to_day
        start_date = end_date - timedelta(days=365 * num_years)
    else:
        end_date = to_day
        start_date = end_date - timedelta(days=365 * 10)  # default: 10 years

    ohlcv_data_list = []

    if end_date > to_day:
        end_date = to_day

    to_date = end_date

    print(f"Fetching data for {symbol} | Range: {start_date.date()} → {end_date.date()}")

    try:
        while to_date > start_date:
            from_date = max(to_date - timedelta(days=DAYS), start_date)

            print(f"  Chunk: {from_date.date()} → {to_date.date()}")
            time.sleep(1)

            ohlcv_data = kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval=INTERVAL
            )

            if ohlcv_data:
                ohlcv_data_list.extend(ohlcv_data)
            else:
                print(f"  No data returned for this chunk, skipping...")

            to_date = from_date - timedelta(days=1)

        if not ohlcv_data_list:
            print(f"No data fetched for {symbol}.")
            return False

        # --- Build DataFrame ---
        df = pd.DataFrame(ohlcv_data_list)
        df.drop_duplicates(subset=['date'], inplace=True)
        df.sort_values('date', inplace=True)
        df.reset_index(drop=True, inplace=True)

        file_path = get_file_path(symbol)
        df.to_csv(file_path, index=False)
        print(f"Saved {len(df)} candles for {symbol} to {file_path}")
        return True

    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        return False


def compute_quantity(entry_price, risk_per_share):
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
    return tradable_qty


def process_symbol(
        symbol,
        instrument_token,
        exit_model=ExitModel.STATIC,
        partial_exit_pct=0.5,  # 0.5 = 50%, 0.3 = 30%
        final_target_r=10,
        atr_entry_buffer=0.1
):
    ENTRY_LOOKAHEAD_CANDLES = 5

    initialize_logger(
        TradeType.INTRADAY,
        f"m{INTRADAY_M5_CANDLE_SIZE}",
        log_to_console=True
    )

    file_path = get_file_path(symbol)

    if not os.path.isfile(file_path) or os.path.getsize(file_path) == 0:
        fetch_back_testing_data(symbol, instrument_token, 2023, 2026)

    df = pd.read_csv(file_path)

    df.columns = df.columns.str.strip()

    df['date'] = pd.to_datetime(df['date'])
    df['day'] = df['date'].dt.date

    add_technical_indicators(df)

    results = []

    day_groups = {d: g for d, g in df.groupby('day')}

    for trading_day, df_day in day_groups.items():

        for window in BREAKOUT_WINDOWS:

            mask = (
                    (df_day['date'].dt.time >= window["start"]) &
                    (df_day['date'].dt.time <= window["end"])
            )

            candidate_idxs = df_day[mask].index.tolist()

            if not candidate_idxs:
                continue

            for breakout_idx in candidate_idxs:

                breakout_pos = df.index.get_loc(breakout_idx)

                slice_start = max(
                    0,
                    breakout_pos - (INTRADAY_M5_CANDLE_LIMIT - 1)
                )

                df_slice = df.iloc[
                    slice_start: breakout_pos + 1
                ]

                if len(df_slice) < INTRADAY_M5_CANDLE_LIMIT:
                    continue

                atr_value = df.at[breakout_idx, 'atr']

                if pd.isna(atr_value) or atr_value == 0:
                    continue

                result = analyze_stock_for_setup(
                    symbol,
                    df_slice,
                    trading_day=trading_day,
                    is_backtesting=True
                )

                if result is None:
                    continue

                is_long = (
                        result["Entry Type"] ==
                        EntryType.LONG.name
                )

                df_trading_day_full = day_groups[trading_day]

                breakout_candle = df_slice.iloc[-1]

                breakout_time = breakout_candle['date']

                atr = breakout_candle["atr"]

                df_after_breakout = df_trading_day_full[
                    df_trading_day_full['date'] > breakout_time
                    ]

                if df_after_breakout.empty:
                    continue

                confirmation_candle = df_after_breakout.iloc[0]

                df_entry_window = df_after_breakout.iloc[
                    1:1 + ENTRY_LOOKAHEAD_CANDLES
                ]

                # ==========================================================
                # ENTRY TRIGGER
                # ==========================================================

                if is_long:

                    trigger_price = (
                            confirmation_candle["high"] +
                            atr_entry_buffer * atr
                    )

                else:

                    trigger_price = (
                            min(
                                confirmation_candle["low"],
                                breakout_candle["low"]
                            ) -
                            atr_entry_buffer * atr
                    )

                entry_filled = False

                for row in df_entry_window.itertuples():

                    if row.low <= trigger_price <= row.high:
                        entry_price = trigger_price

                        triggered_time = row.date

                        entry_index = (
                            df_trading_day_full.index.get_loc(
                                row.Index
                            )
                        )

                        entry_filled = True
                        break

                if not entry_filled:
                    continue

                df_post_entry = df_trading_day_full.iloc[
                    entry_index + 1:
                ]

                if df_post_entry.empty:
                    continue

                risk = result["Risk"]

                if risk <= 0:
                    continue

                qty = compute_quantity(entry_price, risk)

                # ==========================================================
                # STATIC EXIT LEVELS
                # ==========================================================

                if is_long:

                    stop_loss = entry_price - risk

                    static_target = (
                            entry_price +
                            INTRADAY_M5_TARGET_MULTIPLIER * risk
                    )

                else:

                    stop_loss = entry_price + risk

                    static_target = (
                            entry_price -
                            INTRADAY_M5_TARGET_MULTIPLIER * risk
                    )

                # ==========================================================
                # DYNAMIC TARGETS
                # ==========================================================

                if is_long:

                    partial_target = (
                            entry_price +
                            INTRADAY_M5_TARGET_MULTIPLIER * risk
                    )

                    final_target = (
                            entry_price +
                            final_target_r * risk
                    )

                else:

                    partial_target = (
                            entry_price -
                            INTRADAY_M5_TARGET_MULTIPLIER * risk
                    )

                    final_target = (
                            entry_price -
                            final_target_r * risk
                    )

                # ==========================================================
                # TRADE STATE
                # ==========================================================

                max_r_execution = 0
                max_r_full_day = 0
                mae_r = 0

                exit_price = None
                exit_time = None
                exit_index = None

                pnl_r = None
                trade_status = None

                # ==========================================================
                # DYNAMIC STATE VARIABLES
                # ==========================================================

                partial_booked = False

                booked_position = partial_exit_pct
                remaining_position = 1 - partial_exit_pct

                realized_r = 0

                trailing_stop = stop_loss

                # IMPORTANT:
                # trailing stop becomes active NEXT candle only
                pending_trailing_stop = None

                # ==========================================================
                # EXECUTION LOOP
                # ==========================================================

                for i, row in enumerate(df_post_entry.itertuples()):

                    high = row.high
                    low = row.low
                    close = row.close
                    dt = row.date

                    # ------------------------------------------------------
                    # ACTIVATE PENDING TRAILING STOP
                    # ------------------------------------------------------

                    if pending_trailing_stop is not None:
                        trailing_stop = pending_trailing_stop
                        pending_trailing_stop = None

                    # ------------------------------------------------------
                    # UPDATE MFE / MAE
                    # ------------------------------------------------------

                    if is_long:

                        max_r_execution = max(
                            max_r_execution,
                            (high - entry_price) / risk
                        )

                        mae_r = min(
                            mae_r,
                            (low - entry_price) / risk
                        )

                    else:

                        max_r_execution = max(
                            max_r_execution,
                            (entry_price - low) / risk
                        )

                        mae_r = min(
                            mae_r,
                            (entry_price - high) / risk
                        )

                    # ======================================================
                    # STATIC EXIT MODEL
                    # ======================================================

                    if exit_model == ExitModel.STATIC:

                        if is_long:

                            target_hit = (
                                    high >= static_target
                            )

                            stop_hit = (
                                    low <= stop_loss
                            )

                        else:

                            target_hit = (
                                    low <= static_target
                            )

                            stop_hit = (
                                    high >= stop_loss
                            )

                        # TARGET FIRST PRIORITY

                        if target_hit:

                            exit_price = static_target

                            pnl_r = (
                                INTRADAY_M5_TARGET_MULTIPLIER
                            )

                            trade_status = "Win"

                            exit_time = dt
                            exit_index = row.Index

                            break

                        elif stop_hit:

                            exit_price = stop_loss

                            pnl_r = -1

                            trade_status = "Loss"

                            exit_time = dt
                            exit_index = row.Index

                            break

                    # ======================================================
                    # DYNAMIC EXIT MODEL
                    # ======================================================

                    elif exit_model == ExitModel.DYNAMIC:

                        # --------------------------------------------------
                        # BEFORE PARTIAL EXIT
                        # --------------------------------------------------

                        if not partial_booked:

                            if is_long:

                                partial_hit = (
                                        high >= partial_target
                                )

                                stop_hit = (
                                        low <= stop_loss
                                )

                            else:

                                partial_hit = (
                                        low <= partial_target
                                )

                                stop_hit = (
                                        high >= stop_loss
                                )

                            # IMPORTANT:
                            # PRIORITIZE PARTIAL FIRST

                            if partial_hit:

                                partial_booked = True

                                realized_r += (
                                        booked_position *
                                        INTRADAY_M5_TARGET_MULTIPLIER
                                )

                                # Move to breakeven
                                # ACTIVE NEXT CANDLE
                                pending_trailing_stop = (
                                    entry_price
                                )

                            elif stop_hit:

                                exit_price = stop_loss

                                pnl_r = -1

                                trade_status = "Loss"

                                exit_time = dt
                                exit_index = row.Index

                                break

                        # --------------------------------------------------
                        # AFTER PARTIAL EXIT
                        # --------------------------------------------------

                        else:

                            # ----------------------------------------------
                            # SWING TRAILING
                            # ----------------------------------------------

                            if i >= 2:

                                prev_row = df_post_entry.iloc[i - 1]

                                if is_long:

                                    swing_low = prev_row["low"] - 0.1 * atr

                                    new_stop = max(
                                        trailing_stop,
                                        swing_low
                                    )

                                else:

                                    swing_high = prev_row["high"] + 0.1 * atr

                                    new_stop = min(
                                        trailing_stop,
                                        swing_high
                                    )

                                # ACTIVE NEXT CANDLE ONLY
                                pending_trailing_stop = new_stop

                            # ----------------------------------------------
                            # EXIT CHECKS
                            # ----------------------------------------------

                            if is_long:

                                final_target_hit = (
                                        high >= final_target
                                )

                                trailing_stop_hit = (
                                        low <= trailing_stop
                                )

                            else:

                                final_target_hit = (
                                        low <= final_target
                                )

                                trailing_stop_hit = (
                                        high >= trailing_stop
                                )

                            # TARGET FIRST PRIORITY

                            if final_target_hit:

                                realized_r += (
                                        remaining_position *
                                        final_target_r
                                )

                                pnl_r = realized_r

                                exit_price = final_target

                                trade_status = "Win"

                                exit_time = dt
                                exit_index = row.Index

                                break

                            elif trailing_stop_hit:

                                if is_long:

                                    trailing_r = (
                                            (trailing_stop - entry_price)
                                            / risk
                                    )

                                else:

                                    trailing_r = (
                                            (entry_price - trailing_stop)
                                            / risk
                                    )

                                realized_r += (
                                        remaining_position *
                                        trailing_r
                                )

                                pnl_r = realized_r

                                exit_price = trailing_stop

                                trade_status = (
                                    "Win"
                                    if pnl_r > 0
                                    else "Loss"
                                )

                                exit_time = dt
                                exit_index = row.Index

                                break

                # ==========================================================
                # EOD EXIT
                # ==========================================================

                if trade_status is None:

                    last_row = df_post_entry.iloc[-1]

                    final_close = last_row.close

                    if is_long:

                        final_r = (
                                (final_close - entry_price)
                                / risk
                        )

                        max_r_execution = max(
                            max_r_execution,
                            (
                                    last_row.high - entry_price
                            ) / risk
                        )

                        mae_r = min(
                            mae_r,
                            (
                                    last_row.low - entry_price
                            ) / risk
                        )

                    else:

                        final_r = (
                                (entry_price - final_close)
                                / risk
                        )

                        max_r_execution = max(
                            max_r_execution,
                            (
                                    entry_price - last_row.low
                            ) / risk
                        )

                        mae_r = min(
                            mae_r,
                            (
                                    entry_price - last_row.high
                            ) / risk
                        )

                    # ------------------------------------------------------
                    # STATIC
                    # ------------------------------------------------------

                    if exit_model == ExitModel.STATIC:

                        pnl_r = round(final_r, 4)

                    # ------------------------------------------------------
                    # DYNAMIC
                    # ------------------------------------------------------

                    else:

                        if partial_booked:

                            realized_r += (
                                    remaining_position *
                                    final_r
                            )

                            pnl_r = realized_r

                        else:

                            pnl_r = round(final_r, 4)

                    trade_status = (
                        "Win"
                        if pnl_r > 0
                        else "Loss"
                    )

                    exit_price = final_close

                    exit_time = last_row.date

                    exit_index = last_row.name

                # ==========================================================
                # FULL DAY MFE
                # ==========================================================

                max_r_full_day = max_r_execution

                df_after_exit = df_trading_day_full.loc[
                    exit_index + 1:
                ]

                if not df_after_exit.empty:

                    if is_long:

                        max_r_full_day = max(
                            max_r_full_day,
                            (
                                    df_after_exit["high"].max()
                                    - entry_price
                            ) / risk
                        )

                    else:

                        max_r_full_day = max(
                            max_r_full_day,
                            (
                                    entry_price
                                    - df_after_exit["low"].min()
                            ) / risk
                        )

                # ==========================================================
                # DURATION
                # ==========================================================

                exit_pos = (
                    df_trading_day_full.index.get_loc(
                        exit_index
                    )
                )

                duration_minutes = (
                                           exit_time - triggered_time
                                   ).total_seconds() / 60

                duration_bars = max(
                    0,
                    exit_pos - entry_index
                )

                # ==========================================================
                # STORE RESULT
                # ==========================================================

                result.update({

                    "Window": window["name"],

                    "Entry": round(entry_price, 1),
                    "Entry Time": triggered_time,

                    "Exit": round(exit_price, 1),
                    "Exit Time": exit_time,

                    "R": round(pnl_r, 2),

                    "MaxR_Execution": round(
                        max_r_execution,
                        1
                    ),

                    "MaxR_FullDay": round(
                        max_r_full_day,
                        1
                    ),

                    "MAE_R": round(mae_r, 1),

                    "Status": trade_status,

                    "Profit Amount": (
                        round(pnl_r * risk * qty, 2)
                        if pnl_r > 0
                        else 0
                    ),

                    "Loss Amount": (
                        round(abs(pnl_r * risk * qty), 2)
                        if pnl_r < 0
                        else 0
                    ),

                    "Duration_Minutes": round(
                        duration_minutes
                    ),

                    "Duration_Bars": duration_bars,

                    "RiskPerShare": risk,

                    "ExitModel": exit_model.value,

                    "PartialExitPct": partial_exit_pct,

                    "RemainingPosition": remaining_position,

                })

                results.append(result)

    return results


# =========================================================
# ===== DYNAMIC COMPOUNDING STATIC CAPITAL SIMULATION =====
# =========================================================

def apply_dynamic_compounding(df,
                              starting_capital=TRADING_CAPITAL,
                              max_risk_pct=MAX_RISK_PER_TRADE_PERCENT,
                              leverage=INTRADAY_LEVERAGE_MULTIPLIER):
    """
    Static capital simulation — position size is fixed based on TRADING_CAPITAL
    throughout the entire backtest. Capital is never updated between trades.

    This is intentional: we care about RAW SETUP EDGE (R stats, win rate,
    expectancy, profit factor) not compounded ₹ growth. Static sizing keeps
    ₹ PnL linear with Total R, making it easy to sanity-check.

    ₹ PnL per trade = R × fixed_risk_per_trade (in rupees)
    """
    risk_amount = starting_capital * max_risk_pct
    buying_power = starting_capital * leverage

    pnl_list = []
    cum_r = []
    equity = []
    r_total = 0
    running_pnl = 0

    for _, row in df.iterrows():
        risk_per_share = row["RiskPerShare"]
        entry_price = row["Entry"]

        if risk_per_share <= 0:
            pnl_list.append(0)
            cum_r.append(r_total)
            equity.append(starting_capital + running_pnl)
            continue

        risk_based_qty = risk_amount / risk_per_share
        capital_based_qty = buying_power / entry_price
        qty = int(min(risk_based_qty, capital_based_qty))

        if qty <= 0:
            pnl_list.append(0)
            cum_r.append(r_total)
            equity.append(starting_capital + running_pnl)
            continue

        trade_pnl = row["R"] * qty * risk_per_share
        r_total += row["R"]
        running_pnl += trade_pnl

        pnl_list.append(trade_pnl)
        cum_r.append(r_total)
        equity.append(starting_capital + running_pnl)

    df["PnL"] = pnl_list
    df["Cum_R"] = cum_r
    df["Equity"] = equity

    # ₹ drawdown
    df["Equity_Peak"] = df["Equity"].cummax()
    df["DD_PnL"] = df["Equity"] - df["Equity_Peak"]
    df["Drawdown_%"] = df["DD_PnL"] / df["Equity_Peak"] * 100

    # R drawdown
    df["R_Peak"] = df["Cum_R"].cummax()
    df["DD_R"] = df["Cum_R"] - df["R_Peak"]

    return df


# =========================================================
# ================= PERFORMANCE METRICS ===================
# =========================================================

def calculate_max_losing_streak(df):
    max_streak = 0
    current = 0
    for r in df["R"]:
        if r < 0:
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak


def print_core_performance(df):
    total_trades = len(df)
    wins = (df["R"] > 0).sum()
    losses = (df["R"] < 0).sum()
    breakevens = (df["R"] == 0).sum()
    win_rate = wins / total_trades if total_trades > 0 else 0
    avg_win = df[df["R"] > 0]["R"].mean() if wins > 0 else 0
    avg_loss = df[df["R"] < 0]["R"].mean() if losses > 0 else 0
    expectancy = df["R"].mean()
    r_std = df["R"].std()
    sharpe_r = expectancy / r_std if r_std > 0 else 0  # R-based Sharpe

    gross_profit = df[df["PnL"] > 0]["PnL"].sum()
    gross_loss = abs(df[df["PnL"] < 0]["PnL"].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    avg_win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

    print("\n=======================================================")
    print("  CORE PERFORMANCE")
    print("=======================================================")
    print(f"  Total Trades        : {total_trades}")
    print(f"  Wins / Losses / BE  : {wins} / {losses} / {breakevens}")
    print(f"  Win Rate            : {win_rate:.1%}")
    print(f"  Avg Win (R)         : {avg_win:.1f}")
    print(f"  Avg Loss (R)        : {avg_loss:.1f}")
    print(f"  Win/Loss Ratio      : {avg_win_loss_ratio:.1f}")
    print(f"  Expectancy (R)      : {expectancy:.1f}")
    print(f"  R Std Dev           : {r_std:.1f}")
    print(f"  Sharpe (R-based)    : {sharpe_r:.1f}")
    print(f"  Profit Factor       : {profit_factor:.1f}")
    print(f"  Total R             : {df['R'].sum():.1f}")
    print(f"  Total PnL (₹)       : ₹{df['PnL'].sum():,.0f}")

    # CSV export
    os.makedirs(REPORT_FOLDER, exist_ok=True)
    metrics = {
        "Metric": [
            "Total Trades", "Wins", "Losses", "Breakevens", "Win Rate (%)",
            "Avg Win (R)", "Avg Loss (R)", "Win/Loss Ratio", "Expectancy (R)",
            "R Std Dev", "Sharpe (R-based)", "Profit Factor", "Total R", "Total PnL (INR)"
        ],
        "Value": [
            total_trades, wins, losses, breakevens, round(win_rate * 100, 1),
            round(avg_win, 1), round(avg_loss, 1), round(avg_win_loss_ratio, 1),
            round(expectancy, 1), round(r_std, 1), round(sharpe_r, 1),
            round(profit_factor, 1), round(df["R"].sum(), 1), round(df["PnL"].sum(), 0)
        ]
    }
    pd.DataFrame(metrics).to_csv(os.path.join(REPORT_FOLDER, "core_performance.csv"), index=False)
    print(f"  [CSV] core_performance.csv saved.")


def print_risk_metrics(df):
    max_dd_r = df["DD_R"].min()
    max_dd_amt = df["DD_PnL"].min()
    max_dd_pct = df["Drawdown_%"].min()
    avg_dd_pct = df[df["DD_PnL"] < 0]["Drawdown_%"].mean()

    total_r = df["R"].sum()
    recovery_factor = total_r / abs(max_dd_r) if max_dd_r != 0 else 0
    max_losing_streak = calculate_max_losing_streak(df)

    # CAGR estimate based on equity curve
    start_eq = df["Equity"].iloc[0]
    end_eq = df["Equity"].iloc[-1]
    start_date = df["Entry Time"].iloc[0]
    end_date = df["Entry Time"].iloc[-1]
    years = max((end_date - start_date).days / 365.25, 1e-6)
    cagr = ((end_eq / start_eq) ** (1 / years) - 1) * 100

    # Calmar = CAGR / |MaxDD%|
    calmar = cagr / abs(max_dd_pct) if max_dd_pct != 0 else 0

    print("\n=======================================================")
    print("  RISK METRICS")
    print("=======================================================")
    print(f"  Max Drawdown (R)    : {max_dd_r:.1f}")
    print(f"  Max Drawdown (₹)    : ₹{max_dd_amt:,.0f}")
    print(f"  Max Drawdown (%)    : {max_dd_pct:.1f}%")
    print(f"  Avg Drawdown (%)    : {avg_dd_pct:.1f}%")
    print(f"  Recovery Factor     : {recovery_factor:.1f}")
    print(f"  CAGR                : {cagr:.1f}%")
    print(f"  Calmar Ratio        : {calmar:.1f}")
    print(f"  Max Losing Streak   : {max_losing_streak}")

    # CSV export
    os.makedirs(REPORT_FOLDER, exist_ok=True)
    metrics = {
        "Metric": [
            "Max Drawdown (R)", "Max Drawdown (INR)", "Max Drawdown (%)", "Avg Drawdown (%)",
            "Recovery Factor", "CAGR (%)", "Calmar Ratio", "Max Losing Streak"
        ],
        "Value": [
            round(max_dd_r, 1), round(max_dd_amt, 0), round(max_dd_pct, 1),
            round(avg_dd_pct, 1), round(recovery_factor, 1), round(cagr, 1),
            round(calmar, 1), max_losing_streak
        ]
    }
    pd.DataFrame(metrics).to_csv(os.path.join(REPORT_FOLDER, "risk_metrics.csv"), index=False)
    print(f"  [CSV] risk_metrics.csv saved.")


def print_r_distribution(df):
    print("\n=======================================================")
    print("  R Distribution  (LONG only)")
    print("=======================================================")

    # < -1R only possible via gap-down open through stop (realistic fill) or EOD at loss
    buckets = {
        "< -1R (gap)": (df["R"] < -1).sum(),
        "-1R to 0R": ((df["R"] >= -1) & (df["R"] < 0)).sum(),
        "0R (BE)": ((df["R"] >= -0.05) & (df["R"] <= 0.05)).sum(),
        "0-1R": ((df["R"] > 0.05) & (df["R"] <= 1)).sum(),
        "1-2R": ((df["R"] > 1) & (df["R"] <= 2)).sum(),
        "2-4R": ((df["R"] > 2) & (df["R"] <= 4)).sum(),
        "4-6R": ((df["R"] > 4) & (df["R"] <= 6)).sum(),
        "6-8R": ((df["R"] > 6) & (df["R"] <= 8)).sum(),
        "8-10R": ((df["R"] > 8) & (df["R"] <= 10)).sum(),
        "10R+": (df["R"] > 10).sum()
    }

    for k, v in buckets.items():
        print(f"  {k:18} : {v}")

    # CSV export
    os.makedirs(REPORT_FOLDER, exist_ok=True)
    pd.DataFrame({"Bucket": list(buckets.keys()), "Count": list(buckets.values())}).to_csv(
        os.path.join(REPORT_FOLDER, "r_distribution.csv"), index=False
    )
    print(f"  [CSV] r_distribution.csv saved.")


def print_rolling_stats(df, window=200):
    if len(df) < window:
        print("\nNot enough trades for rolling analysis.")
        return

    rolling_exp = df["R"].rolling(window).mean().iloc[-1]
    rolling_wr = (df["R"] > 0).rolling(window).mean().iloc[-1]

    print("\n=======================================================")
    print(f"  Rolling {window}-Trade Stats")
    print("=======================================================")
    print(f"  Latest Expectancy   : {rolling_exp:.1f} R")
    print(f"  Latest Win Rate     : {rolling_wr:.1%}")

    # CSV export — full rolling series for charting
    os.makedirs(REPORT_FOLDER, exist_ok=True)
    rolling_df = pd.DataFrame({
        "Trade_Index": df.index,
        "Entry_Time": df["Entry Time"].values,
        f"Rolling_{window}_Expectancy_R": df["R"].rolling(window).mean().round(3),
        f"Rolling_{window}_WinRate": (df["R"] > 0).rolling(window).mean().round(4),
    })
    rolling_df.to_csv(os.path.join(REPORT_FOLDER, "rolling_stats.csv"), index=False)
    print(f"  [CSV] rolling_stats.csv saved.")


def print_setup_summary(df):
    def setup_max_dd_r(group):
        cum_r = group["R"].cumsum()
        peak = cum_r.cummax()
        return (cum_r - peak).min()

    def setup_max_dd_pnl(group):
        cum_pnl = group["PnL"].cumsum()
        peak = cum_pnl.cummax()
        return (cum_pnl - peak).min()

    summary = (
        df.groupby("Setup")
        .agg(
            Trades=("R", "count"),
            WinRate=("R", lambda x: round((x > 0).mean() * 100, 1)),
            AvgWin_R=("R", lambda x: round(x[x > 0].mean(), 1) if (x > 0).any() else 0),
            AvgLoss_R=("R", lambda x: round(x[x < 0].mean(), 1) if (x < 0).any() else 0),
            Expectancy_R=("R", lambda x: round(x.mean(), 1)),
            Total_R=("R", lambda x: round(x.sum(), 1)),
            Total_PnL=("PnL", lambda x: round(x.sum(), 0)),
            ProfitFactor=("PnL",
                          lambda x: round(x[x > 0].sum() / abs(x[x < 0].sum()), 1)
                          if abs(x[x < 0].sum()) > 0 else float("inf")),
        )
        .sort_values("Expectancy_R", ascending=False)
    )

    # Add per-setup drawdown correctly
    summary["MaxDD_R"] = df.groupby("Setup").apply(setup_max_dd_r).round(1)
    summary["MaxDD_PnL"] = df.groupby("Setup").apply(setup_max_dd_pnl).round(0)

    print("\n=======================================================")
    print("  SETUP SUMMARY")
    print("=======================================================")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", None)
    pd.set_option("display.max_rows", None)
    print(summary.to_string())

    # CSV export
    os.makedirs(REPORT_FOLDER, exist_ok=True)
    summary.to_csv(os.path.join(REPORT_FOLDER, "setup_summary.csv"))
    print(f"  [CSV] setup_summary.csv saved.")


def print_yearly_summary(df):
    df = df.copy()
    df["Year"] = df["Entry Time"].dt.year

    def grp_max_dd_r(group):
        cum_r = group["R"].cumsum()
        peak = cum_r.cummax()
        return round((cum_r - peak).min(), 1)

    def grp_max_dd_pnl(group):
        cum_pnl = group["PnL"].cumsum()
        peak = cum_pnl.cummax()
        return round((cum_pnl - peak).min(), 0)

    yearly = (
        df.groupby(["Year", "Setup"])
        .agg(
            Trades=("R", "count"),
            WinRate=("R", lambda x: round((x > 0).mean() * 100, 1)),
            Expectancy_R=("R", lambda x: round(x.mean(), 1)),
            Total_R=("R", lambda x: round(x.sum(), 1)),
            Total_PnL=("PnL", lambda x: round(x.sum(), 0)),
            ProfitFactor=("PnL",
                          lambda x: round(x[x > 0].sum() / abs(x[x < 0].sum()), 1)
                          if abs(x[x < 0].sum()) > 0 else float("inf")),
        )
        .sort_index()
    )

    yearly["MaxDD_R"] = df.groupby(["Year", "Setup"]).apply(grp_max_dd_r)
    yearly["MaxDD_PnL"] = df.groupby(["Year", "Setup"]).apply(grp_max_dd_pnl)

    print("\n=======================================================")
    print("  YEAR-WISE PERFORMANCE (By Setup)")
    print("=======================================================")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", None)
    pd.set_option("display.max_rows", None)
    print(yearly.to_string())

    # CSV export
    os.makedirs(REPORT_FOLDER, exist_ok=True)
    yearly.to_csv(os.path.join(REPORT_FOLDER, "yearly_summary.csv"))
    print(f"  [CSV] yearly_summary.csv saved.")


def print_trade_quality(df):
    avg_mfe = df["MaxR_Execution"].mean()
    avg_mae = df["MAE_R"].mean()  # Expected negative for LONG (adverse = downside)
    avg_mae_abs = abs(avg_mae)
    avg_dur = df["Duration_Minutes"].mean()
    avg_mfe_full = df["MaxR_FullDay"].mean()

    # Capture efficiency: how much of the full-day upside (LONG MFE) did we actually capture
    efficiency = (df["MaxR_Execution"] / df["MaxR_FullDay"].replace(0, float("nan"))).mean() * 100

    # MAE edge: avg how far price went against us before recovering — key for stop placement
    pct_mae_beyond_half_r = (df["MAE_R"] < -0.5).mean() * 100  # % trades that dipped > 0.5R against

    print("\n=======================================================")
    print("  TRADE QUALITY  (LONG — favourable = UP, adverse = DOWN)")
    print("=======================================================")
    print(f"  Avg MFE (execution) : +{avg_mfe:.1f} R  (best upside seen while in trade)")
    print(f"  Avg MFE (full day)  : +{avg_mfe_full:.1f} R  (best upside available whole day)")
    print(f"  Avg MAE             : {avg_mae:.1f} R  (avg worst drawdown vs entry)")
    print(f"  Avg |MAE|           : {avg_mae_abs:.1f} R")
    print(f"  % Trades MAE > 0.5R : {pct_mae_beyond_half_r:.1f}%  (stop stress indicator)")
    print(f"  Avg Duration (min)  : {avg_dur:.1f}")
    print(f"  Capture Efficiency  : {efficiency:.1f}%")

    # CSV export
    os.makedirs(REPORT_FOLDER, exist_ok=True)
    metrics = {
        "Metric": [
            "Avg MFE Execution (R)", "Avg MFE Full Day (R)", "Avg MAE (R)", "Avg |MAE| (R)",
            "% Trades MAE > 0.5R", "Avg Duration (min)", "Capture Efficiency (%)"
        ],
        "Value": [
            round(avg_mfe, 1), round(avg_mfe_full, 1), round(avg_mae, 1), round(avg_mae_abs, 1),
            round(pct_mae_beyond_half_r, 1), round(avg_dur, 1), round(efficiency, 1)
        ]
    }
    pd.DataFrame(metrics).to_csv(os.path.join(REPORT_FOLDER, "trade_quality.csv"), index=False)
    print(f"  [CSV] trade_quality.csv saved.")


def plot_real_equity(df):
    os.makedirs(REPORT_FOLDER, exist_ok=True)

    plt.figure(figsize=(12, 6))
    plt.plot(df["Entry Time"], df["Equity"])
    plt.title("Compounded Equity Curve")
    plt.xlabel("Date")
    plt.ylabel("Equity (₹)")
    plt.grid(True)
    equity_path = os.path.join(REPORT_FOLDER, "equity_curve.jpg")
    plt.savefig(equity_path, format="jpeg", dpi=150, bbox_inches="tight")
    print(f"  [JPEG] equity_curve.jpg saved.")
    plt.show()

    plt.figure(figsize=(12, 6))
    plt.plot(df["Entry Time"], df["Drawdown_%"], color="red")
    plt.title("Drawdown (%)")
    plt.xlabel("Date")
    plt.ylabel("Drawdown (%)")
    plt.grid(True)
    drawdown_path = os.path.join(REPORT_FOLDER, "drawdown.jpg")
    plt.savefig(drawdown_path, format="jpeg", dpi=150, bbox_inches="tight")
    print(f"  [JPEG] drawdown.jpg saved.")
    plt.show()


# =========================================================
# ================= BACKTEST DRIVER =======================
# =========================================================

def backtest_historical_data_parallel(symbols_dict, max_workers=8):
    all_results = []

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_symbol, sym, token): sym
            for sym, token in symbols_dict.items()
        }

        for future in as_completed(futures):
            sym = futures[future]
            try:
                result = future.result()
                if result:
                    all_results.append(pd.DataFrame(result))
            except Exception as e:
                print(f"Error processing {sym}: {e}")

    if not all_results:
        print("No trades found.")
        return

    df = pd.concat(all_results, ignore_index=True)

    df["Entry Time"] = pd.to_datetime(df["Entry Time"])
    df["Exit Time"] = pd.to_datetime(df["Exit Time"])

    df = df.sort_values("Entry Time").reset_index(drop=True)

    df = apply_dynamic_compounding(df)

    print("\n=======================================================")
    print("  MODE: ALL SIGNALS — static capital sizing")
    print("  R metrics = edge | ₹ PnL = linear proxy (not compounded)")
    print("=======================================================")

    print_core_performance(df)
    print_risk_metrics(df)
    print_r_distribution(df)
    print_rolling_stats(df)
    print_trade_quality(df)
    print_setup_summary(df)
    print_yearly_summary(df)

    plot_real_equity(df)

    df.to_csv("intraday_m5_backtest_results.csv", index=False)
    print("\nCSV export complete.")


# =========================================================

if __name__ == "__main__":
    initialize_logger(TradeType.INTRADAY, "m5")

    # load symbols and instrument token
    symbol_token_map = get_symbol_instrument_token(LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH)

    backtest_historical_data_parallel(symbol_token_map)
