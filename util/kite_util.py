import json
import os
import time
from datetime import datetime, timedelta, date
from typing import Optional

import pandas as pd
import pyotp
from kiteconnect import KiteConnect
from kiteconnect.exceptions import NetworkException, DataException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from util.db_util import write_historical_data
from util.global_variables import API_SECRET, USER_ID, PASSWORD, TOTP_SECRET, KITE_API_REQUEST_RATE_PER_SECOND, \
    BUFFER_SIZE, SWING_CANDLE_LIMIT
from util.global_variables import IST, API_KEY
from util.selenium_driver import get_headless_chrome_driver
from util.trade_logger import log

kite: Optional[KiteConnect] = None
ACCESS_TOKEN_FILE = "access_token.json"
_last_request_time: float = 0


def login_with_selenium():
    """
    Automates the Zerodha Kite Connect login process using Selenium.

    This function performs a headless browser-based login using Zerodha credentials and TOTP-based 2FA.
    It navigates to the login page, inputs the user ID and password, enters the TOTP, and finally extracts
    the `request_token` from the redirected URL after successful login.

    Notes:
        - This function uses headless Chrome. Ensure that ChromeDriver is installed and properly configured.
        - Any change in Zerodha's frontend (e.g., CSS selectors) may break this automation.
        - `request_token` is valid for only a few minutes. Use it immediately to generate the session.
    """

    driver = get_headless_chrome_driver()
    login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={API_KEY}"
    driver.get(login_url)

    try:
        WebDriverWait(driver, 15).until(
            ec.presence_of_element_located((By.CSS_SELECTOR, "input[type='text']"))
        )

        driver.find_element(By.CSS_SELECTOR, "input[type='text']").send_keys(USER_ID)
        driver.find_element(By.CSS_SELECTOR, "input[type='password']").send_keys(PASSWORD)
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

        totp = get_totp_token(TOTP_SECRET)

        WebDriverWait(driver, 15).until(
            ec.presence_of_element_located((By.CSS_SELECTOR, "input[type='number']"))
        )

        driver.find_element(By.CSS_SELECTOR, "input[type='number']").send_keys(totp)
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

        WebDriverWait(driver, 30).until(
            ec.url_contains("request_token")
        )

        current_url = driver.current_url
        request_token = current_url.split("request_token=")[-1].split("&")[0]

        return request_token

    finally:
        driver.quit()


def get_totp_token(secret):
    """
    Generates a time-based one-time password (TOTP) using the provided secret key.
    """
    totp = pyotp.TOTP(secret)
    return totp.now()


def get_market_open() -> datetime:
    """
    Returns the market open time (09:15 AM) for the current day in IST.
    """
    return datetime.now(IST).replace(hour=9, minute=15, second=0, microsecond=0)


def get_market_close() -> datetime:
    return datetime.now(IST).replace(hour=15, minute=30, second=0, microsecond=0)


def save_access_token(token: str):
    with open(ACCESS_TOKEN_FILE, "w") as f:
        json.dump({"access_token": token}, f)


def load_access_token() -> str | None:
    if not os.path.exists(ACCESS_TOKEN_FILE):
        return None
    with open(ACCESS_TOKEN_FILE, "r") as f:
        data = json.load(f)
        return data.get("access_token")


def get_access_token():
    """
    Ensures the global kite object is valid and returns the current access token.

    Flow:
      1. If global kite exists and profile() succeeds → return its token (no-op).
      2. If global kite is stale → set kite=None, fall through.
      3. Load saved token from file (written by Process A or a previous session).
         If valid → restore global kite from it.
      4. If saved token is also expired → fresh Selenium login.
    """
    global kite

    # Step 1: try token saved to disk
    access_token = load_access_token()

    if access_token:
        kite = KiteConnect(api_key=API_KEY)
        kite.set_access_token(access_token)
        try:
            kite.profile()
            kite.timeout = 30
            log("info", "Restored session from saved token.")
            return access_token
        except Exception as e:
            log("info", f"Saved token expired, logging in fresh... ({e})")

    # Step 2: fresh Selenium login
    log("info", "Starting Selenium login...")
    request_token = login_with_selenium()
    kite = KiteConnect(api_key=API_KEY)
    data = kite.generate_session(request_token, api_secret=API_SECRET)
    access_token = data["access_token"]
    kite.set_access_token(access_token)
    kite.timeout = 30
    save_access_token(access_token)
    log("info", "New session created and saved.")

    return access_token


