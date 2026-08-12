from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from time import sleep

import math
import numpy as np
import pandas as pd
from ta.volatility import AverageTrueRange

from intraday.scanner.m5.early_momentum_breakout_scanner import is_early_momentum_breakout_detected
from intraday.scanner.m5.volume_explosion_long_breakout_scanner import is_volume_explosion_long_breakout_detected
from util.entry_type import EntryType
from util.global_variables import *
from util.kite_util import get_best_bid_ask, get_market_depth
from util.setup_type import IntradaySetupType
from util.telegram_bot import send_telegram_alert
from util.trade_logger import log
from util.trade_type import TradeType


def get_previous_day_data(df):
    date_only = df['trade_date'].dt.date
    unique_dates = date_only.unique()

    if len(unique_dates) < 2:
        return df.iloc[0:0].copy()  # empty DataFrame with same structure

    yesterday = unique_dates[-2]
    return df[date_only == yesterday].copy()


def calculate_opening_gap(df_trading_day, df_previous_day):
    today_open = df_trading_day.iloc[0].open
    yesterday_close = df_previous_day.iloc[-1].close

    if yesterday_close <= 0:
        return 0.0

    gap_pct = round(
        abs(today_open - yesterday_close) / yesterday_close * 100,
        1
    )

    return gap_pct


def analyze_stock_for_setup(symbol,
                            df,
                            trading_day=date.today(),
                            is_backtesting=False,
                            is_forward_testing=False):
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

        breakout_candle_date_time = breakout_candle['trade_date']
        breakout_time = breakout_candle_date_time.time()

        log("info", f"Evaluating {symbol} | breakout_candle: {breakout_candle_date_time}")

        df_previous_day = get_previous_day_data(df)
        opening_gap_pct = calculate_opening_gap(df_trading_day, df_previous_day)
        breakout_atr = breakout_candle['atr']
        risk_per_share = get_risk_per_share(breakout_atr)
        tradable_qty = get_tradable_quantity(breakout_candle)
        participation_rate = get_participation_rate(breakout_candle, tradable_qty)

        setup_type = None
        entry_type = None

        is_breakout_detected = False

        if breakout_time == EVB_SCAN_CANDLE_TIME:

            #  EVB LONG
            if is_volume_explosion_long_breakout_detected(breakout_candle, participation_rate, opening_gap_pct):
                setup_type = IntradaySetupType.EVB
                entry_type = EntryType.LONG
                is_breakout_detected = True

            # EMB LONG
            elif is_early_momentum_breakout_detected(breakout_candle, participation_rate, opening_gap_pct):
                setup_type = IntradaySetupType.EMB
                entry_type = EntryType.LONG
                is_breakout_detected = True

        if is_breakout_detected:

            if is_backtesting:
                return {
                    'Symbol': symbol,
                    'Date': breakout_candle_date_time,
                    "Day": breakout_candle_date_time.strftime("%A"),
                    'Setup': setup_type.name,
                    'Entry Type': entry_type.name,
                    'Risk': risk_per_share
                }

            if is_forward_testing:
                log("info", f"{setup_type.name} setup detected for {symbol}")
                return None

            spread_atr_ratio = get_spread_atr_ratio(symbol, breakout_atr)
            if not is_spread_acceptable(spread_atr_ratio, participation_rate):
                message = f"{setup_type.name} breakout rejected for {symbol} — spread_atr ratio {round(spread_atr_ratio * 100, 1)}% is too wide for the participation rate {round(participation_rate * 100, 1)}%"
                log("warning", message)
                send_telegram_alert(message)
                return None

            entry_type_icon = "🟢" if entry_type == EntryType.LONG else "🔴"

            message = (
                f"{entry_type_icon} <b>{entry_type.name} SETUP DETECTED</b>\n\n\n"
                f"📌 <b>Symbol : </b> {symbol}\n\n"
                f"🧠 <b>Setup : </b> {setup_type.name}\n\n"
                f"⚡ <b>Trade : </b> {TradeType.INTRADAY.name}\n\n\n"
                f"⚠️ <b>Risk : </b> {risk_per_share} pips\n\n"
                f"📊 <b>Participation Rate : </b> {round(participation_rate * 100, 1)}%\n\n"
                f"📐 <b>Spread-ATR Ratio : </b> {round(spread_atr_ratio * 100, 1)}%\n\n"
                f"💸 <b>Impact Cost/Risk : </b> {round(get_impact_cost(symbol, tradable_qty, entry_type.name, risk_per_share) * 100, 1)}%\n\n"
            )

            send_telegram_alert(message)
            log("info", message)

    except Exception as e:
        log("error", f"Error in analyzing stock {symbol}: {e}", exc_info=True)


def get_tradable_quantity(breakout_candle):
    # Use the expected entry price
    breakout_price = breakout_candle["high"]

    breakout_value = breakout_price * breakout_candle["volume"]
    if breakout_value <= 0:
        return float("inf")  # Always fail liquidity filter

    # Risk per share
    risk_per_share = (
            breakout_candle["atr"] *
            INTRADAY_M5_ATR_RISK_MULTIPLIER
    )

    if risk_per_share <= 0:
        return float("inf")

    # Available buying power
    buying_power = (
            TRADING_CAPITAL *
            INTRADAY_LEVERAGE_MULTIPLIER
    )

    # Maximum ₹ risk per trade
    R = (
            TRADING_CAPITAL *
            MAX_RISK_PER_TRADE_PERCENT
    )

    # Risk-based quantity
    risk_based_qty = R / risk_per_share

    # Capital-based quantity
    capital_based_qty = buying_power / breakout_price

    # Actual tradable quantity (whole shares only)
    tradable_qty = math.floor(
        min(risk_based_qty, capital_based_qty)
    )

    if tradable_qty <= 0:
        return float("inf")
    return tradable_qty


