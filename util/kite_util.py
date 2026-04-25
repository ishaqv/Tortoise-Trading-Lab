import time
from datetime import datetime, timedelta, date
from typing import Optional

import pandas as pd
from kiteconnect import KiteConnect
from kiteconnect.exceptions import NetworkException, DataException

from util.db_util import write_historical_data
from util.global_variables import IST
from util.global_variables import KITE_API_REQUEST_RATE_PER_SECOND, \
    DB_INSERT_BUFFER_SIZE, SWING_CANDLE_LIMIT
from util.secret_manager_util import get_kite_access_token, get_kite_api_key
from util.telegram_bot import send_telegram_alert
from util.trade_logger import log

kite: Optional[KiteConnect] = None
_last_request_time: float = 0


def get_market_open() -> datetime:
    """
    Returns the market open time (09:15 AM) for the current day in IST.
    """
    return datetime.now(IST).replace(hour=9, minute=15, second=0, microsecond=0)


def get_market_close() -> datetime:
    return datetime.now(IST).replace(hour=15, minute=30, second=0, microsecond=0)


def get_kite_object(max_wait=180, retry_interval=5) -> KiteConnect:
    """
    Returns a valid KiteConnect instance.

    - Uses cached instance if available
    - Waits for fresh token if expired
    - Retries until max_wait
    """

    global kite

    # Fast path
    if kite:
        return kite

    alert_sent = False
    start_time = time.time()

    api_key = get_kite_api_key()
    login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"

    while time.time() - start_time < max_wait:

        access_token = get_kite_access_token()

        # ✅ Handle missing token
        if not access_token:
            log("warning", "No access token available yet. Waiting...")
            time.sleep(retry_interval)
            continue

        kite_obj = KiteConnect(api_key=api_key)
        kite_obj.set_access_token(access_token)
        kite_obj.timeout = 30

        try:
            kite_obj.profile()  # validation
            log("info", "Kite session established successfully.")
            kite = kite_obj
            return kite

        except Exception as e:
            log("warning", f"Token invalid/expired: {e}")

            # ✅ Send alert only once
            if not alert_sent:
                message = (
                    "🚨 <b>Kite Token Expired</b>\n"
                    "\n"
                    "Your trading session has ended and requires manual re-authentication.\n"
                    "\n"
                    f"🔗 <a href='{login_url}'>Login to Zerodha KiteConnect API</a>\n"
                )

                send_telegram_alert(message)
                send_telegram_alert(message)
                alert_sent = True

            time.sleep(retry_interval)

    # Hard fail
    raise RuntimeError("Unable to establish Kite session within time limit")


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

        if len(buffer) >= DB_INSERT_BUFFER_SIZE:
            write_historical_data(table_name, buffer)
            buffer.clear()

    if buffer:
        write_historical_data(table_name, buffer)