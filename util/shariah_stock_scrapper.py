import pandas as pd

from util.trade_logger import log


def get_cached_shariah_symbols(symbol_file_path):
    """
        Loads and returns a cached set of Shariah-compliant stock symbols from a CSV file, if it's still fresh.
    """

    if symbol_file_path.exists():
        try:
            df = pd.read_csv(symbol_file_path)
            symbols = set(df['symbol'].dropna().str.strip())
            symbols.discard('NIFTY500 SHARIAH')  # Remove index name if present
            return symbols
        except Exception as e:
            log("error", f"❌ Failed to read cached Shariah symbols: {e}")

    return None


def write_symbols_to_csv(symbols, symbol_file_path):
    pd.DataFrame(symbols, columns=["symbol"]).to_csv(symbol_file_path, index=False)
