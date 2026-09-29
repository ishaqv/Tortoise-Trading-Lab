from concurrent.futures import ThreadPoolExecutor, as_completed

import math
import pandas as pd
from ta.trend import SMAIndicator
from ta.volatility import AverageTrueRange

from positional.scanner.ma50_breakout_scanner_bot import is_ma50_breakout_detected, get_stop_distance
from util.entry_type import EntryType
from util.global_variables import (
    BREAKOUT_CANDLE_IDX, TRADING_CAPITAL, MAX_RISK_PER_TRADE_PERCENT,
    MAX_WORKERS, POSITIONAL_CANDLE_LIMIT,
)
from util.setup_type import PositionalSetupType
from util.trade_logger import log


def add_technical_indicators(df):
    df["atr"] = AverageTrueRange(
        high=df["high"], low=df["low"], close=df["close"], window=14
    ).average_true_range()
    df["ma_50"] = SMAIndicator(close=df["close"], window=50).sma_indicator()
    df["volume_sma_20"] = df["volume"].shift(1).rolling(window=20).mean()


def get_risk_per_share(breakout_candle):
    return get_stop_distance(breakout_candle)


def get_position_size(entry_price, risk_per_share):
    """Risk-based quantity, capped by available capital. 0 means don't trade."""
    if risk_per_share <= 0 or entry_price <= 0:
        return 0
    risk_qty = TRADING_CAPITAL * MAX_RISK_PER_TRADE_PERCENT / risk_per_share
    capital_qty = TRADING_CAPITAL / entry_price
    return max(math.floor(min(risk_qty, capital_qty)), 0)


def detect_setup(df):
    if is_ma50_breakout_detected(df):
        return PositionalSetupType.MA50B, EntryType.LONG
    return None, None


def analyze_stock_for_setup(symbol, df, is_backtesting=False, is_forward_testing=False):
    """Returns a signal dict if the latest candle is a valid setup, else None."""
    try:
        candle = df.iloc[BREAKOUT_CANDLE_IDX]
        log("info", f"Evaluating {symbol} | breakout_candle: {candle['trade_date']}")

        setup_type, entry_type = detect_setup(df)
        if setup_type is None:
            return None

        risk = get_risk_per_share(candle)
        return {
            "Symbol": symbol,
            "Date": candle["trade_date"],
            "Setup": setup_type.name,
            "Entry Type": entry_type.name,
            "Risk": risk,
            "Stop": round(float(candle["close"]) - risk, 2),
            "Signal Close": float(candle["close"]),
            "ATR": float(candle["atr"]),
            "Volume Ratio": float(candle["volume"] / candle["volume_sma_20"]),
        }

    except Exception as e:
        log("error", f"Error in analyzing stock {symbol}: {e}", exc_info=True)
        return None


def process_stock(symbol, stock_data_df):
    try:
        if stock_data_df is not None and len(stock_data_df) >= POSITIONAL_CANDLE_LIMIT:
            add_technical_indicators(stock_data_df)
            return analyze_stock_for_setup(symbol, stock_data_df, is_forward_testing=True)
    except Exception as e:
        log("error", f"Error processing stock {symbol}: {e}", exc_info=True)
    return None


def run_positional_screener(symbol_df_map: dict[str, pd.DataFrame]) -> list[dict]:
    """Run on completed weekly candles. Returns signals, strongest volume first."""
    signals = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_stock, s, df): s for s, df in symbol_df_map.items()}
        for future in as_completed(futures):
            try:
                result = future.result()
                if result:
                    signals.append(result)
            except Exception as e:
                log("exception", f"Thread error in {futures[future]}: {e}")

    signals.sort(key=lambda s: s["Volume Ratio"], reverse=True)
    log("info", f"Screener completed. {len(signals)} signal(s).")
    return signals


run_intraday_screener = run_positional_screener  # old name still works
