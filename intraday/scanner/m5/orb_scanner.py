from util.global_variables import BREAKOUT_CANDLE_IDX, INTRADAY_M5_CANDLE_SIZE, OR_IN_MINUTES
from util.trade_logger import log


def get_opening_range_end_index():
    """
        Determines the ending index (i.e., number of candles) for the opening range
    """

    return int(OR_IN_MINUTES / INTRADAY_M5_CANDLE_SIZE)


def get_opening_range_values(df_trading_day):
    """
    Computes the Opening Range (OR) values from the initial candles of the trading day.
    """

    opening_range_df = df_trading_day.iloc[:get_opening_range_end_index()]

    return {
        'high': opening_range_df['high'].max(),
        'low': opening_range_df['low'].min()
    }


def is_strong_orb_candle(df_trading_day,
                         body_threshold=0.6,
                         max_wick_ratio=0.25,
                         max_body_atr_multiplier=3):
    """
    Determines whether the breakout candle is a strong, healthy bullish candle.

    This function helps validate breakout quality by filtering out candles that:
        - Are not bullish (close <= open).
        - Have small bodies (weak intent).
        - Have long upper wicks (possible rejection).
        - Are too small (low conviction) or too large (overextended) relative to ATR.

    Candle quality is scored based on:
        - Body-to-range ratio (more body = more score).
        - Upper wick size (smaller = better).
        - Body size in ATR terms (must lie within healthy range).
    """

    breakout_candle = df_trading_day.iloc[BREAKOUT_CANDLE_IDX]

    breakout_open, breakout_close, breakout_high, breakout_low, breakout_volume, breakout_atr = (
        breakout_candle['open'], breakout_candle['close'], breakout_candle['high'],
        breakout_candle['low'], breakout_candle['volume'], breakout_candle['atr']
    )

    # Must be a bullish candle
    breakout_candle_range = breakout_high - breakout_low
    if breakout_close <= breakout_open or breakout_candle_range == 0:
        return False

    # Body check
    body = breakout_close - breakout_open
    body_pct = body / breakout_candle_range
    if body_pct < body_threshold:
        return False

    # wick check
    upper_wick_pct = (breakout_high - breakout_close) / breakout_candle_range
    if upper_wick_pct > max_wick_ratio:
        return False

    # Rejecting over extended moves
    if body > breakout_atr * max_body_atr_multiplier:
        return False

    return True


def is_strong_orb_volume(df_trading_day,
                         min_multiplier=2):
    """
        Evaluates whether the breakout candle in an Opening Range Breakout (ORB) setup
        is backed by strong relative volume compared to the opening range.
    """
    breakout_candle = df_trading_day.iloc[BREAKOUT_CANDLE_IDX]
    breakout_vol = breakout_candle['volume']

    vol_sma = breakout_candle['volume_sma_20']
    # Reject if too weak or too extreme
    return min_multiplier * vol_sma <= breakout_vol


def is_orb_breakout(df_trading_day,
                    max_or_range_in_atr=2.5):
    """
    Validates whether the stock is forming a strong Opening Range Breakout (ORB) setup.

    An ORB is defined as a breakout above the high of the initial trading range (typically the first
    15 or 30 minutes). This method checks whether the breakout is fresh, strong, and occurs from a
    compressed base, which increases the likelihood of sustained momentum.
    """

    opening_range_values = get_opening_range_values(df_trading_day)
    opening_range_high = opening_range_values["high"]
    opening_range_low = opening_range_values["low"]
    breakout_candle = df_trading_day.iloc[BREAKOUT_CANDLE_IDX]

    or_range = opening_range_high - opening_range_low
    or_range_atr_ratio = or_range / breakout_candle["atr"]

    # Breakout candle must close above ORH
    if breakout_candle["close"] <= opening_range_high:
        return False

    # Candle must move at least 10% of opening range
    if (breakout_candle["close"] - opening_range_high) < 0.1 * or_range:
        return False

    # Count prior tests of ORH
    opening_range_end_index = get_opening_range_end_index()
    post_or_df = df_trading_day.iloc[opening_range_end_index:BREAKOUT_CANDLE_IDX]
    wick_test_count = sum(row["high"] > opening_range_high for _, row in post_or_df.iterrows())
    close_test_count = sum(row["close"] > opening_range_high for _, row in post_or_df.iterrows())

    # Already broken/multiple failed attempt
    if close_test_count > 0 or wick_test_count > 1:
        return False

    # OR too wide
    return or_range_atr_ratio < max_or_range_in_atr


def get_previous_day_high(df):
    """
    """

    date_only = df['date'].dt.date
    unique_dates = date_only.unique()

    # === Previous N-day highs ===
    def get_n_day_high(n):
        if len(unique_dates) <= n:
            return None
        selected_day = unique_dates[-n - 1]
        return df[date_only == selected_day]['high'].max()

    return get_n_day_high(1)


def is_previous_day_high_broken(df_previous_day, breakout_candle):
    return breakout_candle["close"] > df_previous_day["high"].max()


def is_orb_detected(df_previous_day, df_trading_day):
    if not is_strong_orb_candle(df_trading_day):
        log("info", "Low bullish confidence")
        return False

    if not is_strong_orb_volume(df_trading_day):
        log("info", "Low volume confidence")
        return False

    if not is_orb_breakout(df_trading_day):
        log("info", "Low ORB confidence")
        return False

    breakout_candle = df_trading_day.iloc[BREAKOUT_CANDLE_IDX]

    if not is_previous_day_high_broken(df_previous_day, breakout_candle):
        log("info", "PDH is not broken")
        return False

    return True
