from datetime import datetime, timedelta

from ta.volatility import AverageTrueRange

from swing.scanner.swing_breakout_scanner_bot import get_stock_dataframe, analyze_stock_for_setup
from util.db_util import get_table_name
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
    table_name = get_table_name("d1")
    df = get_stock_dataframe(symbol, table_name)
    df = df[df['date'] <= breakout_window]
    return df


def add_technical_indicators(df):
    df['atr'] = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()


if __name__ == "__main__":
    initialize_logger(TradeType.SWING, "D", log_to_console=True)

    stock = "AMBER"  # NSE Top Gainer stock for backtest

    # Use data from 2 days ago for testing
    trading_day = datetime.today() - timedelta(days=1)

    stock_df = get_stock_df_from_db(stock, trading_day)

    if stock_df is not None and not stock_df.empty:
        add_technical_indicators(stock_df)
        analyze_stock_for_setup(stock, stock_df, trading_day.date())
