from datetime import datetime, timedelta, time

from intraday.scanner.m15.intraday_m15_breakout_scanner_bot import get_stock_dataframe, add_technical_indicators, \
    analyze_stock_for_setup
from util.db_util import get_table_name
from util.global_variables import INTRADAY_M15_CANDLE_SIZE
from util.trade_logger import initialize_logger
from util.trade_type import TradeType


# =============================================================================
# 🔁 Intraday Breakout Replay – Validation Script
#
# Purpose:
# This script replays intraday data for a breakout stock to verify whether
# the current scanner is able to detect valid breakout setups.
# It helps identify missed breakouts and debug detection logic.
# =============================================================================
#
# ✅ Usage Steps:
#
# 1. Identify potential breakout candidates:
#    - Use `useful_queries.sql` to fetch top gainers for the trading day.
#
# 2. Manually verify breakouts:
#    - Open the intraday chart for each top gainer.
#    - Confirm whether a clean breakout occurred (e.g., ORB or VWAP breakout).
#
# 3. Select breakout timestamp:
#    - Note the breakout time (e.g., 9:45 AM).
#
# 4. Replay breakout scenario:
#    - Use this script to analyze data up to the breakout time.
#    - Logs will indicate if the script detected the breakout.
#
# 5. Investigate missed breakouts:
#    - If a breakout wasn't detected, review the logs for reasons:
#      volume thresholds, prior tests, OR range, ATR compression, etc.
#
# 6. Improve logic if needed:
#    - Based on analysis, refine the breakout detection logic or scoring thresholds.
# =============================================================================


def get_stock_df_from_db(symbol, breakout_window):
    """
       Retrieves intraday stock data for a given symbol from the database
       up to the specified breakout window timestamp.
    """
    table_name = get_table_name(f"m{INTRADAY_M15_CANDLE_SIZE}")
    df = get_stock_dataframe(symbol, table_name)
    df = df[df['date'] <= breakout_window]
    return df


if __name__ == "__main__":
    initialize_logger(TradeType.INTRADAY, f"m{INTRADAY_M15_CANDLE_SIZE}", log_to_console=True)

    stock = "APEX"  # NSE Top Gainer stock for backtest

    # Use data from 2 days ago for testing
    trading_day = datetime.today() - timedelta(days=0)
    breakout_time = datetime.combine(trading_day, time(9, 15))  # 9:45 AM candle is our breakout candidate

    stock_df = get_stock_df_from_db(stock, breakout_time)

    if stock_df is not None and not stock_df.empty:
        add_technical_indicators(stock_df)
        analyze_stock_for_setup(stock, stock_df, trading_day.date())
