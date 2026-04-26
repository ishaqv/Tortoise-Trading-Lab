import csv
from datetime import datetime, timedelta
from pathlib import Path

from util.global_variables import IST, LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH, LIQUID_SHARIAH_SYMBOL_FILE_PATH
from util.kite_util import get_nse_instruments
from util.trade_logger import log


def is_file_stale(file_path: Path, hours: int) -> bool:
    """
    File is stale if:
    - does not exist
    - is empty
    - is older than threshold
    """

    try:
        if not file_path.exists():
            return True

        if file_path.stat().st_size == 0:
            return True

        file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime, IST)
        return (datetime.now(IST) - file_mtime) > timedelta(hours=hours)

    except Exception as e:
        log("exception", f"Error checking file age: {e}")
        return True


def get_symbols():
    """
    Loads and returns a set of Shariah-compliant symbols from a CSV file.
    """
    try:
        symbols = set()

        with open(LIQUID_SHARIAH_SYMBOL_FILE_PATH, mode="r") as file:
            reader = csv.DictReader(file)

            # Validate header early (fail fast)
            if "symbol" not in reader.fieldnames:
                raise ValueError("CSV must contain 'symbol' column")

            for row in reader:
                symbol = row.get("symbol")

                if symbol:
                    symbol = symbol.strip()
                    if symbol:
                        symbols.add(symbol)

        return symbols

    except Exception as e:
        log("error", f"❌ Failed to read symbols: {e}", exc_info=True)
        raise


def load_symbol_token_map():
    """
    Load symbol -> instrument_token map from CSV
    """
    symbol_token_map = {}

    if is_file_stale(LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH, 12):
        return None

    try:
        with open(LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH, mode="r") as file:
            reader = csv.DictReader(file)

            for row in reader:
                symbol = row["symbol"]
                token = row["instrument_token"]
                symbol_token_map[symbol] = token

        return symbol_token_map

    except FileNotFoundError:
        return None

    except Exception as e:
        log("error", f"Failed to load CSV: {e}", exc_info=True)
        return None


def get_symbol_instrument_token() -> dict:
    """
    Retrieves a dictionary of symbols with their corresponding instrument tokens.
    """
    log("info", "Loading symbol-token mapping from file")

    symbol_token_map = load_symbol_token_map()

    if not symbol_token_map:
        log("info", "The symbol-token mapping file is stale. Fetching from Kite...")
        try:
            symbol_token_map = get_symbol_instrument_token_from_kite()
        except Exception as e:
            log("exception", f"❌ Failed to load symbol-token map: {e}", exc_info=True)
            raise

    return symbol_token_map


def get_symbol_instrument_token_from_kite():
    """
    Returns dict: {symbol: instrument_token}
    """

    # Fetch all NSE instruments once
    instruments = get_nse_instruments()
    symbols = get_symbols()
    symbol_token_map = {}

    for instrument in instruments:
        tradingsymbol = instrument["tradingsymbol"]

        if tradingsymbol in symbols:
            symbol_token_map[tradingsymbol] = instrument["instrument_token"]

    save_symbol_token_map_to_csv(symbol_token_map)

    log("info", "The symbol-token mapping file is saved successfully")

    return symbol_token_map


def save_symbol_token_map_to_csv(symbol_token_map):
    """
    Persist symbol -> instrument_token map to CSV
    Format:
    symbol,instrument_token
    """
    try:
        path = Path(LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, mode="w", newline="") as file:
            writer = csv.writer(file)

            # Write header
            writer.writerow(["symbol", "instrument_token"])

            # Write data
            for symbol, token in symbol_token_map.items():
                writer.writerow([symbol, token])

    except Exception as e:
        log("error", f"Failed to save symbol-token mapping file: {e}", exc_info=True)
