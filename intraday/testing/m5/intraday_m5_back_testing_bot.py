import os
import time
from collections import deque
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta

import matplotlib.pyplot as plt
import pandas as pd

from intraday.scanner.m5.intraday_m5_breakout_scanner_bot import analyze_stock_for_setup, add_technical_indicators
from util.entry_type import EntryType
from util.exit_model_util import ExitModel
from util.global_variables import INTRADAY_M5_CANDLE_SIZE, TRADING_CAPITAL, MAX_RISK_PER_TRADE_PERCENT, \
    INTRADAY_LEVERAGE_MULTIPLIER, \
    EVB_SCAN_CANDLE_TIME, LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH, INTRADAY_M5_CANDLE_LIMIT, \
    INTRADAY_M5_ATR_RISK_MULTIPLIER
from util.kite_util import get_kite
from util.setup_type import IntradaySetupType
from util.shariah_stock_filter import get_symbol_instrument_token
from util.trade_logger import initialize_logger
from util.trade_type import TradeType

# ================= CONFIG =================
INTERVAL = "5minute"
DAYS = 100  # Max allowed per Kite API
DATA_FOLDER = f"data/{INTERVAL}"
REPORT_FOLDER = "reports"
# Flat round-trip cost (brokerage + STT + other statutory charges), in ₹,
# charged once per completed trade (entry + exit combined).

entry_slippage_bp = 2
stop_slippage_bp = 4
exit_model = ExitModel.STATIC
EVB_TARGET_R = 2.1 / INTRADAY_M5_ATR_RISK_MULTIPLIER  # EVB travels 2 ATR from entry on average
EMB_TARGET_R = 1.9 / INTRADAY_M5_ATR_RISK_MULTIPLIER  # EMB travels 2 ATR from entry on average

# --------------------------------------------------------------
# Trailing-stop distance (used by ExitModel.DYNAMIC after T1/partial
# is booked). Deliberately NOT ATR-based: the stop trails behind the
# lowest low (long) / highest high (short) of the last
# ROLLING_TRAIL_LOOKBACK closed candles — a level readable straight
# off a chart, so this can be executed manually (check the last N
# candles, move the SL order if it improves) rather than requiring
# an automated bot recomputing ATR every bar.
# Smaller = tighter (locks in more, exits sooner on pullbacks).
# Larger = looser (rides out bigger dips, gives back more on reversals).
# --------------------------------------------------------------
ROLLING_TRAIL_LOOKBACK = 3
R = TRADING_CAPITAL * MAX_RISK_PER_TRADE_PERCENT
# ==========================================================
# Dynamic Round Trip Cost Calculator
# ==========================================================

# ----------------------------
# CONFIGURATION
# ----------------------------

# ─── Breakout windows ─────────────────────────────────────────────────────────
BREAKOUT_WINDOWS = [
    {
        "name": "EVB",
        "start": EVB_SCAN_CANDLE_TIME,
        "end": EVB_SCAN_CANDLE_TIME
    }
]


# ==========================================================
# NSE Equity Intraday Charges
# ==========================================================

NSE_EQUITY_INTRADAY_CHARGES = {

    # Brokerage
    "brokerage_rate": 0.0003,  # 0.03%
    "brokerage_cap": 20.0,  # ₹20/order

    # Taxes & Charges
    "stt": 0.00025,  # Sell side only
    "exchange": 0.0000345,  # NSE transaction charges
    "sebi": 0.000001,  # ₹10 / crore
    "stamp": 0.00003,  # Buy side only
    "gst": 0.18,

}


def get_tick_size(price: float) -> float:
    """
    Returns the NSE tick size based on the stock price.
    """
    if price < 250:
        return 0.01
    elif price <= 1000:
        return 0.05
    elif price <= 5000:
        return 0.10
    elif price <= 10000:
        return 0.50
    elif price <= 20000:
        return 1.00
    else:
        return 5.00


def calculate_round_trip_cost(
        entry_price: float,
        exit_price: float,
        quantity: int):
    """
    Calculate complete round-trip trading costs.

    Parameters
    ----------
    entry_price : float
    exit_price  : float
    quantity    : int


    Returns
    -------
    dict
    """

    buy_value = entry_price * quantity
    sell_value = exit_price * quantity

    turnover = buy_value + sell_value

    # --------------------------------------------------
    # Brokerage
    # --------------------------------------------------

    brokerage_buy = min(
        NSE_EQUITY_INTRADAY_CHARGES["brokerage_cap"],
        buy_value * NSE_EQUITY_INTRADAY_CHARGES["brokerage_rate"]
    )

    brokerage_sell = min(
        NSE_EQUITY_INTRADAY_CHARGES["brokerage_cap"],
        sell_value * NSE_EQUITY_INTRADAY_CHARGES["brokerage_rate"]
    )

    brokerage = brokerage_buy + brokerage_sell

    # --------------------------------------------------
    # STT (Sell side only)
    # --------------------------------------------------

    stt = sell_value * NSE_EQUITY_INTRADAY_CHARGES["stt"]

    # --------------------------------------------------
    # Exchange Charges
    # --------------------------------------------------

    exchange = turnover * NSE_EQUITY_INTRADAY_CHARGES["exchange"]

    # --------------------------------------------------
    # SEBI Charges
    # --------------------------------------------------

    sebi = turnover * NSE_EQUITY_INTRADAY_CHARGES["sebi"]

    # --------------------------------------------------
    # Stamp Duty (Buy side only)
    # --------------------------------------------------

    stamp = buy_value * NSE_EQUITY_INTRADAY_CHARGES["stamp"]

    # --------------------------------------------------
    # GST
    # GST applies only to Brokerage + Exchange Charges
    # --------------------------------------------------

    gst = (
                  brokerage +
                  exchange
          ) * NSE_EQUITY_INTRADAY_CHARGES["gst"]

    # --------------------------------------------------
    # Total
    # --------------------------------------------------

    total = (
            brokerage +
            stt +
            exchange +
            sebi +
            stamp +
            gst
    )

    return {

        "buy_value": round(buy_value, 2),

        "sell_value": round(sell_value, 2),

        "turnover": round(turnover, 2),

        "brokerage": round(brokerage, 2),

        "stt": round(stt, 2),

        "exchange": round(exchange, 2),

        "sebi": round(sebi, 2),

        "stamp": round(stamp, 2),

        "gst": round(gst, 2),

        "total": round(total, 2)

    }


