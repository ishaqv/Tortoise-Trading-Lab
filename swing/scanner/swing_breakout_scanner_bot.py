from concurrent.futures import ThreadPoolExecutor, as_completed
from math import ceil

import pandas as pd
from ta.volatility import AverageTrueRange

from swing.scanner.compressed_range_breakout_scanner import is_compressed_range_breakout_detected
from swing.scanner.volume_explosion_breakout_scanner import is_volume_explosion_breakout_detected
from util.db_util import fetch_data
from util.global_variables import *
from util.kite_util import place_buy_with_sl
from util.setup_type import SwingSetupType
from util.telegram_bot import send_telegram_alert
from util.trade_logger import log
from util.trade_type import TradeType


def is_liquid_stock(breakout_candle):
    """
    Liquidity filter combines daily ADV check with breakout-candle INR turnover.
    """
    price = breakout_candle['close']
    breakout_vol = breakout_candle['volume']
    breakout_inr = breakout_vol * price
    liquidity_ratio = ceil(breakout_inr / TRADING_CAPITAL)
    return liquidity_ratio > MIN_LIQUIDITY_RATIO


def analyze_stock_for_setup(symbol,
                            df,
                            is_backtesting=False):
    """
    Analyzes stock data to detect potential swing setups
    (compression) and sends a trade alert if a valid setup is found.

    This function evaluates the latest candle of the given trading day to check
    for high-conviction breakout conditions using multiple technical signals such
    as candle strength, volume confirmation, resistance break, and structure.


    Key Checks Performed:
        1. Strong breakout candle (e.g., full-body bullish candle).
        2. Strong volume confirmation (based on setup type: ORB or VWAP).
        3. Key resistance level breakout.
        4. Compression breakout

    If all conditions are met and the confidence score exceeds a threshold, the
    function:
        - Calculates position size and entry details.
        - Formats and logs a detailed message.
        - Sends the trade setup as a Telegram alert.
    """

    try:

        log("info", "--------------------------------")
        breakout_candle = df.iloc[BREAKOUT_CANDLE_IDX]
        breakout_candle_date_time = breakout_candle['date']

        log("info", f"Evaluating {symbol} | breakout_candle: {breakout_candle_date_time}")

        if not is_liquid_stock(breakout_candle):
            log("info", f"Skipping – illiquid stock {symbol}")
            return None
        # ---------------------------------------------------------------------------------------------------------
        detected_setup = None

        if is_compressed_range_breakout_detected(df):
            detected_setup = SwingSetupType.CRB.name

        elif is_volume_explosion_breakout_detected(breakout_candle):
            detected_setup = SwingSetupType.VEB.name

        if detected_setup is not None:
            position = calculate_position(df)

            if is_backtesting:
                return {
                    'Symbol': symbol,
                    'Date': breakout_candle_date_time,
                    "Day": breakout_candle_date_time.strftime("%A"),
                    'Setup': detected_setup,
                    'Entry': position['entry'],
                    'Qty': position["qty"],
                    'SL': position['sl'],
                    'Risk': position['risk_per_share']
                }

            message = (
                f"Setup Detected!\n\n"
                f"Trade Type: {TradeType.SWING.name} \n\n"
                f"Setup Type: {detected_setup} \n\n"
                f"Symbol: {symbol}\n\n"
                f"Entry Price: {position['entry']}\n\n"
                f"Quantity: {position['qty']}\n\n"
                f"Stop Loss: {position['sl']}\n\n"
                f"Risk/Share: {position['risk_per_share']}"
            )

            send_telegram_alert(message)
            log("info", message)

            if SWING_IS_AUTOMATIC_ENTRY_ENABLED:
                place_buy_with_sl(symbol, position["qty"], position['entry'], position['sl'],
                                  df.iloc[BREAKOUT_CANDLE_IDX]['atr'])

    except Exception as e:
        log("exception", f"Error processing stock {symbol}: {e}")


def add_technical_indicators(df):
    df['atr'] = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()
    df['volume_sma_20'] = df['volume'].shift(1).rolling(window=20).mean()


def process_stock(symbol, table_name):
    """Processes a single stock symbol safely with exception handling."""
    try:
        stock_data_df = get_stock_dataframe(symbol, table_name)

        if stock_data_df is not None and len(stock_data_df) >= INTRADAY_M15_CANDLE_LIMIT:
            add_technical_indicators(stock_data_df)
            analyze_stock_for_setup(symbol, stock_data_df)
    except Exception as e:
        log("exception", f"Error processing stock {symbol}: {e}")


def run_swing_screener_parallel(symbols, table_name):
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

    data = fetch_data(table_name, symbol, SWING_CANDLE_LIMIT)

    df = pd.DataFrame(data, columns=['id', 'symbol', 'date', 'open', 'high', 'low', 'close', 'volume'])

    # Clean & convert
    numeric_cols = ['open', 'high', 'low', 'close', 'volume']
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors='coerce')
    df['date'] = pd.to_datetime(df['date'])

    df = df.dropna().sort_values('date', ascending=True)
    return df


def calculate_position(df):
    """
    Calculates position size, entry price, stop-loss (SL), and risk per share
    for a breakout trade with balanced risk management and capital utilisation.
    """

    breakout_candle = df.iloc[BREAKOUT_CANDLE_IDX]
    entry = round(breakout_candle['close'])
    sl = round(entry - breakout_candle['atr'] * 1.5)

    risk_per_share = round(entry - sl)

    if risk_per_share <= 0:
        return {
            "entry": entry,
            "sl": sl,
            "qty": 0,
            "risk_per_share": risk_per_share
        }

    # Risk-based and capital-based qty
    risk_amount = TRADING_CAPITAL * MAX_RISK_PER_TRADE_PERCENT
    risk_based_qty = risk_amount / risk_per_share
    capital_based_qty = TRADING_CAPITAL / entry
    raw_qty = min(risk_based_qty, capital_based_qty)
    if raw_qty > 10:
        quantity = round(raw_qty / 10.0) * 10
    else:
        quantity = ceil(raw_qty)

    return {
        "entry": entry,
        "sl": sl,
        "qty": int(quantity),
        "risk_per_share": risk_per_share
    }