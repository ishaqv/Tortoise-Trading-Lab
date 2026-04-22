from util.db_util import get_table_name, initialize_db, purge_old_historical_data, get_last_stored_timestamp_for_symbols
from util.global_variables import INTRADAY_M5_CANDLE_SIZE, LIQUID_SHARIAH_SYMBOL_FILE_PATH, \
    LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH, INTRADAY_M5_CANDLE_LIMIT
from util.kite_util import persist_historical_data
from util.shariah_stock_filter import get_filtered_nse_shariah_stocks_with_instrument_token
from util.trade_logger import initialize_logger, purge_old_logs, log
from util.trade_type import TradeType


def run_backfill() -> None:
    """
    BACKFILL mode — post-market filling of past candles data.
    Fetches 5 min candle data and persist it.
    Typically scheduled around 3:30–4:00 PM.
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
        last_ts_map = get_last_stored_timestamp_for_symbols(table_name, symbols)

        persist_historical_data(table_name, f"{INTRADAY_M5_CANDLE_SIZE}minute", shariah_compliant_stock_dict,
                                INTRADAY_M5_CANDLE_SIZE, last_ts_map)

        # Remove stale data
        purge_old_historical_data(table_name, symbols, INTRADAY_M5_CANDLE_LIMIT)
        purge_old_logs(TradeType.INTRADAY, f"m{INTRADAY_M5_CANDLE_SIZE}")

    except Exception as e:
        log("exception", f"🔥 Error during BACKFILL: {e}")


if __name__ == "__main__":
    run_backfill()