def get_participation_rate(breakout_candle, tradable_qty):
    # Use the expected entry price
    breakout_price = breakout_candle["high"]

    breakout_value = breakout_price * breakout_candle["volume"]
    if breakout_value <= 0:
        return float("inf")  # Always fail liquidity filter

    # Actual order value
    order_value = tradable_qty * breakout_price

    # Percent of breakout candle liquidity consumed
    participation_rate = round(
        (order_value / breakout_value) * 100,
        1
    )

    return participation_rate


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
    return round(breakout_atr * INTRADAY_M5_ATR_RISK_MULTIPLIER, 1)


def get_spread_atr_ratio(symbol, atr, samples=5, delay=0.2):
    """
    Stable spread/ATR ratio using median spread sampling.
    """
    if atr <= 0:
        return None

    spreads = []

    for _ in range(samples):
        bid, ask = get_best_bid_ask(symbol)

        if 0 < bid <= ask and ask > 0:
            spreads.append(ask - bid)

        sleep(delay)

    if not spreads:
        return None

    median_spread = np.median(spreads)

    return round(median_spread / atr, 4)


def is_spread_acceptable(spread_atr_ratio, participation_rate):
    """
    Returns True if the spread/ATR ratio is acceptable
    for the given participation rate.

    Lower participation rate = better liquidity.
    """

    if spread_atr_ratio is None:
        return False

    if participation_rate is None:
        return False

    if participation_rate <= 1.0:
        max_spread_atr_ratio = NSE_MAX_SPREAD_ATR_RATIO

    elif participation_rate <= 3.0:
        max_spread_atr_ratio = 0.10

    elif participation_rate <= 5.0:
        max_spread_atr_ratio = 0.075

    else:
        # Normally rejected by the separate participation filter
        max_spread_atr_ratio = 0.02

    return spread_atr_ratio <= max_spread_atr_ratio


def get_impact_cost(
        symbol,
        quantity,
        direction,
        risk_per_share,
        samples=5,
        delay=0.2
):
    """
    Estimate execution impact cost in R for the actual order quantity
    using Kite's 5-level market depth.

    LONG  -> consumes ask/sell side
    SHORT -> consumes bid/buy side

    Impact R =
        execution impact per share / risk per share

    Returns:
        Median estimated impact cost in R.
        Returns None if impact cost cannot be calculated.

    Any error is logged silently and does not interrupt execution.
    """

    try:
        if quantity <= 0 or risk_per_share <= 0:
            return None

        direction = direction.upper().strip()

        if direction not in ("LONG", "SHORT"):
            return None

        impacts_r = []

        for _ in range(samples):

            try:

                depth = get_market_depth(symbol)

                bids = depth.get("buy", [])
                asks = depth.get("sell", [])

                if not bids or not asks:
                    sleep(delay)
                    continue

                best_bid = bids[0]["price"]
                best_ask = asks[0]["price"]

                if (
                        best_bid <= 0
                        or best_ask <= 0
                        or best_bid > best_ask
                ):
                    sleep(delay)
                    continue

                mid_price = (best_bid + best_ask) / 2

                # -------------------------------------------------
                # LONG -> Consume ASK side
                # -------------------------------------------------

                if direction == "LONG":

                    remaining_qty = quantity
                    execution_value = 0.0

                    asks_sorted = sorted(
                        asks,
                        key=lambda x: x["price"]
                    )

                    for level in asks_sorted:

                        price = level["price"]
                        available_qty = level["quantity"]

                        if price <= 0 or available_qty <= 0:
                            continue

                        fill_qty = min(
                            remaining_qty,
                            available_qty
                        )

                        execution_value += fill_qty * price
                        remaining_qty -= fill_qty

                        if remaining_qty <= 0:
                            break

                    if remaining_qty > 0:
                        continue

                    execution_vwap = execution_value / quantity

                    impact_per_share = (
                            execution_vwap - mid_price
                    )

                # -------------------------------------------------
                # SHORT -> Consume BID side
                # -------------------------------------------------

                else:

                    remaining_qty = quantity
                    execution_value = 0.0

                    bids_sorted = sorted(
                        bids,
                        key=lambda x: x["price"],
                        reverse=True
                    )

                    for level in bids_sorted:

                        price = level["price"]
                        available_qty = level["quantity"]

                        if price <= 0 or available_qty <= 0:
                            continue

                        fill_qty = min(
                            remaining_qty,
                            available_qty
                        )

                        execution_value += fill_qty * price
                        remaining_qty -= fill_qty

                        if remaining_qty <= 0:
                            break

                    if remaining_qty > 0:
                        continue

                    execution_vwap = execution_value / quantity

                    impact_per_share = (
                            mid_price - execution_vwap
                    )

                # -------------------------------------------------
                # Convert impact to R
                # -------------------------------------------------

                impact_r = (
                        impact_per_share / risk_per_share
                )

                impacts_r.append(impact_r)

            except Exception as e:
                log(
                    "debug",
                    f"Impact cost unavailable for {symbol}: {e}"
                )
                continue

            sleep(delay)

        if not impacts_r:
            return None

        return round(
            float(np.median(impacts_r)),
            4
        )

    except Exception as e:
        log(
            "debug",
            f"Impact cost calculation failed for {symbol}: {e}"
        )
        return None
