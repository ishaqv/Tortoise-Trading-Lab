from util.global_variables import BREAKOUT_CANDLE_IDX
from util.trade_logger import log


def get_stop_distance(candle):
    """Stop below the breakout week's low (or just under MA50), at least 1 ATR away.
    Replaces 'close - open', which gave tiny stops on small-bodied candles."""
    stop = min(candle["low"], candle["ma_50"] - 0.5 * candle["atr"])
    return round(max(candle["close"] - stop, candle["atr"]), 2)


def is_ma50_breakout(df, lookup=25, max_violations=2, min_atr_distance=0.25, max_atr_distance=1.5):
    if len(df) < lookup + 1:
        return False

    latest = df.iloc[BREAKOUT_CANDLE_IDX]
    previous = df.iloc[-(lookup + 1):BREAKOUT_CANDLE_IDX]

    # Mostly below MA50 before the breakout (allow a couple of stray closes above)
    if (previous["close"] >= previous["ma_50"]).sum() > max_violations:
        return False

    # Closes above MA50, but not already extended
    if latest["close"] <= latest["ma_50"]:
        return False
    atr_distance = (latest["close"] - latest["ma_50"]) / latest["atr"]
    if not (min_atr_distance <= atr_distance <= max_atr_distance):
        return False

    # Bullish week that closes in its upper half
    rng = latest["high"] - latest["low"]
    if rng <= 0 or latest["close"] <= latest["open"]:
        return False
    if (latest["close"] - latest["low"]) / rng < 0.5:
        return False

    return True


def is_valid_breakout_volume(breakout_candle, min_volume_multiplier=1.5):
    return breakout_candle["volume"] > min_volume_multiplier * breakout_candle["volume_sma_20"]


def is_ma50_breakout_detected(df):
    if not is_ma50_breakout(df):
        log("info", "MA50 - Low breakout confidence")
        return False

    if not is_valid_breakout_volume(df.iloc[BREAKOUT_CANDLE_IDX]):
        log("info", "MA50 - Low volume confidence")
        return False

    return True
