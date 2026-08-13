from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from time import sleep

import math
import numpy as np
import pandas as pd
from ta.volatility import AverageTrueRange

from intraday.scanner.m5.early_momentum_breakout_scanner import is_early_momentum_breakout_detected
from intraday.scanner.m5.volume_explosion_breakout_scanner import is_volume_explosion_breakout_detected
from util.entry_type import EntryType
from util.global_variables import *
from util.kite_util import get_best_bid_ask, get_market_depth
from util.setup_type import IntradaySetupType
from util.telegram_bot import send_telegram_alert
from util.trade_logger import log
from util.trade_type import TradeType


# -----------------------------------------------------------------------------
# DATA / INDICATORS
# -----------------------------------------------------------------------------

def get_previous_day_data(df):
    trade_dates = df["trade_date"].dt.date
    unique_dates = trade_dates.unique()

    if len(unique_dates) < 2:
        return df.iloc[0:0].copy()

    previous_day = unique_dates[-2]
    return df[trade_dates == previous_day].copy()


def calculate_opening_gap(df_trading_day, df_previous_day):
    today_open = df_trading_day.iloc[0].open
    yesterday_close = df_previous_day.iloc[-1].close

    if yesterday_close <= 0:
        return 0.0

    return round(abs(today_open - yesterday_close) / yesterday_close * 100, 1)


def add_technical_indicators(df):
    df["atr"] = AverageTrueRange(
        high=df["high"], low=df["low"], close=df["close"], window=14
    ).average_true_range()
    df["volume_sma_20"] = df["volume"].shift(1).rolling(window=20).mean()


def get_risk_per_share(breakout_atr):
    return round(breakout_atr * INTRADAY_M5_ATR_RISK_MULTIPLIER, 1)


def get_tradable_quantity(breakout_candle):
    breakout_price = breakout_candle["close"]
    breakout_value = breakout_price * breakout_candle["volume"]

    if breakout_value <= 0:
        return float("inf")  # no liquidity, so fail the trade

    risk_per_share = breakout_candle["atr"] * INTRADAY_M5_ATR_RISK_MULTIPLIER
    if risk_per_share <= 0:
        return float("inf")

    buying_power = TRADING_CAPITAL * INTRADAY_LEVERAGE_MULTIPLIER
    max_risk_amount = TRADING_CAPITAL * MAX_RISK_PER_TRADE_PERCENT

    risk_based_qty = max_risk_amount / risk_per_share
    capital_based_qty = buying_power / breakout_price

    tradable_qty = math.floor(min(risk_based_qty, capital_based_qty))

    return tradable_qty if tradable_qty > 0 else float("inf")


def get_participation_rate(breakout_candle, tradable_qty):
    breakout_price = breakout_candle["close"]
    breakout_value = breakout_price * breakout_candle["volume"]

    if breakout_value <= 0:
        return float("inf")

    order_value = tradable_qty * breakout_price
    return round((order_value / breakout_value) * 100, 1)


# -----------------------------------------------------------------------------
# LIQUIDITY / EXECUTION
# -----------------------------------------------------------------------------

def get_spread_atr_ratio(symbol, atr, samples=5, delay=0.2):
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

    return round(np.median(spreads) / atr, 4)


def is_spread_acceptable(spread_atr_ratio, participation_rate):
    # the more liquidity our order eats up, the tighter the spread needs to be
    if spread_atr_ratio is None or participation_rate is None:
        return False

    if participation_rate <= 1.0:
        max_spread_atr_ratio = NSE_MAX_SPREAD_ATR_RATIO
    elif participation_rate <= 3.0:
        max_spread_atr_ratio = 0.10
    elif participation_rate <= 5.0:
        max_spread_atr_ratio = 0.075
    else:
        max_spread_atr_ratio = 0.02

    return spread_atr_ratio <= max_spread_atr_ratio


def walk_order_book(levels, quantity, mid_price, direction):
    # fills the order level by level and returns how far the fill price
    # drifted away from the mid price (the "impact" of the order)
    is_long = direction == EntryType.LONG
    sorted_levels = sorted(levels, key=lambda lvl: lvl["price"], reverse=not is_long)

    remaining_qty = quantity
    execution_value = 0.0

    for level in sorted_levels:
        price = level["price"]
        available_qty = level["quantity"]

        if price <= 0 or available_qty <= 0:
            continue

        fill_qty = min(remaining_qty, available_qty)
        execution_value += fill_qty * price
        remaining_qty -= fill_qty

        if remaining_qty <= 0:
            break

    if remaining_qty > 0:
        return None  # not enough depth to fill the whole order

    execution_vwap = execution_value / quantity
    return execution_vwap - mid_price if is_long else mid_price - execution_vwap


def get_impact_cost(symbol, quantity, direction, risk_per_share, samples=5, delay=0.2):
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

                if best_bid <= 0 or best_ask <= 0 or best_bid > best_ask:
                    sleep(delay)
                    continue

                mid_price = (best_bid + best_ask) / 2
                impact_per_share = walk_order_book(
                    levels=asks if direction == EntryType.LONG else bids,
                    quantity=quantity,
                    mid_price=mid_price,
                    direction=direction,
                )

                if impact_per_share is not None:
                    impacts_r.append(impact_per_share / risk_per_share)

            except Exception as e:
                log("debug", f"Impact cost unavailable for {symbol}: {e}")

            sleep(delay)

        if not impacts_r:
            return None

        return round(float(np.median(impacts_r)), 4)

    except Exception as e:
        log("debug", f"Impact cost calculation failed for {symbol}: {e}")
        return None


