from datetime import timedelta, datetime, date

import pandas as pd

from util.db_util import write_historical_data
from util.global_variables import IST, SWING_CANDLE_LIMIT, DB_INSERT_BUFFER_SIZE
from util.kite_util import fetch_historical_data_from_kite
from util.trade_logger import log


def get_market_open() -> datetime:
    """
    Returns the market open time (09:15 AM) for the current day in IST.
    """
    return datetime.now(IST).replace(hour=9, minute=15, second=0, microsecond=0)


def get_market_close() -> datetime:
    return datetime.now(IST).replace(hour=15, minute=30, second=0, microsecond=0)


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
        log("exception", f"⚠️ Kite historical data fetch failed for {symbol}: {e}", exc_info=True)
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
        log("exception", f"⚠️ Kite historical daily candle data fetch failed for {symbol}: {e}", exc_info=True)
        return []


def append_latest_candle_data_from_kite(
        interval,
        symbol_token_map,
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

    for symbol, instrument_token in symbol_token_map.items():

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
        symbol_token_map,
        candle_size,
        last_ts_map
):
    buffer = []

    for symbol, instrument_token in symbol_token_map.items():
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
