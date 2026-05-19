from util.trade_logger import log


def is_strong_breakout_candle(breakout_candle,
                              body_threshold=0.6,
                              max_wick_ratio=0.25,
                              max_body_atr_multiplier=6):
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


def is_explosive_breakout_volume(breakout_candle,
                                 min_multiplier=17):
    """
    breakout_volume should exceed 2 standard deviations above the mean.
    When you see a volume bar above mean + 2σ, it usually signals institutional activity, breakout force
    """
    # Reject if too weak or too extreme
    return breakout_candle['volume'] > min_multiplier * breakout_candle['volume_sma_20']


def is_volume_explosion_long_breakout_detected(breakout_candle):
    if not is_strong_breakout_candle(breakout_candle):
        log("info", "Low bullish confidence")
        return False

    if not is_explosive_breakout_volume(breakout_candle):
        log("info", "Low volume confidence")
        return False

    return True