def get_file_path(symbol):
    """Returns the file path for CSV data for a symbol."""
    os.makedirs(DATA_FOLDER, exist_ok=True)
    return os.path.join(DATA_FOLDER, f"NSE_{symbol}.csv")


def fetch_back_testing_data(symbol, instrument_token, from_year=None, to_year=None, num_years=3):
    """
    Fetch historical OHLCV data. Two modes:
      - Specify from_year & to_year  → fetches that exact range  (e.g. from_year=2022, to_year=2026)
      - Specify num_years            → fetches last N years from today (default: last 3 years — older
        data is treated as less relevant since market microstructure/liquidity regimes shift over time)
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

        df.rename(columns={'date': 'trade_date'}, inplace=True)

        df.drop_duplicates(subset=['trade_date'], inplace=True)

        df.sort_values('trade_date', inplace=True)

        df.reset_index(drop=True, inplace=True)

        file_path = get_file_path(symbol)
        df.to_csv(file_path, index=False)

        print(f"Saved {len(df)} candles for {symbol} to {file_path}")
        return True

    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        return False


def compute_quantity(entry_price, risk_per_share):
    # Buying power (equity × leverage). INTRADAY_LEVERAGE_MULTIPLIER already
    # has the 5% undeployed-cash policy baked in (e.g. 5x * 0.95 = 4.75) —
    # do not apply an additional buffer here, that would double-count it.
    buying_power = TRADING_CAPITAL * INTRADAY_LEVERAGE_MULTIPLIER

    # REAL risk (based on equity) — the fixed "1R" unit, defined once at
    # module level as R = TRADING_CAPITAL * MAX_RISK_PER_TRADE_PERCENT.
    risk_based_qty = R / risk_per_share

    # Capital-based qty (using leverage)
    capital_based_qty = buying_power / entry_price

    is_leverage_constrained = capital_based_qty < risk_based_qty
    tradable_qty = min(risk_based_qty, capital_based_qty)

    # Quantity is rounded to the nearest 5 for convenience.
    if tradable_qty > 5:
        tradable_qty = round(tradable_qty / 5.0) * 5
    return tradable_qty, is_leverage_constrained


def process_symbol(
        symbol,
        instrument_token,
        partial_exit_pct=0.4,  # 0.5 = 50%, 0.3 = 30%
        entry_buffer_multiplier=2
):
    ENTRY_LOOKAHEAD_CANDLES = 15

    initialize_logger(
        TradeType.INTRADAY,
        f"m{INTRADAY_M5_CANDLE_SIZE}",
        True
    )

    file_path = get_file_path(symbol)

    if not os.path.isfile(file_path) or os.path.getsize(file_path) == 0:
        fetch_back_testing_data(symbol, instrument_token, num_years=5)

    df = pd.read_csv(file_path)

    df.columns = df.columns.str.strip()

    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df['day'] = df['trade_date'].dt.date

    add_technical_indicators(df)

    results = []

    day_groups = {d: g for d, g in df.groupby('day')}

    for trading_day, df_day in day_groups.items():

        for window in BREAKOUT_WINDOWS:

            mask = (
                    (df_day['trade_date'].dt.time >= window["start"]) &
                    (df_day['trade_date'].dt.time <= window["end"])
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

                breakout_time = breakout_candle['trade_date']

                df_after_breakout = df_trading_day_full[
                    df_trading_day_full['trade_date'] > breakout_time
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
                tick_size = get_tick_size(confirmation_candle["high"])

                if is_long:
                    trigger_price = (
                            max(confirmation_candle["high"],
                                breakout_candle["high"]) + entry_buffer_multiplier * tick_size
                    )

                else:

                    trigger_price = (
                            min(
                                confirmation_candle["low"],
                                breakout_candle["low"]
                            ) -
                            entry_buffer_multiplier * tick_size
                    )

                entry_filled = False

                for row in df_entry_window.itertuples():

                    if row.low <= trigger_price <= row.high:
                        entry_price = trigger_price

                        # Slippage does NOT shift the entry fill (and
                        # therefore does not shift stop/target geometry).
                        # It is tracked as a separate per-share cost and
                        # deducted only from the rupee P&L later.

                        entry_slippage_per_share = (
                                entry_price * entry_slippage_bp / 10000

                        )

                        triggered_time = row.trade_date

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

                if result["Setup"] == IntradaySetupType.EVB.name:
                    target_r = EVB_TARGET_R
                elif result["Setup"] == IntradaySetupType.EMB.name:
                    target_r = EMB_TARGET_R


                risk = result["Risk"]

                if risk <= 0:
                    continue

                qty, _ = compute_quantity(entry_price, risk)

                # Exit-side slippage cost (per share), only ever set when
                # the trade actually exits via a stop-loss / trailing stop.
                # Stays 0 for target / EOD exits.
                exit_slippage_per_share = 0.0

                # ==========================================================
                # STATIC EXIT LEVELS
                # ==========================================================

                if is_long:

                    stop_loss = entry_price - risk

                    static_target = (
                            entry_price +
                            target_r * risk
                    )

                else:

                    stop_loss = entry_price + risk

                    static_target = (
                            entry_price -
                            target_r * risk
                    )

                # ==========================================================
                # DYNAMIC TARGETS
                # ==========================================================
                final_target_r = target_r * 3
                if is_long:

                    partial_target = (
                            entry_price +
                            target_r * risk
                    )

                    final_target = (
                            entry_price +
                            final_target_r * risk
                    )

                else:

                    partial_target = (
                            entry_price -
                            target_r * risk
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

                # T1 = partial/first target, T2 = final target.
                # Tracked independently of trade_status/exit reason so we
                # can report "hit T2", "hit T1 but not T2", "never hit T1"
                # regardless of how/where the trade eventually exited.
                t1_hit = False
                t2_hit = False

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

                # ------------------------------------------------------
                # RECENT CANDLE LOWS/HIGHS
                # ------------------------------------------------------
                # Rolling history of the last ROLLING_TRAIL_LOOKBACK closed
                # candles' lows (long) / highs (short), used below to
                # compute a trail a person can read straight off a chart:
                # "lowest low of the last N candles" — no ATR, no R-math.
                recent_extremes = deque(maxlen=ROLLING_TRAIL_LOOKBACK)

                # ==========================================================
                # EXECUTION LOOP
                # ==========================================================

                for i, row in enumerate(df_post_entry.itertuples()):

                    high = row.high
                    low = row.low
                    close = row.close
                    dt = row.trade_date

                    # ------------------------------------------------------
                    # ACTIVATE PENDING TRAILING STOP
                    # ------------------------------------------------------

                    if pending_trailing_stop is not None:
                        trailing_stop = pending_trailing_stop
                        pending_trailing_stop = None

                    # ------------------------------------------------------
                    # TRACK ROLLING CANDLE EXTREMES
                    # ------------------------------------------------------
                    # Appended every bar (not just after partial) so that
                    # once T1 fires, the last N candles' worth of history
                    # is already available rather than starting empty.

                    recent_extremes.append(low if is_long else high)

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

                        # INTRABAR PRIORITY: TARGET FIRST

                        if target_hit:

                            exit_price = static_target

                            pnl_r = (
                                target_r
                            )

                            # STATIC model has only one target, which sits
                            # at the same R multiple as T1 in the dynamic
                            # model. There is no separate T2 leg here.
                            t1_hit = True
                            t2_hit = False

                            trade_status = "Win"

                            exit_time = dt
                            exit_index = row.Index

                            break

                        elif stop_hit:

                            exit_price = stop_loss

                            pnl_r = -1


                            exit_slippage_per_share = (
                                    exit_price * stop_slippage_bp / 10000
                            )

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

                            # INTRABAR PRIORITY: PARTIAL TARGET FIRST

                            if partial_hit:

                                partial_booked = True
                                t1_hit = True

                                realized_r += (
                                        booked_position *
                                        target_r
                                )

                                # Move to breakeven
                                # ACTIVE NEXT CANDLE
                                pending_trailing_stop = (
                                    entry_price
                                )

                            elif stop_hit:

                                exit_price = stop_loss

                                pnl_r = -1


                                exit_slippage_per_share = (
                                        exit_price * stop_slippage_bp / 10000
                                )

                                trade_status = "Loss"

                                exit_time = dt
                                exit_index = row.Index

                                break

                        # --------------------------------------------------
                        # AFTER PARTIAL EXIT
                        # --------------------------------------------------

                        else:

                            # ----------------------------------------------
                            # ROLLING N-CANDLE TRAIL (manually executable)
                            # ----------------------------------------------
                            # Previously an ATR-based chandelier trail —
                            # accurate, but requires recomputing ATR every
                            # candle for every open position, which isn't
                            # realistic to execute by hand. This version
                            # uses only what's visible on the chart: the
                            # lowest low (long) / highest high (short) of
                            # the last ROLLING_TRAIL_LOOKBACK closed candles.
                            # A person managing one position can check this
                            # every candle close and move their SL order to
                            # match — no ATR, no R-arithmetic. Naturally
                            # volatility-adaptive the same way ATR is
                            # (recent lows sit further away in a choppy
                            # stock, closer in a calm one) without requiring
                            # any calculation beyond "what's the lowest low
                            # of the last few candles". The stop only ever
                            # moves in the favorable direction (monotonic)
                            # and never below breakeven.

                            if is_long:

                                candidate_stop = min(recent_extremes)

                                if candidate_stop > trailing_stop:
                                    pending_trailing_stop = candidate_stop

                            else:

                                candidate_stop = max(recent_extremes)

                                if candidate_stop < trailing_stop:
                                    pending_trailing_stop = candidate_stop

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

                            # INTRABAR PRIORITY: FINAL TARGET FIRST

                            if final_target_hit:

                                t2_hit = True

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

                                exit_price = trailing_stop


                                exit_slippage_per_share = (
                                        exit_price * stop_slippage_bp / 10000
                                )

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

                    exit_time = last_row.trade_date

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

                ROUND_TRIP_COST = calculate_round_trip_cost(entry_price, exit_price, qty).get(
                    "total")
                result.update({

                    "Window": window["name"],

                    "Entry": round(entry_price, 2),
                    "Entry Time": triggered_time,

                    "Exit": round(exit_price, 2),
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

                    # Target-hit flags (see "TRADE STATE" section above for
                    # exactly where each is set).
                    "T1_Hit": t1_hit,
                    "T2_Hit": t2_hit,

                    # Gross PnL (before costs) vs Net PnL (after slippage
                    # cost + flat round-trip brokerage/STT/other charges).
                    # Note: R itself (and target/SL levels) is computed off
                    # the clean signal price — slippage only hits the
                    # rupee P&L, never the trade geometry.
                    "Gross PnL": round(pnl_r * risk * qty, 2),

                    "SlippagePerShare": round(
                        entry_slippage_per_share + exit_slippage_per_share, 4
                    ),

                    "SlippageCost": round(
                        (entry_slippage_per_share + exit_slippage_per_share)
                        * qty, 2
                    ),

                    "RoundTripCost": ROUND_TRIP_COST,

                    "Net PnL": round(
                        pnl_r * risk * qty
                        - (entry_slippage_per_share + exit_slippage_per_share) * qty
                        - ROUND_TRIP_COST, 2
                    ),

                    "Profit Amount": (
                        round(
                            pnl_r * risk * qty
                            - (entry_slippage_per_share + exit_slippage_per_share) * qty
                            - ROUND_TRIP_COST, 2
                        )
                        if (
                                   pnl_r * risk * qty
                                   - (entry_slippage_per_share + exit_slippage_per_share) * qty
                                   - ROUND_TRIP_COST
                           ) > 0
                        else 0
                    ),

                    "Loss Amount": (
                        round(
                            abs(
                                pnl_r * risk * qty
                                - (entry_slippage_per_share + exit_slippage_per_share) * qty
                                - ROUND_TRIP_COST
                            ), 2
                        )
                        if (
                                   pnl_r * risk * qty
                                   - (entry_slippage_per_share + exit_slippage_per_share) * qty
                                   - ROUND_TRIP_COST
                           ) < 0
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
                              starting_capital=TRADING_CAPITAL):
    """
    Position-sized R simulation.

    qty comes from `compute_quantity()` — the exact same sizing function
    used in process_symbol/live trading — so the backtest's quantity and
    capital cap can never drift out of sync with the live path. The
    `starting_capital`/`max_risk_pct`/`leverage` args are kept for
    signature compatibility, but the actual "1R" unit used everywhere in
    this function is the module-level global `R = TRADING_CAPITAL *
    MAX_RISK_PER_TRADE_PERCENT` (defined once near the top of the file),
    not these arguments — pass non-default values here only if you've
    also overridden the corresponding globals, otherwise they're ignored.
    Note INTRADAY_LEVERAGE_MULTIPLIER already has the 5% undeployed-cash
    policy priced in (e.g. 5x leverage × 0.95 = 4.75) — don't apply an
    additional buffer on top of it anywhere in this pipeline.

    What changes: `R` (the per-trade multiple, stored in df["R"]) is now
    `net trade PnL / R` (the global constant) — normalized against actual
    capital at risk AND net of costs, not the theoretical price-based
    multiple. The raw price-based R coming into this function (row["R"])
    assumes you always got the full risk_based_qty (i.e. the full global
    R actually on the line) and ignores slippage/brokerage. Whenever
    capital_based_qty caps the position below that, or costs eat into the
    trade, the resulting df["R"] reflects that — a full stop-out
    shouldn't count as a full -1R if you didn't really have the full R on,
    and shouldn't count as exactly -1R even when you did, once costs are
    included.

    Example: R (global) = ₹12,500, but this trade could only take a
    position risking ₹6,250 (half size, capital-constrained). Stop hit →
    gross loss ₹6,250, minus slippage/brokerage → net loss e.g. ₹6,845 →
    reported df["R"] = -6,845 / 12,500 = -0.55 (not -1, not -0.5 either —
    costs are baked in too).

    Using net PnL (not gross) is deliberate: it's what makes every
    R-based stat tie out EXACTLY to its ₹ counterpart via the single
    global R constant — Total_R × R == Total_PnL, DD_R × R == DD_PnL at
    every point on the equity curve, Expectancy(R) × trade_count × R ==
    Total_PnL. Using gross PnL here would silently reintroduce a
    gross/net mismatch (R and ₹ drawdown would stop reconciling). The
    original, uncapped, pre-cost price-based R is preserved in
    `R_Theoretical` for reference (raw setup quality, independent of
    capital and costs), and `Leverage_Constrained` flags which trades
    were capital-capped.

    ₹ PnL per trade = price-based R × qty × risk_per_share, net of:
      - slippage cost = SlippagePerShare × qty
      - a flat ROUND_TRIP_COST (brokerage + STT + other charges)
    """
    pnl_list = []
    gross_pnl_list = []
    r_position_sized_list = []
    cum_r = []
    equity = []
    leverage_constrained_list = []
    slippage_cost_list = []
    round_trip_cost_list = []
    r_total = 0
    running_pnl = 0

    for _, row in df.iterrows():
        risk_per_share = row["RiskPerShare"]
        ROUND_TRIP_COST = row["RoundTripCost"]
        entry_price = row["Entry"]
        slippage_per_share = row.get("SlippagePerShare", 0)
        price_based_r = row["R"]

        if risk_per_share <= 0:
            pnl_list.append(0)
            gross_pnl_list.append(0)
            r_position_sized_list.append(0)
            cum_r.append(r_total)
            equity.append(starting_capital + running_pnl)
            leverage_constrained_list.append(False)
            slippage_cost_list.append(0)
            round_trip_cost_list.append(0)
            continue

        # Use the SAME sizing function as process_symbol/live trading —
        # single source of truth for qty, including round-to-nearest-5.
        # NOTE: compute_quantity reads TRADING_CAPITAL / MAX_RISK_PER_TRADE_PERCENT /
        # INTRADAY_LEVERAGE_MULTIPLIER directly from module globals, not from
        # this function's starting_capital/max_risk_pct/leverage arguments —
        # those globals are the defaults for this function too, so they
        # agree unless this function is called with overridden values for a
        # what-if scenario.
        qty, is_leverage_constrained = compute_quantity(entry_price, risk_per_share)
        qty = int(qty)

        if qty <= 0:
            pnl_list.append(0)
            gross_pnl_list.append(0)
            r_position_sized_list.append(0)
            cum_r.append(r_total)
            equity.append(starting_capital + running_pnl)
            leverage_constrained_list.append(is_leverage_constrained)
            slippage_cost_list.append(0)
            round_trip_cost_list.append(0)
            continue

        slippage_cost = slippage_per_share * qty
        gross_trade_pnl = price_based_r * qty * risk_per_share
        trade_pnl = gross_trade_pnl - slippage_cost - ROUND_TRIP_COST

        # R-multiple = actual net ₹ PnL / the global R unit. Net (not
        # gross), so every R-based stat ties out exactly to its ₹
        # counterpart via this one constant: Total_R x R == Total_PnL,
        # DD_R x R == DD_PnL, Expectancy(R) x trades x R == Total_PnL.
        # (Using gross_trade_pnl here instead would silently reintroduce
        # the gross/net mismatch that made MaxDD_R and MaxDD_PnL not
        # reconcile.)
        position_sized_r = trade_pnl / R

        r_total += position_sized_r
        running_pnl += trade_pnl

        pnl_list.append(trade_pnl)
        gross_pnl_list.append(gross_trade_pnl)
        r_position_sized_list.append(position_sized_r)
        cum_r.append(r_total)
        equity.append(starting_capital + running_pnl)
        leverage_constrained_list.append(is_leverage_constrained)
        slippage_cost_list.append(slippage_cost)
        round_trip_cost_list.append(ROUND_TRIP_COST)

    df["Gross_PnL"] = gross_pnl_list
    df["PnL"] = pnl_list
    df["R_Theoretical"] = df["R"]
    df["R"] = r_position_sized_list
    # Gross R-multiple (pre-cost) — same global R unit as the net df["R"],
    # so Gross Expectancy(R) x trades x R == Total Gross PnL, exactly the
    # way Expectancy(R) x trades x R == Total_PnL does for the net figure.
    df["R_Gross"] = df["Gross_PnL"] / R
    df["Cum_R"] = cum_r
    df["Equity"] = equity
    df["Leverage_Constrained"] = leverage_constrained_list
    df["SlippageCost_Actual"] = slippage_cost_list
    df["RoundTripCost_Actual"] = round_trip_cost_list

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


def calculate_max_winning_streak(df):
    max_streak = 0
    current = 0
    for r in df["R"]:
        if r > 0:
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak


def calculate_max_dd_duration_days(df):
    """Longest stretch (calendar days) the equity curve spent below a
    prior peak before making a new high — i.e. how long you'd go
    without a fresh account high. Recovery Factor alone tells you
    magnitude of DD vs total edge, not how long you're stuck."""
    equity = df["Equity"]
    peak = equity.cummax()
    underwater = equity < peak
    dates = df["Entry Time"]

    max_duration_days = 0
    streak_start = None

    for i in range(len(df)):
        if underwater.iloc[i]:
            if streak_start is None:
                streak_start = dates.iloc[i - 1] if i > 0 else dates.iloc[i]
        else:
            if streak_start is not None:
                max_duration_days = max(max_duration_days, (dates.iloc[i] - streak_start).days)
                streak_start = None

    if streak_start is not None:
        max_duration_days = max(max_duration_days, (dates.iloc[-1] - streak_start).days)

    return max_duration_days