# -----------------------------------------------------------------------------
# SETUP DETECTION / ALERTS
# -----------------------------------------------------------------------------

def detect_setup(breakout_candle, breakout_time, participation_rate, opening_gap_pct):
    if breakout_time != EVB_SCAN_CANDLE_TIME:
        return None, None

    if is_volume_explosion_breakout_detected(breakout_candle, participation_rate, opening_gap_pct):
        return IntradaySetupType.EVB, EntryType.LONG

    if is_early_momentum_breakout_detected(breakout_candle, participation_rate, opening_gap_pct):
        return IntradaySetupType.EMB, EntryType.LONG

    return None, None


def evaluate_and_alert(symbol, setup_type, entry_type, breakout_atr, risk_per_share, tradable_qty, participation_rate):
    spread_atr_ratio = get_spread_atr_ratio(symbol, breakout_atr)

    if not is_spread_acceptable(spread_atr_ratio, participation_rate):
        ratio_display = round(spread_atr_ratio * 100, 1) if spread_atr_ratio is not None else "N/A"
        message = (
            f"{setup_type.name} breakout rejected for {symbol} — "
            f"spread/ATR ratio {ratio_display}% is too wide for the "
            f"participation rate {participation_rate}%"
        )
        log("info", message)
        send_telegram_alert(message)
        return

    entry_type_icon = "🟢" if entry_type == EntryType.LONG else "🔴"

    message = (
        f"{entry_type_icon} <b>{entry_type.name} SETUP DETECTED</b>\n\n\n"
        f"📌 <b>Symbol : </b> {symbol}\n\n"
        f"🧠 <b>Setup : </b> {setup_type.name}\n\n"
        f"⚡ <b>Trade : </b> {TradeType.INTRADAY.name}\n\n"
        f"⚠️ <b>Risk : </b> {risk_per_share} pips\n\n"
        f"📊 <b>Participation Rate : </b> {participation_rate}%\n\n"
        f"📐 <b>Spread-ATR Ratio : </b> {round(spread_atr_ratio * 100, 1)}%\n\n"
    )

    send_telegram_alert(message)
    log("info", message)


# -----------------------------------------------------------------------------
# STOCK ANALYSIS / SCREENER
# -----------------------------------------------------------------------------

def analyze_stock_for_setup(symbol, df, trading_day=None, is_backtesting=False, is_forward_testing=False):
    if trading_day is None:
        trading_day = date.today()

    try:
        log("info", "--------------------------------")

        df_trading_day = df[df["trade_date"].dt.date == trading_day].copy()
        if len(df_trading_day) < 1:
            return None

        breakout_candle = df_trading_day.iloc[BREAKOUT_CANDLE_IDX]
        breakout_candle_date_time = breakout_candle["trade_date"]
        breakout_time = breakout_candle_date_time.time()

        log("info", f"Evaluating {symbol} | breakout_candle: {breakout_candle_date_time}")

        df_previous_day = get_previous_day_data(df)
        opening_gap_pct = calculate_opening_gap(df_trading_day, df_previous_day)
        breakout_atr = breakout_candle["atr"]
        risk_per_share = get_risk_per_share(breakout_atr)
        tradable_qty = get_tradable_quantity(breakout_candle)
        participation_rate = get_participation_rate(breakout_candle, tradable_qty)

        setup_type, entry_type = detect_setup(
            breakout_candle, breakout_time, participation_rate, opening_gap_pct
        )

        if setup_type is None:
            return None

        if is_backtesting:
            return {
                "Symbol": symbol,
                "Date": breakout_candle_date_time,
                "Day": breakout_candle_date_time.strftime("%A"),
                "Setup": setup_type.name,
                "Entry Type": entry_type.name,
                "Risk": risk_per_share,
            }

        if is_forward_testing:
            log("info", f"{setup_type.name} setup detected for {symbol}")
            return None

        evaluate_and_alert(
            symbol=symbol,
            setup_type=setup_type,
            entry_type=entry_type,
            breakout_atr=breakout_atr,
            risk_per_share=risk_per_share,
            tradable_qty=tradable_qty,
            participation_rate=participation_rate,
        )
        return None

    except Exception as e:
        log("error", f"Error in analyzing stock {symbol}: {e}", exc_info=True)
        return None


def process_stock(symbol, stock_data_df):
    try:
        if stock_data_df is not None and len(stock_data_df) >= INTRADAY_M5_CANDLE_LIMIT:
            add_technical_indicators(stock_data_df)
            analyze_stock_for_setup(symbol, stock_data_df)
    except Exception as e:
        log("error", f"Error processing stock {symbol}: {e}", exc_info=True)


def run_intraday_screener(symbol_df_map: dict[str, pd.DataFrame]) -> None:
    log(
    "info",
    f"Starting screener with {MAX_WORKERS} workers "
    f"for {len(symbol_df_map)} symbols.",
)

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