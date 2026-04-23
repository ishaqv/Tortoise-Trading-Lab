from datetime import datetime, timedelta
from pathlib import Path
from time import sleep

import pandas as pd

from util.global_variables import IST
from util.kite_util import get_kite_object
from util.shariah_stock_scrapper import get_cached_shariah_symbols
from util.trade_logger import log

shariah_compliant_stocks = None
shariah_compliant_stock_dict = None


def is_file_stale(file_path: Path, hours: int) -> bool:
    """
    Checks whether a file is stale based on its last modified time.

    A file is considered stale if:
    - It does not exist, or
    - It was last modified more than 'days' ago.
    """

    try:
        return not file_path.exists() or (
                    datetime.now(IST) - datetime.fromtimestamp(file_path.stat().st_mtime, IST)) > timedelta(
            hours=hours)
    except Exception as e:
        log("exception", f"Error checking file age: {e}")
        return True  # Fallback: treat as stale if error occurs


def load_cached_data(file_path: Path):
    """
     Loads cached symbol-to-instrument_token mapping from a CSV file.
    """

    try:
        if is_file_stale(file_path, 12):
            return None

        df = pd.read_csv(file_path)
        df.columns = df.columns.str.strip()
        df['symbol'] = df['symbol'].astype(str).str.strip()
        return df.set_index('symbol')['instrument_token'].to_dict()
    except Exception as e:
        log("exception", f"❌ Failed to read cached Shariah stock data: {e}")
        return None


def is_shariah_compliant(symbol_file_path, symbol: str) -> bool:
    """
    Checks if the given stock symbol is part of the Shariah-compliant list.
    """

    global shariah_compliant_stocks
    if shariah_compliant_stocks is None:
        try:
            shariah_compliant_stocks = get_cached_shariah_symbols(symbol_file_path)
        except Exception as e:
            log("exception", f"❌ Failed to fetch Shariah symbols: {e}")
            return False
    return symbol.strip() in shariah_compliant_stocks


def get_filtered_nse_shariah_stocks_with_instrument_token(symbol_file_path, symbol_token_file_path) -> dict:
    """
    Retrieves a dictionary of NSE Shariah-compliant stocks with their corresponding instrument tokens.

    This function first attempts to load the data from a cached CSV file. If the cache is stale or missing,
    it fetches fresh data from the NSE, filters it, saves it to cache, and returns the result.
    """

    global shariah_compliant_stock_dict

    if shariah_compliant_stock_dict is not None:
        return shariah_compliant_stock_dict

    cached_data = load_cached_data(symbol_token_file_path)
    if cached_data:
        shariah_compliant_stock_dict = cached_data
    else:
        try:
            instruments = fetch_nse_shariah_instruments(symbol_file_path)
            shariah_compliant_stock_dict = filter_and_save_stocks(instruments, symbol_token_file_path)
        except Exception as e:
            log("exception", f"❌ Failed to fetch and filter instruments: {e}")
            shariah_compliant_stock_dict = {}

    return shariah_compliant_stock_dict


def fetch_nse_shariah_instruments(symbol_file_path):
    """
    Fetches all NSE instruments and filters for Shariah-compliant stocks.
    """

    try:
        return [inst for inst in get_kite_object().instruments("NSE") if
                is_shariah_compliant(symbol_file_path, inst['tradingsymbol'])]
    except Exception as e:
        log("exception", f"❌ Failed to fetch NSE instruments: {e}")
        return []


def filter_and_save_stocks(instruments, symbol_token_file_path):
    """
    Filters instrument data, saves to CSV, and returns a symbol-token mapping.
    """

    filtered_data = []
    for i in range(0, len(instruments), 50):
        batch = instruments[i:i + 50]

        for inst in batch:
            filtered_data.append({
                'symbol': inst['tradingsymbol'].strip(),
                'instrument_token': inst['instrument_token']
            })
        sleep(3)

    df = pd.DataFrame(filtered_data)
    try:
        df.to_csv(symbol_token_file_path, index=False)
    except Exception as e:
        log("exception", f"❌ Failed to save CSV: {e}")

    return df.set_index('symbol')['instrument_token'].to_dict()
