from util.global_variables import BREAKOUT_CANDLE_IDX
from util.trade_logger import log


def is_compressed_range(range_df,
                        atr,
                        box_factor=1.5,
                        stddev_factor=0.35,
                        range_std_factor=0.25):
    """
    Detect true price compression (volatility + direction contraction)
    """

    if atr <= 0:
        return False

    # 1. Box range vs ATR
    box_range = range_df['high'].max() - range_df['low'].min()
    box_tight = box_range / atr <= box_factor

    # 2. Close clustering
    std_close = range_df['close'].std()
    close_tight = std_close / atr <= stddev_factor

    # 3. Candle range consistency (kills wick traps)
    candle_ranges = range_df['high'] - range_df['low']
    range_std = candle_ranges.std()
    range_std_tight = range_std / atr <= range_std_factor

    return (
            box_tight
            and close_tight
            and range_std_tight
    )


def is_strong_breakout_candle(breakout_candle,
                              body_threshold=0.6,
                              max_wick_ratio=0.3,
                              max_body_atr_multiplier=2):
    """
    Determines whether the breakout candle is a strong, healthy bullish candle(body > 50% and upper wick < 35%).
    """

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


def is_strong_breakout_volume(breakout_candle,
                              min_multiplier=1.5):
    """
    """
    # Reject if too weak
    return breakout_candle['volume'] > min_multiplier * breakout_candle['volume_sma_20']


def is_range_breakout(breakout_candle, range_df):
    range_high = range_df['high'].max()

    # Breakout candle must close above the compression range
    if breakout_candle["close"] <= range_high:
        return False

    box_range = range_df['high'].max() - range_df['low'].min()
    # Candle must move at least 10% above the compression range
    if (breakout_candle["close"] - range_high) < 0.1 * box_range:
        return False

    return True


def is_compressed_range_breakout_detected(df, lookback=12):
    range_df = df.iloc[BREAKOUT_CANDLE_IDX - lookback: BREAKOUT_CANDLE_IDX]
    breakout_candle = df.iloc[BREAKOUT_CANDLE_IDX]

    if not is_compressed_range(range_df, breakout_candle['atr']):
        log("info", "Low compression confidence")
        return False

    if not is_strong_breakout_candle(breakout_candle):
        log("info", "Low bullish confidence")
        return False

    if not is_strong_breakout_volume(breakout_candle):
        log("info", "Low volume confidence")
        return False

    if not is_range_breakout(breakout_candle, range_df):
        log("info", "Low range breakout confidence")
        return False

    return True
