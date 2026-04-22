import os
import threading
from datetime import timedelta, datetime, date

import mysql.connector
import pandas as pd

from util.global_variables import INTRADAY_M5_CANDLE_SIZE, INTRADAY_M5_CANDLE_LIMIT
from util.trade_logger import log

lock = threading.Lock()

pool = None


def get_db_connection():
    """
        Retrieves a database connection from the connection pool.
    """
    global pool

    if not pool:
        # Create a connection pool
        pool = mysql.connector.pooling.MySQLConnectionPool(
            pool_name="stock_db_pool",
            pool_size=10,  # Adjust based on the load
            host=os.getenv('DB_HOST'),
            port=int(os.getenv('DB_PORT', 3306)),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME'))

    return pool.get_connection()


def initialize_db(table_name):
    """
        Initializes the MySQL database by creating the `intraday_historical_data` table if it doesn't exist.
        The table stores intraday OHLCV data and is optimized with:
            - A unique constraint on (symbol, date) to prevent duplicates.
            - An index on (symbol, date DESC) to speed up recent data queries.
    """

    conn = None
    try:
        with lock:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                sql = f"""
                    CREATE TABLE IF NOT EXISTS `{table_name}` (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        symbol VARCHAR(10) NOT NULL,
                        date DATETIME NOT NULL,
                        open DECIMAL(15, 4),
                        high DECIMAL(15, 4),
                        low DECIMAL(15, 4),
                        close DECIMAL(15, 4),
                        volume BIGINT,
                        UNIQUE KEY unique_symbol_date (symbol, date),
                        INDEX idx_symbol_date_desc (symbol, date DESC)                        
                    ) ENGINE=InnoDB
                """
                cursor.execute(sql)

                conn.commit()

    except mysql.connector.Error as e:
        log("error", f"❌ MySQL database initialization error: {e}", exc_info=True)
        if conn:
            conn.rollback()

    finally:
        if conn:
            conn.close()


def purge_old_historical_data(table_name, symbols, candle_limit, optimize_after=True):
    """
        Purges outdated or irrelevant data from the `intraday_historical_data` table.

        Steps:
        1. Deletes rows for any symbol *not* present in the current Shariah-compliant list.
           - This step ensures stale/delisted symbols are cleaned up.
        2. Retains only the latest `CANDLE_LIMIT` rows per valid symbol (based on descending datetime).
           - Helps control data size for high-frequency symbols.
    """

    conn = None
    try:
        with lock:
            conn = get_db_connection()
            with conn.cursor(buffered=True) as cursor:

                # Step 1: Delete rows that do NOT belong to any symbol in the list

                # The Shariah-compliant symbols list changes every two days.
                # This purge ensures that any outdated or residual data for delisted symbols is removed from the database.

                format_strings = ','.join(['%s'] * len(symbols))
                sql = f"""
                    DELETE FROM `{table_name}`
                    WHERE symbol NOT IN ({format_strings})
                """
                cursor.execute(sql, symbols)

                # Step 2: Keep only the latest 'candle_limit' rows per symbol
                for symbol in symbols:
                    sql = f"""
                        DELETE hd FROM `{table_name}` hd
                        LEFT JOIN (
                            SELECT id FROM `{table_name}` 
                            WHERE symbol = %s 
                            ORDER BY date DESC 
                            LIMIT %s
                        ) AS keep_rows ON hd.id = keep_rows.id
                        WHERE hd.symbol = %s AND keep_rows.id IS NULL
                    """
                    cursor.execute(sql, (symbol, candle_limit, symbol))
                conn.commit()

            if optimize_after:
                with conn.cursor(buffered=True) as optimize_cursor:
                    sql = f"OPTIMIZE TABLE `{table_name}`"
                    optimize_cursor.execute(sql)
                    log("info", "✅ Table optimization completed")

    except mysql.connector.Error as e:
        log("error", f"❌ Purge error: {e}", exc_info=True)
        if conn:
            conn.rollback()

    finally:
        if conn:
            conn.close()


def write_historical_data(table_name, buffer):
    """
        Performs a bulk insert of historical candle data into the `intraday_historical_data` table.

        Behavior:
        - Uses `INSERT ... ON DUPLICATE KEY UPDATE` to avoid duplicate rows for (symbol, date).
        - If a duplicate exists, the record is updated with the new OHLCV values.
        - Thread-safe with `lock` to ensure only one thread writes at a time.
        - Automatically clears the buffer after successful insertion.
    """

    conn = None
    try:
        with lock:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                sql = f"""
                    INSERT INTO `{table_name}` (symbol, date, open, high, low, close, volume)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        open = VALUES(open),
                        high = VALUES(high),
                        low = VALUES(low),
                        close = VALUES(close),
                        volume = VALUES(volume)
                """
                cursor.executemany(sql, buffer)
                conn.commit()
                log("info", f"✅ Successfully inserted {len(buffer)} records into the database.")
                buffer.clear()

    except Exception as e:
        if conn:
            conn.rollback()
        log("error", f"❌ Database error during batch insert: {e}", exc_info=True)

    finally:
        if conn:
            conn.close()


def get_last_stored_timestamp_for_symbols(table_name, symbols):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:

            format_strings = ','.join(['%s'] * len(symbols))

            # SQL orders DESC purely as a pagination trick — ROW_NUMBER() + rn <= N is the most efficient
            # way to fetch the last N candles per symbol. The DESC order itself is a means to an end,
            # not the desired consumption order.
            query = f"""
                SELECT symbol, date
                FROM (
                    SELECT 
                        symbol,
                        date,
                        ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) as rn
                    FROM `{table_name}`
                    WHERE symbol IN ({format_strings})
                ) t
                WHERE rn <= %s
                ORDER BY symbol, date DESC
            """

            cursor.execute(query, (*symbols, INTRADAY_M5_CANDLE_LIMIT))
            rows = cursor.fetchall()

        if not rows:
            return {}

        # Group by symbol — timestamps are in DESC order
        symbol_map = {}
        for symbol, ts in rows:
            symbol_map.setdefault(symbol, []).append(ts)

        result = {}

        for symbol, timestamps in symbol_map.items():
            for i in range(len(timestamps) - 1):
                current = timestamps[i]
                prev = timestamps[i + 1]

                if prev != current - timedelta(minutes=INTRADAY_M5_CANDLE_SIZE):
                    result[symbol] = prev  # gap found, returing last continous timestamp
                    break
            else:
                result[symbol] = timestamps[0]  # no gap found, all continuous — most recent is correct

        return result

    except Exception as e:
        log("error", f"❌ Bulk fetch error: {e}", exc_info=True)
        return {}

    finally:
        if conn:
            conn.close()


def get_last_stored_date_for_symbols(table_name: str, symbols: list[str]) -> dict[str, date]:
    """Returns the latest stored date per symbol for daily candles."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            format_strings = ','.join(['%s'] * len(symbols))

            query = f"""
                SELECT symbol, MAX(date) as latest_date
                FROM `{table_name}`
                WHERE symbol IN ({format_strings})
                GROUP BY symbol
            """

            cursor.execute(query, symbols)
            rows = cursor.fetchall()

        return {symbol: latest_date for symbol, latest_date in rows} if rows else {}

    except Exception as e:
        log("error", f"❌ Bulk fetch error: {e}", exc_info=True)
        return {}

    finally:
        if conn:
            conn.close()


def fetch_data(table_name, symbol, candle_limit):
    """
        Fetches the most recent  records for the given stock symbol from the `intraday_historical_data` table.

        Behavior:
        - Retrieves the latest `CANDLE_LIMIT` rows for the specified symbol, sorted by date in descending order.
        - Returns a list of tuples, each representing a row.
    """

    conn = None
    data = []
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = f"""
                SELECT * FROM `{table_name}`
                WHERE symbol = %s
                ORDER BY date DESC
                LIMIT %s
            """
            cursor.execute(sql, (symbol, candle_limit))
            data = cursor.fetchall()

    except Exception as e:
        log("error", f"❌ Error fetching historical data for symbol {symbol}: {e}", exc_info=True)

    finally:
        if conn:
            conn.close()

    return data


def get_last_timestamp_map(symbol_df_map) -> dict[str, datetime]:
    """
    Returns a dict of {symbol: latest_timestamp} by reusing get_historical_data_for_symbols.
    Used to determine the from_date for the next historical data fetch per symbol.
    """

    return {
        symbol: df['date'].iloc[-1]  # iloc[-1] = latest candle since df is in ASC order
        for symbol, df in symbol_df_map.items()
    }


def get_historical_data_for_symbols(table_name, symbols) -> dict[str, pd.DataFrame]:
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:

            format_strings = ','.join(['%s'] * len(symbols))

            # SQL orders DESC purely as a pagination trick — ROW_NUMBER() + rn <= N is the most efficient
            # way to fetch the last N candles per symbol. The DESC order itself is a means to an end,
            # not the desired consumption order.
            query = f"""
                SELECT *
                FROM (
                    SELECT 
                        id,
                        symbol,
                        date,
                        open,
                        high,
                        low,
                        close,
                        volume,
                        ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) as rn
                    FROM `{table_name}`
                    WHERE symbol IN ({format_strings})
                ) t
                WHERE rn <= %s
                ORDER BY symbol, date DESC
            """

            cursor.execute(query, (*symbols, INTRADAY_M5_CANDLE_LIMIT))
            rows = cursor.fetchall()

        if not rows:
            return {}

        # Build DataFrame from raw rows; drop rn (SQL window function artifact, not needed beyond row limiting)
        df = pd.DataFrame(rows, columns=['id', 'symbol', 'date', 'open', 'high', 'low', 'close', 'volume', 'rn'])
        df = df.drop(columns=['rn'])

        # Coerce OHLCV columns to numeric — invalid/corrupt values become NaN
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors='coerce')
        df['date'] = pd.to_datetime(df['date'])

        # Reverse DESC → ASC to restore natural chronological order for time-series consumption.
        # ASC is the expected order for all downstream work — indicator calculations (RSI, EMA etc.),
        # iloc[-1] to access the latest candle, and any charting.
        # iloc[::-1] is used over sort_values() since data is already sorted — O(n) reversal vs O(n log n) re-sort.
        df = df.dropna().iloc[::-1].reset_index(drop=True)

        # Split into per-symbol DataFrames — each with a clean 0-based index
        return {symbol: group.reset_index(drop=True) for symbol, group in df.groupby('symbol')}

    except Exception as e:
        log("error", f"❌ Bulk fetch error: {e}", exc_info=True)
        return {}

    finally:
        if conn:
            conn.close()


def fetch_liquid_symbols(capital, adv_days=20, participation_rate=0.005,  # your order ≤ 0.5% of stock's daily value
                         ):
    """
    Full-capital deployment ADV filter.

    Liquidity rule:
        capital ≤ participation_rate × ADV
        → min_adv = capital / participation_rate
    """

    conn = None
    symbols = []

    min_adv = capital / participation_rate
    table_name = get_table_name("d1")
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:

            sql = f"""
                SELECT symbol
                FROM (
                    SELECT
                        symbol,
                        COUNT(*)            AS days_available,
                        AVG(close * volume) AS adv
                    FROM (
                        SELECT
                            symbol,
                            close,
                            volume,
                            ROW_NUMBER() OVER (
                                PARTITION BY symbol
                                ORDER BY date DESC
                            ) AS rn
                        FROM `{table_name}`
                    ) ranked
                    WHERE rn <= %s
                    GROUP BY symbol
                ) final
                WHERE days_available = %s
                AND adv >= %s
                ORDER BY adv DESC;
            """

            cursor.execute(sql, (adv_days, adv_days, min_adv))
            symbols = [row[0] for row in cursor.fetchall()]

            log("info", (
                f"ADV filter | capital=₹{capital:,.0f} | "
                f"min_adv=₹{min_adv:,.0f} | "
                f"passed={len(symbols)}"
            ))

    except Exception as e:
        log("error", f"❌ ADV filter error: {e}", exc_info=True)

    finally:
        if conn:
            conn.close()

    return symbols


def get_table_name(timeframe):
    return timeframe + "_historical_data"
