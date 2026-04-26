from util.db_util import get_table_name, initialize_db, purge_old_historical_data, \
    get_last_stored_date_for_symbols
from util.global_variables import SWING_CANDLE_SIZE, SWING_CANDLE_LIMIT
from util.kite_util import persist_historical_data, init_kite_session
from util.shariah_stock_filter import get_symbol_instrument_token
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

        # init kite
        init_kite_session()

        # load symbols and instrument token
        symbol_token_map = get_symbol_instrument_token()

        symbols = symbol_token_map.keys()

        # fetch and store candle ohlcv
        last_ts_map = get_last_stored_date_for_symbols(table_name, symbols)

        persist_historical_data(table_name, "day", symbol_token_map,
                                SWING_CANDLE_SIZE, last_ts_map)

        # Remove stale data
        purge_old_historical_data(table_name, symbols, SWING_CANDLE_LIMIT)
        purge_old_logs(TradeType.SWING, "d1")

    except Exception as e:
        log("exception", f"🔥 Error during BACKFILL: {e}")
        raise


if __name__ == "__main__":
    run_backfill()
