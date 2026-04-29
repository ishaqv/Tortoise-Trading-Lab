import csv
from datetime import datetime, timedelta
from pathlib import Path

from util.db_util import fetch_and_filter_liquid_symbols
from util.global_variables import IST, LIQUID_SHARIAH_SYMBOL_FILE_PATH, \
    MASTER_SHARIAH_SYMBOL_FILE_PATH
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
        log("exception", f"Error checking file {file_path.name} age: {e}")
        return True


def read_symbols_from_csv(file_path: str) -> set[str]:
    symbols = set()
    with open(file_path, mode="r") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames or "symbol" not in reader.fieldnames:
            raise ValueError("CSV must contain 'symbol' column")
        for row in reader:
            if symbol := row.get("symbol", "").strip():
                symbols.add(symbol)
    return symbols


def get_liquid_symbols() -> set[str]:
    try:
        if is_file_stale(LIQUID_SHARIAH_SYMBOL_FILE_PATH, 12):
            symbols = fetch_and_filter_liquid_symbols()
            save_symbols_to_csv(symbols, LIQUID_SHARIAH_SYMBOL_FILE_PATH)
            return symbols
        return read_symbols_from_csv(LIQUID_SHARIAH_SYMBOL_FILE_PATH)
    except Exception as e:
        log("error", f"❌ Failed to read liquid symbols: {e}", exc_info=True)
        raise


def get_master_symbols() -> set[str]:
    try:
        return read_symbols_from_csv(MASTER_SHARIAH_SYMBOL_FILE_PATH)
    except Exception as e:
        log("error", f"❌ Failed to read master symbols: {e}", exc_info=True)
        raise


def load_symbol_token_map(file_path):
    """
    Load symbol -> instrument_token map from CSV
    """
    symbol_token_map = {}

    if is_file_stale(file_path, 12):
        return None

    try:
        with open(file_path, mode="r") as file:
            reader = csv.DictReader(file)

            for row in reader:
                symbol = row["symbol"]
                token = row["instrument_token"]
                symbol_token_map[symbol] = token

        return symbol_token_map

    except FileNotFoundError:
        return None

    except Exception as e:
        log("error", f"Failed to load CSV file {file_path.name}: {e}", exc_info=True)
        return None


def get_symbol_instrument_token(file_path) -> dict:
    """
    Retrieves a dictionary of symbols with their corresponding instrument tokens.
    """
    log("info", f"Loading symbol-token mapping from file {file_path.name}")

    symbol_token_map = load_symbol_token_map(file_path)

    if not symbol_token_map:
        log("info", "The symbol-token mapping file is stale. Fetching from Kite...")
        try:
            symbols = None
            if "master" in file_path.name:
                symbols = get_master_symbols()

            elif "liquid" in file_path.name:
                symbols = get_liquid_symbols()

            symbol_token_map = get_symbol_instrument_token_from_kite(symbols)

            save_symbol_token_map_to_csv(symbol_token_map, file_path)

        except Exception as e:
            log("exception", f"❌ Failed to load symbol-token map: {e}", exc_info=True)
            raise

    return symbol_token_map


def get_symbol_instrument_token_from_kite(symbols):
    """
    Returns dict: {symbol: instrument_token}
    """
    if not symbols:
        return None

    # Fetch all NSE instruments once
    instruments = get_nse_instruments()

    symbol_token_map = {}

    for instrument in instruments:
        tradingsymbol = instrument["tradingsymbol"]

        if tradingsymbol in symbols:
            symbol_token_map[tradingsymbol] = instrument["instrument_token"]

    return symbol_token_map


def save_symbol_token_map_to_csv(symbol_token_map, file_path):
    """
    Persist symbol -> instrument_token map to CSV
    Format:
    symbol,instrument_token
    """
    try:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, mode="w", newline="") as file:
            writer = csv.writer(file)

            # Write header
            writer.writerow(["symbol", "instrument_token"])

            # Write data
            for symbol, token in symbol_token_map.items():
                writer.writerow([symbol, token])

        log("info", f"The symbol-token mapping file {file_path.name} is saved successfully")

    except Exception as e:
        log("error", f"Failed to save symbol-token mapping file {file_path.name}: {e}", exc_info=True)


def save_symbols_to_csv(symbols, file_path) -> str:
    try:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["symbol"])
            writer.writerows([[s] for s in symbols])

        log("info", f"Saved {len(symbols)} symbols to {file_path.name}")

    except Exception as e:
        log("error", f"Failed to save symbol file {file_path.name}: {e}", exc_info=True)