def print_key_metrics_table(df, window=20):
    """
    Single consolidated table of every decision-relevant metric.
    Replaces the old scattered CORE PERFORMANCE / RISK METRICS /
    TRADE QUALITY / ROLLING STATS sections.
    """
    total_trades = len(df)
    wins = (df["R"] > 0).sum()
    losses = (df["R"] < 0).sum()
    breakevens = (df["R"] == 0).sum()
    win_rate = wins / total_trades if total_trades > 0 else 0
    avg_win = df[df["R"] > 0]["R"].mean() if wins > 0 else 0
    avg_loss = df[df["R"] < 0]["R"].mean() if losses > 0 else 0
    avg_win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")
    expectancy_net = df["R"].mean()
    expectancy_gross = df["R_Gross"].mean() if "R_Gross" in df.columns else float("nan")
    best_trade_r = df["R"].max()
    worst_trade_r = df["R"].min()

    # Theoretical (pre-leverage-scaling) win/loss — what the setup itself
    # achieves in clean price terms, before position sizing shrinks it.
    # If this differs sharply from Avg Win/Loss (R) above, that gap is
    # driven by leverage/capital constraints (see % Trades
    # Leverage-Constrained), not the setup's underlying edge.
    has_theoretical = "R_Theoretical" in df.columns
    avg_win_theoretical = df[df["R_Theoretical"] > 0][
        "R_Theoretical"].mean() if has_theoretical and wins > 0 else float("nan")
    avg_loss_theoretical = df[df["R_Theoretical"] < 0][
        "R_Theoretical"].mean() if has_theoretical and losses > 0 else float("nan")

    gross_profit = df[df["PnL"] > 0]["PnL"].sum()
    gross_loss = abs(df[df["PnL"] < 0]["PnL"].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    max_dd_r = df["DD_R"].min()
    max_dd_amt = df["DD_PnL"].min()
    max_dd_pct = df["Drawdown_%"].min()
    total_r = df["R"].sum()
    recovery_factor = total_r / abs(max_dd_r) if max_dd_r != 0 else 0
    max_dd_duration_days = calculate_max_dd_duration_days(df)
    max_losing_streak = calculate_max_losing_streak(df)
    max_winning_streak = calculate_max_winning_streak(df)

    avg_mfe = df["MaxR_Execution"].mean()
    avg_mfe_full = df["MaxR_FullDay"].mean()
    avg_mae = df["MAE_R"].mean()
    pct_mae_beyond_half_r = (df["MAE_R"] < -0.5).mean() * 100
    avg_dur = df["Duration_Minutes"].mean()
    efficiency = (df["MaxR_Execution"] / df["MaxR_FullDay"].replace(0, float("nan"))).mean() * 100

    total_gross_pnl = df["Gross_PnL"].sum() if "Gross_PnL" in df.columns else float("nan")
    total_cost = (total_gross_pnl - df["PnL"].sum()) if "Gross_PnL" in df.columns else float("nan")
    cost_drag_pct = (total_cost / total_gross_pnl * 100) if total_gross_pnl not in (0, float("nan")) else float("nan")
    pct_leverage_constrained = (
            df["Leverage_Constrained"].mean() * 100) if "Leverage_Constrained" in df.columns else float("nan")

    # df["R"] is net (post-cost) by definition now, so total_r IS the net
    # figure. Gross R (pre-cost) needs its own calc from Gross_PnL, since
    # it's no longer equal to df["R"].sum(). Uses the global R constant.
    total_r_net = total_r  # alias for row-label clarity below
    total_r_gross = (total_gross_pnl / R) if R and total_gross_pnl == total_gross_pnl else float("nan")

    total_slippage_cost = df["SlippageCost_Actual"].sum() if "SlippageCost_Actual" in df.columns else float("nan")
    total_round_trip_cost = df["RoundTripCost_Actual"].sum() if "RoundTripCost_Actual" in df.columns else float("nan")
    participating_trades = (df["RoundTripCost_Actual"] > 0).sum() if "RoundTripCost_Actual" in df.columns else float(
        "nan")
    avg_cost_per_trade = (total_cost / participating_trades) if participating_trades else float("nan")

    start_date = df["Entry Time"].iloc[0]
    end_date = df["Entry Time"].iloc[-1]
    months_span = max((end_date - start_date).days / 30.44, 1e-6)
    trades_per_month = total_trades / months_span

    # Actual calendar-month trade counts (Jan, Feb, ... buckets), rather than
    # the /30.44-day approximation above. Used for Max/Min/Avg Trades per
    # Month. Note: the first and last buckets may be partial calendar months
    # if the backtest doesn't start/end exactly on the 1st, so Min can look
    # artificially low — check monthly_trade_counts.csv if that matters.
    monthly_trade_counts = df.groupby(
        df["Entry Time"].dt.tz_localize(None).dt.to_period("M")
        if df["Entry Time"].dt.tz is not None
        else df["Entry Time"].dt.to_period("M")
    ).size()
    max_trades_month = int(monthly_trade_counts.max()) if len(monthly_trade_counts) else 0
    min_trades_month = int(monthly_trade_counts.min()) if len(monthly_trade_counts) else 0
    avg_trades_month_actual = monthly_trade_counts.mean() if len(monthly_trade_counts) else 0.0

    if len(df) >= window:
        rolling_exp = df["R"].rolling(window).mean().iloc[-1]
        rolling_exp_gross = df["R_Gross"].rolling(window).mean().iloc[-1] if "R_Gross" in df.columns else float("nan")
        rolling_wr = (df["R"] > 0).rolling(window).mean().iloc[-1]
    else:
        rolling_exp, rolling_exp_gross, rolling_wr = float("nan"), float("nan"), float("nan")

    rows = [
        ("Performance", "Capital(₹)", f"{TRADING_CAPITAL}"),
        ("Performance", "R(₹)", f"{R}"),
        ("Performance", "Total Trades", f"{total_trades}"),
        ("Performance", "Wins / Losses / BE", f"{wins} / {losses} / {breakevens}"),
        ("Performance", "Win Rate", f"{win_rate:.1%}"),
        ("Performance", "Avg Win (R)", f"{avg_win:.2f}"),
        ("Performance", "Avg Win (R, Theoretical/Uncapped)",
         f"{avg_win_theoretical:.2f}" if avg_win_theoretical == avg_win_theoretical else "n/a"),
        ("Performance", "Avg Loss (R)", f"{avg_loss:.2f}"),
        ("Performance", "Avg Loss (R, Theoretical/Uncapped)",
         f"{avg_loss_theoretical:.2f}" if avg_loss_theoretical == avg_loss_theoretical else "n/a"),

        ("Performance", "Win/Loss Ratio", f"{avg_win_loss_ratio:.2f}"),
        ("Performance", "Expectancy (R, Gross, pre-cost)",
         f"{expectancy_gross:.2f}" if expectancy_gross == expectancy_gross else "n/a"),
        ("Performance", "Expectancy (₹, Gross, pre-cost)",
         f"{round(expectancy_gross * R)}" if expectancy_gross == expectancy_gross else "n/a"),
        ("Performance", "Expectancy (R, Net, post-cost)", f"{expectancy_net:.2f}"),
        ("Performance", "Expectancy (₹, Net, post-cost)", f"{round(expectancy_net * R)}"),
        ("Performance", "Profit Factor", f"{profit_factor:.2f}"),
        ("Performance", "Best / Worst Trade (R)", f"{best_trade_r:.2f} / {worst_trade_r:.2f}"),
        ("Performance", "Total R (Gross, pre-cost)",
         f"{total_r_gross:.2f}" if total_r_gross == total_r_gross else "n/a"),
        ("Performance", "Total R (Net, post-cost)", f"{total_r_net:.2f}"),
        ("Performance", "Total PnL (₹, net)", f"₹{df['PnL'].sum():,.0f}"),
        ("Risk", "Max Drawdown (R)", f"{max_dd_r:.2f}"),
        ("Risk", "Max Drawdown (₹)", f"₹{max_dd_amt:,.0f}"),
        ("Risk", "Max Drawdown (%)", f"{max_dd_pct:.2f}%"),
        ("Risk", "Max DD Duration (days)", f"{max_dd_duration_days}"),
        ("Risk", "Recovery Factor", f"{recovery_factor:.2f}"),
        ("Risk", "Max Losing Streak", f"{max_losing_streak}"),
        ("Risk", "Max Winning Streak", f"{max_winning_streak}"),
        ("Trade Quality", "Avg MFE Execution (R)", f"+{avg_mfe:.2f}"),
        ("Trade Quality", "Avg MFE Full Day (R)", f"+{avg_mfe_full:.2f}"),
        ("Trade Quality", "Capture Efficiency", f"{efficiency:.2f}%"),
        ("Trade Quality", "Avg MAE (R)", f"{avg_mae:.2f}"),
        ("Trade Quality", "% Trades MAE > 0.5R", f"{pct_mae_beyond_half_r:.2f}%"),
        ("Trade Quality", "Avg Duration (min)", f"{avg_dur:.2f}"),
        ("Costs", "Total Flat Brokerage/STT (₹)",
         f"₹{total_round_trip_cost:,.0f}" if total_round_trip_cost == total_round_trip_cost else "n/a"),
        ("Costs", "Total Slippage Cost (₹)",
         f"₹{total_slippage_cost:,.0f}" if total_slippage_cost == total_slippage_cost else "n/a"),
        ("Costs", "Total Cost (₹)", f"₹{total_cost:,.0f}" if total_cost == total_cost else "n/a"),
        ("Costs", "Avg Cost / Trade (₹)",
         f"₹{avg_cost_per_trade:,.0f}" if avg_cost_per_trade == avg_cost_per_trade else "n/a"),
        ("Costs", "Cost Drag (% of Gross PnL)", f"{cost_drag_pct:.2f}%" if cost_drag_pct == cost_drag_pct else "n/a"),
        ("Risk", "% Trades Leverage-Constrained",
         f"{pct_leverage_constrained:.2f}%" if "Leverage_Constrained" in df.columns else "n/a"),
        ("Frequency", "Avg Trades / Month (span-based)", f"{trades_per_month:.2f}"),
        ("Frequency", "Avg Trades / Month (calendar)", f"{avg_trades_month_actual:.2f}"),
        ("Frequency", "Max Trades / Month", f"{max_trades_month}"),
        ("Frequency", "Min Trades / Month", f"{min_trades_month}"),
        ("Recent Edge", f"Rolling {window}-Trade Expectancy (Gross)",
         f"{rolling_exp_gross:.2f} R" if rolling_exp_gross == rolling_exp_gross else "n/a"),
        ("Recent Edge", f"Rolling {window}-Trade Expectancy (Net)",
         f"{rolling_exp:.2f} R" if rolling_exp == rolling_exp else "n/a"),
        ("Recent Edge", f"Rolling {window}-Trade Win Rate", f"{rolling_wr:.1%}" if rolling_wr == rolling_wr else "n/a"),
    ]

    table = pd.DataFrame(rows, columns=["Category", "Metric", "Value"]).drop(columns="Category")

    print("\n=======================================================")
    print("  KEY METRICS SUMMARY")
    print("=======================================================")
    print(table.to_string(index=False))

    # CSV export — full rolling series kept separately for charting trend
    os.makedirs(REPORT_FOLDER, exist_ok=True)
    table.to_csv(os.path.join(REPORT_FOLDER, "key_metrics_summary.csv"), index=False)

    # Per-calendar-month trade counts, so Max/Min/Avg Trades per Month above
    # can be traced back to the actual months driving them.
    monthly_counts_df = monthly_trade_counts.rename("Trades").reset_index()
    monthly_counts_df.columns = ["Month", "Trades"]
    monthly_counts_df["Month"] = monthly_counts_df["Month"].astype(str)
    monthly_counts_df.to_csv(os.path.join(REPORT_FOLDER, "monthly_trade_counts.csv"), index=False)

    if len(df) >= window:
        rolling_df = pd.DataFrame({
            "Trade_Index": df.index,
            "Entry_Time": df["Entry Time"].values,
            f"Rolling_{window}_Expectancy_R_Gross": df["R_Gross"].rolling(window).mean().round(3)
            if "R_Gross" in df.columns else float("nan"),
            f"Rolling_{window}_Expectancy_R_Net": df["R"].rolling(window).mean().round(3),
            f"Rolling_{window}_WinRate": (df["R"] > 0).rolling(window).mean().round(4),
        })
        rolling_df.to_csv(os.path.join(REPORT_FOLDER, "rolling_stats.csv"), index=False)


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
            Expectancy_R_Net=("R", lambda x: round(x.mean(), 2)),
            Total_R_Net=("R", lambda x: round(x.sum(), 2)),
            Total_PnL=("PnL", lambda x: round(x.sum(), 0)),
            ProfitFactor=("PnL",
                          lambda x: round(x[x > 0].sum() / abs(x[x < 0].sum()), 2)
                          if abs(x[x < 0].sum()) > 0 else float("inf")),
        )
        .sort_values("Expectancy_R_Net", ascending=False)
    )

    # Gross R (pre-cost) needs its own calc from Gross_PnL — R itself is
    # net now, so Total_R_Net above already ties out exactly to Total_PnL
    # (Total_R_Net x R == Total_PnL, by construction). Gross R is shown
    # separately purely to see the pre-cost setup quality.
    if "Gross_PnL" in df.columns:
        gross_pnl_by_setup = df.groupby("Setup")["Gross_PnL"].sum()
        summary["Total_R_Gross"] = (gross_pnl_by_setup / R).round(2)
        # Gross Expectancy(R) = mean of per-trade Gross R = Total_R_Gross / Trades,
        # the gross-side counterpart to Expectancy_R_Net above.
        summary["Expectancy_R_Gross"] = (summary["Total_R_Gross"] / summary["Trades"]).round(2)
    else:
        summary["Total_R_Gross"] = float("nan")
        summary["Expectancy_R_Gross"] = float("nan")
    summary = summary[[
        "Trades", "WinRate", "AvgWin_R", "AvgLoss_R",
        "Expectancy_R_Gross", "Expectancy_R_Net",
        "Total_R_Gross", "Total_R_Net", "Total_PnL", "ProfitFactor"
    ]]

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
            Expectancy_R_Net=("R", lambda x: round(x.mean(), 2)),
            Total_R_Net=("R", lambda x: round(x.sum(), 2)),
            Total_PnL=("PnL", lambda x: round(x.sum(), 0)),
            ProfitFactor=("PnL",
                          lambda x: round(x[x > 0].sum() / abs(x[x < 0].sum()), 2)
                          if abs(x[x < 0].sum()) > 0 else float("inf")),
        )
        .sort_index()
    )

    # Gross R (pre-cost) from Gross_PnL — see print_setup_summary for why
    # R itself (Total_R_Net here) already ties out exactly to Total_PnL.
    if "Gross_PnL" in df.columns:
        gross_pnl_by_grp = df.groupby(["Year", "Setup"])["Gross_PnL"].sum()
        yearly["Total_R_Gross"] = (gross_pnl_by_grp / R).round(1)
        # Gross Expectancy(R) = mean per-trade Gross R = Total_R_Gross / Trades.
        yearly["Expectancy_R_Gross"] = (yearly["Total_R_Gross"] / yearly["Trades"]).round(2)
    else:
        yearly["Total_R_Gross"] = float("nan")
        yearly["Expectancy_R_Gross"] = float("nan")
    yearly = yearly[[
        "Trades", "WinRate", "Expectancy_R_Gross", "Expectancy_R_Net",
        "Total_R_Gross", "Total_R_Net",
        "Total_PnL", "ProfitFactor"
    ]]

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


