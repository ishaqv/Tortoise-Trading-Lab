from util.global_variables import INTRADAY_M5_CANDLE_SIZE, LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH
from util.kite_util import init_kite_session
from util.shariah_stock_filter import get_symbol_instrument_token

from util.trade_logger import initialize_logger, log
from util.trade_type import TradeType


def run_warmup() -> None:
    """
    WARMUP mode — pre-market preparation before trading begins.
    Fetches kite acces token and catches it.
    Runs once, typically scheduled around 9:10–9:15 AM.
    """
    try:
        # init logging
        initialize_logger(TradeType.INTRADAY, f"m{INTRADAY_M5_CANDLE_SIZE}")

        # init kite
        init_kite_session()

        # load symbols and instrument token
        get_symbol_instrument_token(LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH)

        log("info", "✅ WARMUP complete")

    except Exception as e:
        log("error", f"🔥 Error during WARMUP: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    run_warmup()
