import time
from random import uniform

import pandas as pd
import requests

from util.selenium_driver import get_headless_chrome_driver
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


def get_shariah_compliant_symbols(symbol_file_path):
    """
    Returns a set of Shariah-compliant stock symbols.
    """

    cached_shariah_symbols = get_cached_shariah_symbols(symbol_file_path)

    if cached_shariah_symbols:
        return cached_shariah_symbols

    # Fetch from NSE if cache is stale/missing
    driver = None

    try:
        driver = get_headless_chrome_driver()
        url = "https://www.nseindia.com/market-data/live-equity-market?symbol=NIFTY500%20SHARIAH"
        driver.get(url)
        time.sleep(uniform(4, 6))  # randomized delay

        cookies = driver.get_cookies()
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": url
        }

        session = requests.Session()
        for cookie in cookies:
            session.cookies.set(cookie['name'], cookie['value'])

        download_url = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY500%20SHARIAH"
        response = session.get(download_url, headers=headers)

        if response.status_code == 200:
            data = response.json()
            symbols = set([row["symbol"].strip() for row in data.get("data", []) if "symbol" in row])
            symbols.discard("NIFTY500 SHARIAH")
            # Save to CSV
            pd.DataFrame(symbols, columns=["symbol"]).to_csv(symbol_file_path, index=False)

            return set(symbols)
        else:
            log("error", f"❌ Failed to fetch Shariah index data. Status code: {response.status_code}")
            return set()

    except Exception as e:
        log("exception", f"❌ Error fetching Shariah index data: {e}")

    finally:
        if driver:
            driver.quit()


def write_symbols_to_csv(symbols, symbol_file_path):
    pd.DataFrame(symbols, columns=["symbol"]).to_csv(symbol_file_path, index=False)
