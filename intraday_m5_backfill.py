from util.db_util import get_table_name, purge_old_historical_data, get_last_stored_ts_for_symbols
from util.global_variables import INTRADAY_M5_CANDLE_SIZE, INTRADAY_M5_CANDLE_LIMIT, \
    LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH
from util.historical_candle_data_util import persist_historical_data
from util.kite_util import init_kite_session
from util.shariah_stock_filter import get_symbol_instrument_token
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

        # init kite
        init_kite_session()

        # load symbols and instrument token
        symbol_token_map = get_symbol_instrument_token(LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH)

        symbols = symbol_token_map.keys()

        # fetch and store candle ohlcv
        table_name = get_table_name(f"m{INTRADAY_M5_CANDLE_SIZE}")
        last_ts_map = get_last_stored_ts_for_symbols(table_name, symbols)

        persist_historical_data(table_name, f"{INTRADAY_M5_CANDLE_SIZE}minute", symbol_token_map,
                                INTRADAY_M5_CANDLE_SIZE, last_ts_map)

        # Remove stale data
        purge_old_historical_data(table_name, symbols, INTRADAY_M5_CANDLE_LIMIT)
        purge_old_logs(TradeType.INTRADAY, f"m{INTRADAY_M5_CANDLE_SIZE}")

    except Exception as e:
        log("error", f"🔥 Error during BACKFILL: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    run_backfill()
