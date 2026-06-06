# switch to the correct db
USE algotrading;


# Top N Gainers

# d1_historical_data - daily candle data is persisted here

WITH ranked_days AS (
    SELECT
        symbol,
        trade_date,
        close,
        LAG(close) OVER (PARTITION BY symbol ORDER BY trade_date) AS prev_close
    FROM d1_historical_data
    WHERE trade_date >= CURDATE() - INTERVAL 7 DAY  -- small window for efficiency
),
latest AS (
    SELECT
        symbol,
        close       AS close_today,
        prev_close  AS close_yesterday,
        ROUND(((close - prev_close) / prev_close) * 100, 2) AS percent_change
    FROM ranked_days
    WHERE DATE(trade_date) = (SELECT MAX(DATE(trade_date)) FROM d1_historical_data)
)
SELECT
    symbol,
    close_today,
    close_yesterday,
    percent_change
FROM latest
WHERE close_yesterday IS NOT NULL
  AND percent_change > 3
ORDER BY percent_change DESC
LIMIT 10;