def cache_kite_access_token() -> None:
    """
    Called by Process A to log in and persist the token to disk.
    Process B will pick it up via load_access_token() on startup.
    """
    request_token = login_with_selenium()
    kite_token_manager = KiteConnect(api_key=API_KEY)
    data = kite_token_manager.generate_session(request_token, api_secret=API_SECRET)
    access_token = data["access_token"]
    save_access_token(access_token)


def get_kite_object() -> KiteConnect:
    """
    Returns the global KiteConnect object, always ensuring the token is valid.

    Delegates fully to get_access_token() which manages the global kite instance.
    Never creates a parallel kite instance — avoids stale reference bugs.
    """
    global kite
    if not kite:
        kite = KiteConnect(api_key=API_KEY)
        kite.set_access_token(get_access_token())
        kite.timeout = 30
    return kite


def get_to_date(from_date: datetime, intraday_candle_size: int) -> datetime | None:
    """
    Returns the latest valid candle boundary we can fetch up to,
    or None if there's nothing to fetch yet.
    """
    now = datetime.now(IST).replace(second=0, microsecond=0)

    # Always anchor market hours to TODAY
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)

    # Nothing to fetch before market opens
    if now < market_open:
        return None

    # Clamp current time to market close
    effective_now = min(now, market_close)

    # from_date is already at or beyond the latest fetchable candle
    if from_date >= effective_now:
        return None

    # Clamp from_date to market open (in case it's earlier)
    effective_from = max(from_date, market_open)

    # Defensive: after clamping, still nothing to fetch
    if effective_from >= effective_now:
        return None

    # Snap to the last complete candle boundary
    elapsed_minutes = int((effective_now - effective_from).total_seconds() // 60)
    num_steps = elapsed_minutes // intraday_candle_size

    if num_steps == 0:
        return None  # not even one full candle has elapsed

    return effective_from + timedelta(minutes=num_steps * intraday_candle_size)


def kite_throttle():
    global _last_request_time

    now = time.time()
    elapsed = now - _last_request_time
    min_interval = 1 / KITE_API_REQUEST_RATE_PER_SECOND  # e.g., 3 req/s → 0.333s

    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)

    _last_request_time = time.time()


def fetch_historical_data_from_kite(symbol, instrument_token, from_date, to_date, interval, retries=3):
    for attempt in range(1, retries + 1):
        try:
            kite_throttle()
            historical_data = get_kite_object().historical_data(
                instrument_token,
                from_date,
                to_date,
                interval
            )
            return historical_data

        except NetworkException as e:
            wait = 2 ** attempt  # 2s, 4s, 8s
            log("warning", f"⚠️ Network error for {symbol}: {e}")
            log("warning", f"   Type: {type(e)}")
            log("warning", f"   Args: {e.args}")
            log("warning", f"   Dict: {e.__dict__}")  # ← often has the real details
            log("warning", f"⚠️ Network error for {symbol} (attempt {attempt}/{retries}): {e}. Retrying in {wait}s...")
            if attempt == retries:
                log("error", f"❌ All retries exhausted for {symbol}: {e}")
                return None
            time.sleep(wait)

        except DataException as e:
            log("error", f"❌ Invalid data/token for {symbol}: {e}")
            return None  # Don't retry — bad instrument token

        except Exception as e:
            log("error", f"❌ Unexpected error for {symbol}: {e}")
            return None
    return None


def fetch_historical_data_for_symbol(symbol, instrument_token, last_stored_date, interval, intraday_candle_size):
    try:
        market_open_today = get_market_open()

        if last_stored_date:
            if last_stored_date.tzinfo is None:
                last_stored_date = last_stored_date.replace(tzinfo=IST)
            else:
                last_stored_date = last_stored_date.astimezone(IST)

            next_candle = last_stored_date + timedelta(minutes=intraday_candle_size)

            if next_candle.date() < get_market_close().date() and next_candle.time() >= get_market_close().time():
                # ─── Last candle was the final candle of the previous day → fresh start today
                from_date = market_open_today
            else:
                # ─── Mid-session → continue from next candle
                from_date = next_candle
        else:
            from_date = market_open_today

        to_date = get_to_date(from_date, intraday_candle_size)

        if to_date is None or from_date >= to_date:
            log("info", f"Skipping {symbol} — nothing to fetch yet")
            return []

        # Kite API requires tz-naive datetimes — strip timezone before sending
        from_date_naive = from_date.replace(tzinfo=None)
        to_date_naive = to_date.replace(tzinfo=None)

        historical_data = fetch_historical_data_from_kite(symbol, instrument_token, from_date_naive, to_date_naive,
                                                          interval)

        if not historical_data:
            return []

        df = pd.DataFrame(historical_data)
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d %H:%M:%S')

        return [
            (
                symbol,
                str(row['date']),
                float(row['open']),
                float(row['high']),
                float(row['low']),
                float(row['close']),
                int(row['volume'])
            )
            for _, row in df.iterrows()
        ]

    except Exception as e:
        log("exception", f"⚠️ Fetch failed for {symbol}: {e}")
        return []


