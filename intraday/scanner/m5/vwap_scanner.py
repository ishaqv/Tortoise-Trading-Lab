import pandas as pd

from util.global_variables import BREAKOUT_CANDLE_IDX
from util.trade_logger import log


def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    cum_price_volume = (typical_price * df['volume']).cumsum()
    cum_volume = df['volume'].cumsum()
    vwap = (cum_price_volume / cum_volume).round(2)
    return vwap


def is_strong_bullish_breakout_candle(df_trading_day,
                                      body_threshold=0.6,
                                      max_upper_wick_ratio=0.25,
                                      max_lower_wick_ratio=0.25,
                                      max_body_atr_multiplier=5):
    """
    """
    breakout_candle = df_trading_day.iloc[BREAKOUT_CANDLE_IDX]

    breakout_open = breakout_candle['open']
    breakout_close = breakout_candle['close']
    breakout_high = breakout_candle['high']
    breakout_low = breakout_candle['low']
    breakout_atr = breakout_candle['atr']

    breakout_candle_range = breakout_high - breakout_low
    if breakout_close <= breakout_open or breakout_candle_range == 0:
        return False

    body = breakout_close - breakout_open

    # Body ratio
    body_pct = body / breakout_candle_range
    if body_pct < body_threshold:
        return False

    # Upper wick — rejection check (unchanged)
    upper_wick_pct = (breakout_high - breakout_close) / breakout_candle_range
    if upper_wick_pct > max_upper_wick_ratio:
        return False

    # Lower wick — NEW: seller pushback check
    lower_wick_pct = (breakout_open - breakout_low) / breakout_candle_range
    if lower_wick_pct > max_lower_wick_ratio:
        return False

    # Overextended move
    if body > breakout_atr * max_body_atr_multiplier:
        return False

    return True


def is_strong_breakout_volume(df_trading_day, lookback,
                              min_multiplier=2,
                              compression_declining_vol=True):
    """
    """
    breakout_candle = df_trading_day.iloc[BREAKOUT_CANDLE_IDX]
    breakout_vol = breakout_candle['volume']
    vol_sma = breakout_candle['volume_sma_20']

    # Original check: breakout volume must spike hard
    if not (min_multiplier * vol_sma < breakout_vol):
        return False

    # NEW: Volume during compression should be below average (the coil)
    if compression_declining_vol:
        compression_candles = df_trading_day.iloc[
            BREAKOUT_CANDLE_IDX - lookback: BREAKOUT_CANDLE_IDX
        ]
        avg_compression_vol = compression_candles['volume'].mean()

        # Compression volume should be below the 20-period SMA
        # meaning the market was quieting down before the breakout
        if avg_compression_vol >= vol_sma:
            return False

    return True


def is_vwap_breakout(df_trading_day,
                     lookback,
                     atr_multiplier_strong=0.15):
    """
    """
    df_trading_day['vwap'] = calculate_vwap(df_trading_day)
    breakout_candle = df_trading_day.iloc[BREAKOUT_CANDLE_IDX]

    raw_vwap = breakout_candle['vwap']
    adjusted_vwap = raw_vwap + atr_multiplier_strong * breakout_candle['atr']

    # Close must be decisively above VWAP + buffer
    if breakout_candle['close'] < adjusted_vwap:
        return False

    # Candle must start under VWAP and close above it — that's a reclaim
    if breakout_candle['open'] >= raw_vwap:
        return False

    # NEW: Prior candles must have been below VWAP
    # Confirms this is a genuine reclaim, not just VWAP oscillation
    min_candles_below_vwap = int(lookback * 0.8)
    prior_candles = df_trading_day.iloc[
        BREAKOUT_CANDLE_IDX - min_candles_below_vwap: BREAKOUT_CANDLE_IDX
    ]
    candles_below_vwap = (prior_candles['close'] < prior_candles['vwap']).sum()
    if candles_below_vwap < min_candles_below_vwap:
        return False

    return True


def is_compressed_range(range_df,
                        atr,
                        box_factor=0.75,
                        stddev_factor=0.30,
                        range_std_factor=0.35,
                        min_score=2,
                        max_drift_factor=0.4):
    """
    """
    if atr <= 0 or len(range_df) < 3:
        return False

    score = 0

    # Check 1: FIX — use actual high/low for box, not body
    box_range = range_df['high'].max() - range_df['low'].min()
    if box_range / atr <= box_factor:
        score += 1

    # Check 2: Close clustering
    std_close = range_df['close'].std()
    if std_close / atr <= stddev_factor:
        score += 1

    # Check 3: Candle range consistency
    candle_ranges = range_df['high'] - range_df['low']
    range_std = candle_ranges.std()
    if range_std / atr <= range_std_factor:
        score += 1

    if score < min_score:
        return False

    # NEW: Drift check — consolidation must be roughly horizontal
    price_drift = abs(range_df['close'].iloc[-1] - range_df['close'].iloc[0])
    if price_drift / atr > max_drift_factor:
        return False

    return True


def is_vwap_breakout_detected(df_trading_day, is_compression_enabled, lookback=10):
    if not is_strong_bullish_breakout_candle(df_trading_day):
        log("info", "Low bullish confidence")
        return False

    if not is_strong_breakout_volume(df_trading_day, lookback=lookback):
        log("info", "Low volume confidence")
        return False

    range_df = df_trading_day.iloc[BREAKOUT_CANDLE_IDX - lookback: BREAKOUT_CANDLE_IDX]
    atr = df_trading_day['atr'].iloc[BREAKOUT_CANDLE_IDX]

    if is_compression_enabled and not is_compressed_range(range_df, atr):
        log("info", "Low compression confidence")
        return False

    if not is_vwap_breakout(df_trading_day, lookback=lookback):
        log("info", "Low VWAP breakout confidence")
        return False

    return True