def print_target_hit_summary(df):
    """
    Breaks trades into three mutually exclusive buckets based on which
    target(s) they reached before exiting, regardless of the final exit
    reason (target / trailing-stop / SL / EOD):

      - Hit T2            : reached the final target (T1 was necessarily
                             hit first, since T2 only fires after partial)
      - Hit T1, not T2     : reached partial target but exited (SL/trail/EOD)
                             before ever reaching the final target
      - Never hit T1       : stopped out / closed at EOD without even
                             reaching the first target
    """
    total = len(df)

    if total == 0:
        print("\nNo trades to summarize for target-hit stats.")
        return

    hit_t2 = df["T2_Hit"] == True
    hit_t1_only = (df["T1_Hit"] == True) & (df["T2_Hit"] == False)
    hit_neither = df["T1_Hit"] == False

    n_t2 = int(hit_t2.sum())
    n_t1_only = int(hit_t1_only.sum())
    n_neither = int(hit_neither.sum())

    def _avg_r(mask, col="R"):
        return round(df.loc[mask, col].mean(), 2) if mask.any() else 0.0

    def _avg_dur(mask):
        return round(df.loc[mask, "Duration_Minutes"].mean(), 1) if mask.any() else 0.0

    def _win_rate(mask):
        return round((df.loc[mask, "R"] > 0).mean() * 100, 1) if mask.any() else 0.0

    has_gross = "R_Gross" in df.columns

    avg_r_t2 = _avg_r(hit_t2)
    avg_r_t1_only = _avg_r(hit_t1_only)
    avg_r_neither = _avg_r(hit_neither)

    avg_r_gross_t2 = _avg_r(hit_t2, "R_Gross") if has_gross else float("nan")
    avg_r_gross_t1_only = _avg_r(hit_t1_only, "R_Gross") if has_gross else float("nan")
    avg_r_gross_neither = _avg_r(hit_neither, "R_Gross") if has_gross else float("nan")

    avg_dur_t2 = _avg_dur(hit_t2)
    avg_dur_t1_only = _avg_dur(hit_t1_only)
    avg_dur_neither = _avg_dur(hit_neither)

    wr_t1_only = _win_rate(hit_t1_only)

    print("\n=======================================================")
    print("  TARGET HIT SUMMARY (T1 = partial target, T2 = final target)")
    print("=======================================================")
    print(f"  Total Trades         : {total}")
    print(
        f"  Hit T2               : {n_t2}  ({n_t2 / total * 100:.2f}%)  |  Avg R (Gross/Net): {avg_r_gross_t2:+.2f} / {avg_r_t2:+.2f}  |  Avg Dur: {avg_dur_t2:.2f} min")
    print(
        f"  Hit T1, not T2       : {n_t1_only}  ({n_t1_only / total * 100:.2f}%)  |  Avg R (Gross/Net): {avg_r_gross_t1_only:+.2f} / {avg_r_t1_only:+.2f}  |  Avg Dur: {avg_dur_t1_only:.2f} min  |  WinRate: {wr_t1_only:.2f}%")
    print(
        f"  Never hit T1         : {n_neither}  ({n_neither / total * 100:.2f}%)  |  Avg R (Gross/Net): {avg_r_gross_neither:+.2f} / {avg_r_neither:+.2f}  |  Avg Dur: {avg_dur_neither:.2f} min")

    # CSV export
    os.makedirs(REPORT_FOLDER, exist_ok=True)
    summary = pd.DataFrame({
        "Bucket": ["Hit T2", "Hit T1, not T2", "Never hit T1", "Total"],
        "Trades": [n_t2, n_t1_only, n_neither, total],
        "Pct": [
            round(n_t2 / total * 100, 1),
            round(n_t1_only / total * 100, 1),
            round(n_neither / total * 100, 1),
            100.0,
        ],
        "Avg_R_Gross": [
            avg_r_gross_t2, avg_r_gross_t1_only, avg_r_gross_neither,
            round(df["R_Gross"].mean(), 2) if has_gross else float("nan"),
        ],
        "Avg_R_Net": [avg_r_t2, avg_r_t1_only, avg_r_neither, round(df["R"].mean(), 2)],
        "Avg_Duration_Minutes": [
            avg_dur_t2, avg_dur_t1_only, avg_dur_neither,
            round(df["Duration_Minutes"].mean(), 1),
        ],
    })
    summary.to_csv(os.path.join(REPORT_FOLDER, "target_hit_summary.csv"), index=False)


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

    print_key_metrics_table(df)
    if exit_model == ExitModel.DYNAMIC:
        print_target_hit_summary(df)
    print_setup_summary(df)
    print_yearly_summary(df)

    plot_real_equity(df)

    df.to_csv("intraday_m5_backtest_results.csv", index=False)


# =========================================================

if __name__ == "__main__":
    initialize_logger(TradeType.INTRADAY, "m5", True)

    # load symbols and instrument token
    symbol_token_map = get_symbol_instrument_token(LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH)

    backtest_historical_data_parallel(symbol_token_map)