from util.global_variables import TRADING_CAPITAL, INTRADAY_LEVERAGE_MULTIPLIER
from util.trade_logger import log

MIN_PCT_CHANGE = 3.5
MAX_PCT_CHANGE = 7.5

buying_power = TRADING_CAPITAL * INTRADAY_LEVERAGE_MULTIPLIER


def is_valid_price_change(breakout_candle):
    """
    Determines whether the breakout candle is a strong, healthy bullish candle(body > 50% and upper wick < 35%).
    """

    # % price move from open
    price_change_pct = round((breakout_candle["close"] - breakout_candle["open"]) / breakout_candle["open"] * 100, 1)
    return MAX_PCT_CHANGE >= price_change_pct >= MIN_PCT_CHANGE


def is_explosive_breakout_volume(breakout_candle,
                                 min_multiplier=25):
    """
    breakout_volume should exceed 2 standard deviations above the mean.
    When you see a volume bar above mean + 2σ, it usually signals institutional activity, breakout force
    """
    # Reject if too weak or too extreme
    return breakout_candle['volume'] > min_multiplier * breakout_candle['volume_sma_20']


def is_volume_explosion_long_breakout_detected(breakout_candle):
    if not is_valid_price_change(breakout_candle):
        log("info", "Low price change confidence")
        return False

    if not is_explosive_breakout_volume(breakout_candle):
        log("info", "Low volume confidence")
        return False

    return True
