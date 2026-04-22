from util.db_util import get_table_name, initialize_db, purge_old_historical_data, \
    get_last_stored_date_for_symbols
from util.global_variables import LIQUID_SHARIAH_SYMBOL_FILE_PATH, \
    LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH, SWING_CANDLE_SIZE, SWING_CANDLE_LIMIT
from util.kite_util import persist_historical_data
from util.shariah_stock_filter import get_filtered_nse_shariah_stocks_with_instrument_token
from util.trade_logger import initialize_logger, purge_old_logs, log
from util.trade_type import TradeType


def run_backfill() -> None:
    """
    BACKFILL mode — post-market filling of past candles data.
    Fetches daily candle data and persist it.
    Typically scheduled around 3:50 PM.
    """
    try:
        # init logging
        initialize_logger(TradeType.SWING, "d1")

        # init backend data storage
        table_name = get_table_name("d1")
        initialize_db(table_name)

        # get stock universe
        shariah_compliant_stock_dict = get_filtered_nse_shariah_stocks_with_instrument_token(
            LIQUID_SHARIAH_SYMBOL_FILE_PATH, LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH)

        symbols = list(shariah_compliant_stock_dict.keys())

        # fetch and store candle ohlcv
        last_ts_map = get_last_stored_date_for_symbols(table_name, symbols)

        persist_historical_data(table_name, "day", shariah_compliant_stock_dict,
                                SWING_CANDLE_SIZE, last_ts_map)

        # Remove stale data
        purge_old_historical_data(table_name, symbols, SWING_CANDLE_LIMIT)
        purge_old_logs(TradeType.SWING, "d1")

    except Exception as e:
        log("exception", f"🔥 Error during BACKFILL: {e}")


if __name__ == "__main__":
    run_backfill()
