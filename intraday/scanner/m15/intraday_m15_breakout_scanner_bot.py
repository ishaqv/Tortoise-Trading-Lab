from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from math import ceil, floor

import pandas as pd
from ta.volatility import AverageTrueRange

from intraday.scanner.m15.explosive_volume_m15_breakout_scanner import is_volume_explosion_breakout_detected
from util.db_util import fetch_data
from util.global_variables import *
from util.kite_util import place_buy_with_sl
from util.setup_type import IntradaySetupType
from util.telegram_bot import send_telegram_alert
from util.trade_logger import log
from util.trade_type import TradeType


def is_liquid_stock(breakout_candle,
                    adv=None,
                    min_adv_multiple=20,
                    min_candle_adv_pct=0.02):
    """
    Liquidity filter combines daily ADV check with breakout-candle INR turnover.
    """
    price = breakout_candle['close']
    breakout_vol = breakout_candle['volume']
    breakout_inr = breakout_vol * price

    if not adv:
        liquidity_ratio = ceil(breakout_inr / TRADING_CAPITAL * INTRADAY_LEVERAGE_MULTIPLIER)
        return liquidity_ratio > MIN_LIQUIDITY_RATIO

    adv_inr = adv * price

    # --- Daily layer ---
    if adv_inr < TRADING_CAPITAL * min_adv_multiple:
        return False

    # --- candle layer ---
    if breakout_inr < min_candle_adv_pct * adv_inr:
        return False

    return True


