from util.scanner_util import is_liquid_breakout, is_valid_opening_gap, is_valid_price_change, is_valid_breakout_volume
from util.trade_logger import log

# ── CONFIG ────────────────
MIN_PRICE_CHANGE = 3.5
MAX_PRICE_CHANGE = 9
MAX_OPENING_GAP_PCT = 5.0
MAX_PARTICIPATION_RATE = 4.0
MIN_VOLUME_MULTIPLIER = 15
IDEAL_PARTICIPATION_RATE = 0.50

def is_volume_explosion_breakout_detected(breakout_candle, participation_rate, opening_gap_pct):
    if not is_liquid_breakout(participation_rate, MAX_PARTICIPATION_RATE):
        log("info", "EVB - Low participation confidence")
        return False

    if not is_valid_opening_gap(opening_gap_pct, MAX_OPENING_GAP_PCT):
        log("info", "EVB - Low gap confidence")
        return False

    if participation_rate < IDEAL_PARTICIPATION_RATE:
        min_price_change = 2.50
    else:
        min_price_change = MIN_PRICE_CHANGE

    if not is_valid_price_change(breakout_candle, min_price_change, MAX_PRICE_CHANGE):
        log("info", "EVB - Low price change confidence")
        return False

    if not is_valid_breakout_volume(breakout_candle, MIN_VOLUME_MULTIPLIER):
        log("info", "EVB - Low volume confidence")
        return False

    return True
