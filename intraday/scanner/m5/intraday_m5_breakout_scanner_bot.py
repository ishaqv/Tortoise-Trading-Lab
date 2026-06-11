from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from time import sleep

import numpy as np
import pandas as pd
from ta.volatility import AverageTrueRange

from intraday.scanner.m5.early_momentum_breakout_scanner import is_early_momentum_breakout_detected
from intraday.scanner.m5.volume_explosion_long_breakout_scanner import is_volume_explosion_long_breakout_detected
from util.entry_type import EntryType
from util.global_variables import *
from util.kite_util import get_bid_ask
from util.setup_type import IntradaySetupType
from util.telegram_bot import send_telegram_alert
from util.trade_logger import log
from util.trade_type import TradeType


def is_liquid_breakout(breakout_candle):
    breakout_value = (
            breakout_candle['close'] *
            breakout_candle['volume']
    )

    if breakout_value <= 0:
        return False

    buying_power = (
            TRADING_CAPITAL *
            INTRADAY_LEVERAGE_MULTIPLIER
    )

    participation_rate = (
            buying_power / breakout_value
    )

    return participation_rate <= MAX_BREAKOUT_PARTICIPATION


def get_previous_day_data(df):
    date_only = df['trade_date'].dt.date
    unique_dates = date_only.unique()

    if len(unique_dates) < 2:
        return df.iloc[0:0].copy()  # empty DataFrame with same structure

    yesterday = unique_dates[-2]
    return df[date_only == yesterday].copy()


def calculate_gap(df_trading_day, df_previous_day):
    today_open = df_trading_day.iloc[0].open
    yesterday_close = df_previous_day.iloc[-1].close
    gap = abs(today_open - yesterday_close)
    return gap


def is_valid_gap_opening(df_trading_day, df_previous_day, max_gap_in_atr=3):
    if len(df_previous_day) < 1:
        return True  # allow first day
    gap = calculate_gap(df_trading_day, df_previous_day)
    atr = df_trading_day.iloc[0].atr  # ATR from first candle
    gap_in_atr = gap / atr
    return gap_in_atr < max_gap_in_atr


def analyze_stock_for_setup(symbol,
                            df,
                            trading_day=date.today(),
                            is_backtesting=False):
    """
    Analyzes intraday stock data to detect potential breakout setups
    and sends a trade alert if a valid setup is found.

    This function evaluates the latest candle of the given trading day to check
    for high-conviction breakout conditions using multiple technical signals such
    as candle strength, volume confirmation.
    """

    try:
        log("info", "--------------------------------")
        # Filter trading day's data
        df_trading_day = df[df['trade_date'].dt.date == trading_day].copy()

        if len(df_trading_day) < 1:
            return None

        breakout_candle = df_trading_day.iloc[BREAKOUT_CANDLE_IDX]

        if not is_liquid_breakout(breakout_candle):
            log("info", f"Skipping – illiquid stock {symbol}")
            return None

        df_previous_day = get_previous_day_data(df)

        if not is_valid_gap_opening(df_trading_day, df_previous_day):
            log("info", f"Skipping – huge opening gap detected in stock {symbol}")
            return None

        breakout_candle_date_time = breakout_candle['trade_date']
        breakout_time = breakout_candle_date_time.time()

        log("info", f"Evaluating {symbol} | breakout_candle: {breakout_candle_date_time}")

        setup_type = None
        entry_type = None

        is_breakout_detected = False

        if breakout_time == EVB_SCAN_CANDLE_TIME:
            #  1 EMB LONG
            if is_early_momentum_breakout_detected(breakout_candle):
                setup_type = IntradaySetupType.EMB
                entry_type = EntryType.LONG
                is_breakout_detected = True


            # 2 EVB LONG
            elif is_volume_explosion_long_breakout_detected(breakout_candle):
                setup_type = IntradaySetupType.EVB
                entry_type = EntryType.LONG
                is_breakout_detected = True

        if is_breakout_detected:
            breakout_atr = breakout_candle['atr']
            risk_per_share = get_risk_per_share(breakout_atr)
            if is_backtesting:
                return {
                    'Symbol': symbol,
                    'Date': breakout_candle_date_time,
                    "Day": breakout_candle_date_time.strftime("%A"),
                    'Setup': setup_type.name,
                    'Entry Type': entry_type.name,
                    'Risk': risk_per_share
                }

            if not is_spread_acceptable(symbol, breakout_atr):
                message = f"Breakout rejected for {symbol} — spread too wide"
                log("warning", message)
                send_telegram_alert(message)
                return None

            entry_type_icon = "🟢" if entry_type == EntryType.LONG else "🔴"

            message = (
                f"{entry_type_icon} <b>{entry_type.name} SETUP DETECTED</b>\n\n\n"
                f"📌 <b>Symbol : </b> {symbol}\n\n"
                f"🧠 <b>Setup : </b> {setup_type.name}\n\n"
                f"⚡ <b>Trade : </b> {TradeType.INTRADAY.name}\n\n\n"
                f"⚠️ Risk : {risk_per_share} pips\n\n"
                f"🎯 Target : {round(risk_per_share * INTRADAY_M5_TARGET_MULTIPLIER, 1)} pips\n"
            )

            send_telegram_alert(message)
            log("info", message)

    except Exception as e:
        log("error", f"Error in analyzing stock {symbol}: {e}", exc_info=True)


def add_technical_indicators(df):
    df['atr'] = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()
    df['volume_sma_20'] = df['volume'].shift(1).rolling(window=20).mean()


def process_stock(symbol, stock_data_df):
    """Processes a single stock symbol safely with exception handling."""
    try:
        if stock_data_df is not None and len(stock_data_df) >= INTRADAY_M5_CANDLE_LIMIT:
            add_technical_indicators(stock_data_df)
            analyze_stock_for_setup(symbol, stock_data_df)
    except Exception as e:
        log("error", f"Error processing stock {symbol}: {e}", exc_info=True)


def run_intraday_screener(symbol_df_map: dict[str, pd.DataFrame]) -> None:
    """
    Runs the intraday breakout screener in parallel across all symbols.
    MAX_WORKERS: tune based on number of CPU cores available.
    """
    log("info", f"Starting screener with {MAX_WORKERS} workers for {len(symbol_df_map)} symbols.")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_stock, symbol, df): symbol
            for symbol, df in symbol_df_map.items()
        }

        for future in as_completed(futures):
            symbol = futures[future]
            try:
                future.result()
            except Exception as e:
                log("exception", f"Thread error in {symbol}: {e}")

    log("info", "Screener completed.")


def get_risk_per_share(breakout_atr):
    """
    """
    return round(breakout_atr * ATR_RISK_MULTIPLIER, 1)


def get_spread_atr_ratio(symbol, atr, samples=5, delay=0.2):
    """
    Stable spread/ATR ratio using median spread sampling.
    """
    if atr <= 0:
        return None

    spreads = []

    for _ in range(samples):
        bid, ask = get_bid_ask(symbol)

        if 0 < bid <= ask and ask > 0:
            spreads.append(ask - bid)

        sleep(delay)

    if not spreads:
        return None

    median_spread = np.median(spreads)

    return round(median_spread / atr, 4)


def is_spread_acceptable(symbol, atr):
    """
    Returns True if the spread/ATR ratio is within acceptable limits.
    """
    ratio = get_spread_atr_ratio(symbol, atr)

    if ratio is None:
        return False  # Reject if spread data unavailable

    return ratio <= NSE_MAX_SPREAD_ATR_RATIO