def get_previous_day_data(df):
    date_only = df['date'].dt.date
    unique_dates = date_only.unique()
    yesterday = unique_dates[-2]
    return df[df['date'].dt.date == yesterday].copy()


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
    (either ORB or VWAP) and sends a trade alert if a valid setup is found.

    This function evaluates the latest candle of the given trading day to check
    for high-conviction breakout conditions using multiple technical signals such
    as candle strength, volume confirmation, resistance break, and structure.


    Key Checks Performed:
        1. Strong breakout candle (e.g., full-body bullish candle).
        2. Strong volume confirmation (based on setup type: ORB or VWAP).
        3. Key resistance level breakout.
        4. Presence of higher-high, higher-low structure (bullish trend structure).
        5. Specific logic for either:
           - ORB breakout: Early morning breakout of initial range.
           - VWAP breakout: Volume-supported breakout above VWAP later in the session.

    If all conditions are met and the confidence score exceeds a threshold, the
    function:
        - Calculates position size and entry details.
        - Formats and logs a detailed message.
        - Sends the trade setup as a Telegram alert.
    """

    try:
        # Filter trading day's data
        df_trading_day = df[df['date'].dt.date == trading_day].copy()

        if len(df_trading_day) < 1:
            return None

        log("info", "--------------------------------")
        breakout_candle = df_trading_day.iloc[BREAKOUT_CANDLE_IDX]

        if not is_liquid_stock(breakout_candle):
            log("info", f"Skipping – illiquid stock {symbol}")
            return None

        df_previous_day = get_previous_day_data(df)

        if not is_valid_gap_opening(df_trading_day, df_previous_day):
            log("info", f"Skipping – huge gapup opening stock {symbol}")
            return None

        breakout_candle_date_time = breakout_candle['date']
        breakout_time = breakout_candle_date_time.time()

        log("info", f"Evaluating {symbol} | breakout_candle: {breakout_candle_date_time}")

        setup_type = None
        is_breakout_detected = False

        # ---------------------------------------------------------------------------------------------------------

        # 1️⃣ VEB
        if not is_breakout_detected and breakout_time == EVB_SCAN_CANDLE_TIME:
            if is_volume_explosion_breakout_detected(breakout_candle):
                setup_type = IntradaySetupType.EVB_M15
                is_breakout_detected = True

        if is_breakout_detected:
            position = calculate_position(df_trading_day)
            if not position:
                return None

            if is_backtesting:
                return {
                    'Symbol': symbol,
                    'Date': breakout_candle_date_time,
                    "Day": breakout_candle_date_time.strftime("%A"),
                    'Setup': setup_type.name,
                    'Qty': position["qty"],
                    'Risk': position['risk_per_share']
                }

            message = (
                f"Setup Detected!\n\n"
                f"Trade Type: {TradeType.INTRADAY.name} \n\n"
                f"Type: {setup_type.name} \n\n"
                f"Symbol: {symbol}\n\n"
                f"Quantity: {position['qty']}\n\n"
                f"Risk: {position['risk_per_share']} pips\n\n"
                f"Target: {round(position['risk_per_share'] * INTRADAY_M15_TARGET_MULTIPLIER, 1)} pips \n\n"
            )

            send_telegram_alert(message)
            log("info", message)

            if INTRADAY_IS_AUTOMATIC_ENTRY_ENABLED:
                place_buy_with_sl(symbol, position["qty"], position['entry'], position['sl'],
                                  df_trading_day.iloc[BREAKOUT_CANDLE_IDX]['atr'])

    except Exception as e:
        log("exception", f"Error processing stock {symbol}: {e}")


def add_technical_indicators(df):
    df['atr'] = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()
    df['volume_sma_20'] = df['volume'].shift(1).rolling(window=20).mean()


def process_stock(symbol, table_name):
    """Processes a single stock symbol safely with exception handling."""
    try:
        stock_data_df = get_stock_dataframe(symbol, table_name)

        if stock_data_df is not None and len(stock_data_df) >= INTRADAY_M15_CANDLE_LIMIT / 2:
            add_technical_indicators(stock_data_df)
            analyze_stock_for_setup(symbol, stock_data_df)
    except Exception as e:
        log("exception", f"Error processing stock {symbol}: {e}")


def run_intraday_m15_screener_parallel(symbols, table_name):
    """
    Runs the intraday breakout screener for a list of stock symbols in parallel.
    MAX_WORKERS: number of concurrent threads to use (Decide based based of no of CPU cores)
    """
    log("info", f"Starting parallel screener with {MAX_WORKERS} workers for {len(symbols)} symbols.")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_stock, symbol, table_name): symbol for symbol in symbols}

        for future in as_completed(futures):
            symbol = futures[future]
            try:
                future.result()  # Retrieve exceptions if any
            except Exception as e:
                log("exception", f"Thread error in {symbol}: {e}")

    log("info", "Parallel screener completed.")


def get_stock_dataframe(symbol, table_name):
    """
    Fetches intraday stock data for the given symbol from the database
    and returns a cleaned and sorted pandas DataFrame.
    """

    data = fetch_data(table_name, symbol, INTRADAY_M15_CANDLE_LIMIT)

    df = pd.DataFrame(data, columns=['id', 'symbol', 'date', 'open', 'high', 'low', 'close', 'volume'])

    # Clean & convert
    numeric_cols = ['open', 'high', 'low', 'close', 'volume']
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors='coerce')
    df['date'] = pd.to_datetime(df['date'])

    df = df.dropna().sort_values('date', ascending=True)
    return df


def calculate_position(df):
    """
    Calculates position size using:
    - 1% risk of real trading capital
    - 5x leverage for buying power
    """

    risk_per_share = df["atr"].iloc[BREAKOUT_CANDLE_IDX] * ATR_RISK_MULTIPLIER

    if risk_per_share <= 0:
        return None

    entry_price = df["high"].iloc[BREAKOUT_CANDLE_IDX]

    # REAL risk (based on equity)
    risk_amount = TRADING_CAPITAL * MAX_RISK_PER_TRADE_PERCENT

    # Buying power (equity × leverage)
    buying_power = TRADING_CAPITAL * 5

    # Risk-based qty
    risk_based_qty = risk_amount / risk_per_share

    # Capital-based qty (using leverage)
    capital_based_qty = buying_power / entry_price

    raw_qty = min(risk_based_qty, capital_based_qty)

    if raw_qty > 10:
        raw_qty = round(raw_qty / 10.0) * 10

    return {
        "qty": floor(raw_qty),
        "risk_per_share": round(risk_per_share, 1),
    }
