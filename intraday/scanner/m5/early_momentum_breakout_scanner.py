from util.scanner_util import is_liquid_breakout, is_valid_opening_gap, is_valid_price_change, is_valid_breakout_volume
from util.trade_logger import log

# ── CONFIG ────────────────
MIN_PRICE_CHANGE = 3.25
MAX_PRICE_CHANGE = 8.5
MAX_OPENING_GAP_PCT = 2.5
MAX_PARTICIPATION_RATE = 0.85
MIN_VOLUME_MULTIPLIER = 3


def is_early_momentum_breakout_detected(breakout_candle, participation_rate, opening_gap_pct):
    if not is_liquid_breakout(participation_rate, MAX_PARTICIPATION_RATE):
        log("info", "EMB - Low participation confidence")
        return False

    if not is_valid_opening_gap(opening_gap_pct, MAX_OPENING_GAP_PCT):
        log("info", "EMB - Low gap confidence")
        return False

    if not is_valid_price_change(breakout_candle, MIN_PRICE_CHANGE, MAX_PRICE_CHANGE):
        log("info", "EMB - Low price change confidence")
        return False

    if not is_valid_breakout_volume(breakout_candle, MIN_VOLUME_MULTIPLIER):
        log("info", "EMB - Low volume confidence")
        return False

    return True
