from util.global_variables import TRADING_CAPITAL, INTRADAY_LEVERAGE_MULTIPLIER
from util.trade_logger import log

# ── CONFIG ────────────────────────────────────────────────
MIN_PCT_CHANGE = 2.5
MAX_PCT_CHANGE = 6.5
MAX_PARTICIPATION_RATE = 0.7
buying_power = TRADING_CAPITAL * INTRADAY_LEVERAGE_MULTIPLIER


def is_strong_breakout_candle(breakout_candle,
                              body_threshold=0.5,
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


def is_early_momentum_breakout_candle(breakout_candle):
    # % price move from open
    price_change_pct = round((breakout_candle["close"] - breakout_candle["open"]) / breakout_candle["open"] * 100, 1)

    # Liquidity  condition
    participation_rate = round(
        (buying_power * 100) /
        (breakout_candle["close"] * breakout_candle["volume"]),
        2
    )

    return MAX_PCT_CHANGE >= price_change_pct >= MIN_PCT_CHANGE and participation_rate < MAX_PARTICIPATION_RATE


def is_valid_breakout_volume(breakout_candle,
                             min_multiplier=4):
    """
    """
    return breakout_candle['volume'] > min_multiplier * breakout_candle['volume_sma_20']


def is_early_momentum_breakout_detected(breakout_candle):
    if not is_strong_breakout_candle(breakout_candle):
        log("info", "Low bullish confidence")
        return False

    if not is_valid_breakout_volume(breakout_candle):
        log("info", "Low volume confidence")
        return False

    if not is_early_momentum_breakout_candle(breakout_candle):
        log("info", "Low momemtum confidence")
        return False

    return True
