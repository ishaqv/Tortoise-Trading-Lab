def is_strong_breakout_candle(breakout_candle,
                              body_threshold=0.6,
                              max_wick_ratio=0.3):
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

    return True


def is_valid_opening_gap(gap_pct, max_opening_gap_pct):
    return gap_pct <= max_opening_gap_pct


def is_liquid_breakout(participation_rate, max_participation_rate):
    return participation_rate <= max_participation_rate


def is_valid_price_change(breakout_candle, min_price_change, max_price_change):
    """
    """
    # % price move from open
    if breakout_candle["open"] <= 0:
        return False

    price_change_pct = (
                               (breakout_candle["close"] - breakout_candle["open"])
                               / breakout_candle["open"]
                       ) * 100

    return min_price_change <= price_change_pct <= max_price_change


def is_valid_breakout_volume(breakout_candle, min_volume_multiplier):
    """
    """
    return breakout_candle['volume'] > min_volume_multiplier * breakout_candle['volume_sma_20']
