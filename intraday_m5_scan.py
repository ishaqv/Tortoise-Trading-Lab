from intraday.scanner.m5.intraday_m5_breakout_scanner_bot import run_intraday_screener
from util.db_util import get_table_name, initialize_db, get_historical_data_for_symbols, write_historical_data
from util.global_variables import INTRADAY_M5_CANDLE_SIZE, LIQUID_SHARIAH_SYMBOL_FILE_PATH, \
    LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH
from util.kite_util import append_latest_candle_data_from_kite
from util.shariah_stock_filter import get_filtered_nse_shariah_stocks_with_instrument_token
from util.trade_logger import initialize_logger, log
from util.trade_type import TradeType


def run_scan() -> None:
    """
    SCAN mode — Scans for potential setups and alert them via telegram.
    Fetches latest 5 min candle data, process and persist it.
    Typically scheduled around 9:20 AM.
    """
    try:
        # init logging
        initialize_logger(TradeType.INTRADAY, f"m{INTRADAY_M5_CANDLE_SIZE}")

        # init backend data storage
        table_name = get_table_name(f"m{INTRADAY_M5_CANDLE_SIZE}")
        initialize_db(table_name)

        # get stock universe
        shariah_compliant_stock_dict = get_filtered_nse_shariah_stocks_with_instrument_token(
            LIQUID_SHARIAH_SYMBOL_FILE_PATH, LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH)

        symbols = list(shariah_compliant_stock_dict.keys())

        # fetch and store candle ohlcv
        symbol_df_map = get_historical_data_for_symbols(table_name, symbols)
        symbol_df_map, new_records = append_latest_candle_data_from_kite(f"{INTRADAY_M5_CANDLE_SIZE}minute",
                                                                         shariah_compliant_stock_dict,
                                                                         INTRADAY_M5_CANDLE_SIZE, symbol_df_map)

        # run screener to find potential setup
        run_intraday_screener(symbol_df_map)

        # Persist new candle data
        if new_records:
            write_historical_data(table_name, new_records)

    except Exception as e:
        log("exception", f"🔥 Error during SCAN: {e}")


if __name__ == "__main__":
    run_scan()
