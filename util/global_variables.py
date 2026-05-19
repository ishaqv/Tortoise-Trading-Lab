from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo


def str_to_bool(s: str) -> bool:
    return s.strip().lower() in ("true", "1", "yes", "y", "on")


INTRADAY_M5_TARGET_MULTIPLIER = 3.5
INTRADAY_M15_TARGET_MULTIPLIER = 2
INTRADAY_LEVERAGE_MULTIPLIER = 4.5  # Always maintain a minimum cash buffer of 10% undeployed at all times.
ATR_RISK_MULTIPLIER = 0.5
SWING_TARGET_MULTIPLIER = 3
INTRADAY_M5_CANDLE_SIZE = 5  # in minutes
INTRADAY_M15_CANDLE_SIZE = 15  # in minutes
SWING_CANDLE_SIZE = 1440  # in minutes
TRADING_MINUTES_PER_DAY = 375  # 9:15 AM - 3:30 PM
INTRADAY_HISTORICAL_DATA_CACHE_DAYS = 0.75  # minimum for correct indicator computation
INTRADAY_M5_CANDLE_LIMIT = int(
    (INTRADAY_HISTORICAL_DATA_CACHE_DAYS * TRADING_MINUTES_PER_DAY) // INTRADAY_M5_CANDLE_SIZE)
INTRADAY_M15_CANDLE_LIMIT = int(
    (INTRADAY_HISTORICAL_DATA_CACHE_DAYS * TRADING_MINUTES_PER_DAY) // INTRADAY_M15_CANDLE_SIZE)
SWING_CANDLE_LIMIT = 30
IST = ZoneInfo("Asia/Kolkata")
LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH = Path(__file__).resolve().parents[1] / "nse_liquid_shariah_symbol_token.csv"
LIQUID_SHARIAH_SYMBOL_FILE_PATH = Path(__file__).resolve().parents[1] / "nse_liquid_shariah_symbol.csv"
MASTER_SHARIAH_SYMBOL_TOKEN_FILE_PATH = Path(__file__).resolve().parents[1] / "nse_master_shariah_symbol_token.csv"
MASTER_SHARIAH_SYMBOL_FILE_PATH = Path(__file__).resolve().parents[1] / "nse_master_shariah_symbol.csv"
# EVB session
EVB_SCAN_CANDLE_TIME = time(9, 15)
BREAKOUT_CANDLE_IDX = -1
MAX_WORKERS = 2
KITE_API_REQUEST_RATE_PER_SECOND = 10
DB_INSERT_BUFFER_SIZE = 1000
GCP_PROJECT_ID = "trading-vps-463502"
TRADING_CAPITAL = 500000
MAX_RISK_PER_TRADE_PERCENT = 0.02
MIN_ADV_PARTICIPATION_RATE = 0.02
MAX_BREAKOUT_PARTICIPATION = 0.50