def fetch_historical_data_for_symbol_daily(symbol, instrument_token, last_stored_date, interval):
    try:

        today = datetime.now(IST).date()

        if last_stored_date:
            # Normalize to a plain date regardless of whether it's a date or datetime
            if isinstance(last_stored_date, datetime):
                last_stored_date = last_stored_date.astimezone(IST).date()
            elif isinstance(last_stored_date, date):
                last_stored_date = last_stored_date  # already a plain date

            from_date = last_stored_date + timedelta(days=1)
        else:
            # No data yet — pull from a reasonable default (e.g.30 days back)
            from_date = today - timedelta(days=SWING_CANDLE_LIMIT)

        to_date = today

        if from_date > to_date:
            log("info", f"Skipping {symbol} — daily data is already up to date")
            return []

        # Kite API expects datetime objects even for daily interval — use midnight, tz-naive
        from_date_naive = datetime(from_date.year, from_date.month, from_date.day)
        to_date_naive = datetime(to_date.year, to_date.month, to_date.day)

        historical_data = fetch_historical_data_from_kite(
            symbol, instrument_token, from_date_naive, to_date_naive, interval
        )

        if not historical_data:
            return []

        df = pd.DataFrame(historical_data)
        # Keep only the date part — time is meaningless for daily candles
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')

        return [
            (
                symbol,
                str(row['date']),
                float(row['open']),
                float(row['high']),
                float(row['low']),
                float(row['close']),
                int(row['volume'])
            )
            for _, row in df.iterrows()
        ]

    except Exception as e:
        log("exception", f"⚠️ Daily fetch failed for {symbol}: {e}")
        return []


def append_latest_candle_data_from_kite(
        interval,
        shariah_compliant_stock_dict,
        candle_size,
        symbol_df_map: dict[str, pd.DataFrame]
) -> tuple[dict[str, pd.DataFrame], list]:
    """
    Fetches the latest candle(s) from Kite for each symbol and appends them
    to the in-memory symbol_df_map (already loaded from DB).

    Returns:
        symbol_df_map : updated in-memory map with new candles appended
        new_records   : raw tuples of all newly fetched candles for batch DB insert
    """
    new_records = []

    for symbol, instrument_token in shariah_compliant_stock_dict.items():

        # Derive from_date from in-memory df — no DB call needed
        existing_df = symbol_df_map.get(symbol)
        last_stored_date = existing_df['date'].iloc[-1] if existing_df is not None and not existing_df.empty else None

        # Fetch latest candle(s) from Kite
        records = fetch_historical_data_for_symbol(symbol, instrument_token, last_stored_date, interval, candle_size)

        if not records:
            continue

        # Accumulate raw tuples for batch DB insert later
        new_records.extend(records)

        # Build df from raw Kite records and align columns with existing df
        new_df = pd.DataFrame(records, columns=['symbol', 'date', 'open', 'high', 'low', 'close', 'volume'])
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        new_df[numeric_cols] = new_df[numeric_cols].apply(pd.to_numeric, errors='coerce')
        new_df['date'] = pd.to_datetime(new_df['date'])
        new_df = new_df.dropna()

        # Append new candles to existing in-memory df
        if existing_df is not None and not existing_df.empty:
            symbol_df_map[symbol] = pd.concat([existing_df, new_df], ignore_index=True)
        else:
            symbol_df_map[symbol] = new_df

    return symbol_df_map, new_records


def persist_historical_data(
        table_name,
        interval,
        shariah_compliant_stock_dict,
        candle_size,
        last_ts_map
):
    buffer = []

    for symbol, instrument_token in shariah_compliant_stock_dict.items():
        if interval == "day":
            records = fetch_historical_data_for_symbol_daily(
                symbol, instrument_token, last_ts_map.get(symbol), interval)
        else:
            records = fetch_historical_data_for_symbol(
                symbol, instrument_token, last_ts_map.get(symbol), interval, candle_size)

        if not records:
            continue

        buffer.extend(records)

        if len(buffer) >= BUFFER_SIZE:
            write_historical_data(table_name, buffer)
            buffer.clear()

    if buffer:
        write_historical_data(table_name, buffer)