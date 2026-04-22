import os
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def str_to_bool(s: str) -> bool:
    return s.strip().lower() in ("true", "1", "yes", "y", "on")


INTRADAY_M5_TARGET_MULTIPLIER = float(os.getenv('INTRADAY_M5_TARGET_MULTIPLIER', "3"))
INTRADAY_M15_TARGET_MULTIPLIER = float(os.getenv('INTRADAY_M15_TARGET_MULTIPLIER', "2"))
INTRADAY_LEVERAGE_MULTIPLIER = int(os.getenv('INTRADAY_LEVERAGE_MULTIPLIER', "5"))
ATR_RISK_MULTIPLIER = float(os.getenv('ATR_RISK_MULTIPLIER', "1.0"))
SWING_TARGET_MULTIPLIER = 3
OR_IN_MINUTES = 30  # First 30 minutes
INTRADAY_M5_CANDLE_SIZE = 5  # in minutes
INTRADAY_M15_CANDLE_SIZE = 15  # in minutes
SWING_CANDLE_SIZE = 24 * 60  # in minutes
TRADING_MINUTES_PER_DAY = 375  # 9:15 AM - 3:30 PM
CACHE_DAYS = 365
INTRADAY_HISTORICAL_DATA_CACHE_DAYS = 0.75  # minimum for correct indicator computation
INTRADAY_M5_CANDLE_LIMIT = int(
    (INTRADAY_HISTORICAL_DATA_CACHE_DAYS * TRADING_MINUTES_PER_DAY) // INTRADAY_M5_CANDLE_SIZE)
INTRADAY_M15_CANDLE_LIMIT = int(
    (INTRADAY_HISTORICAL_DATA_CACHE_DAYS * TRADING_MINUTES_PER_DAY) // INTRADAY_M15_CANDLE_SIZE)
SWING_HISTORICAL_DATA_CACHE_DAYS = 30
SWING_CANDLE_LIMIT = SWING_HISTORICAL_DATA_CACHE_DAYS
IST = ZoneInfo("Asia/Kolkata")
LIQUID_SHARIAH_SYMBOL_TOKEN_FILE_PATH = Path(__file__).resolve().parents[1] / "nse_liquid_shariah_symbol_token.csv"
LIQUID_SHARIAH_SYMBOL_FILE_PATH = Path(__file__).resolve().parents[1] / "nse_liquid_shariah_symbol.csv"
MASTER_SHARIAH_SYMBOL_TOKEN_FILE_PATH = Path(__file__).resolve().parents[1] / "nse_master_shariah_symbol_token.csv"
MASTER_SHARIAH_SYMBOL_FILE_PATH = Path(__file__).resolve().parents[1] / "nse_master_shariah_symbol.csv"
TRADING_CAPITAL = int(os.getenv('TRADING_CAPITAL', "200000"))
MAX_RISK_PER_TRADE_PERCENT = float(os.getenv('MAX_RISK_PER_TRADE_PERCENT', '0.01'))

# EVB session
EVB_SCAN_CANDLE_TIME = time(9, 15)

# ORB session
ORB_SCAN_CANDLE_START_TIME = time(9, 45)
ORB_SCAN_CANDLE_END_TIME = time(10, 5)

# VWAP session
VWAP_SCAN_CANDLE_START_TIME = time(10, 10)
VWAP_SCAN_CANDLE_END_TIME = time(11, 30)

BREAKOUT_CANDLE_IDX = -1
ACCEPTANCE_CANDLE_IDX = -1

MIN_LIQUIDITY_RATIO = int(os.getenv('MIN_LIQUIDITY_RATIO', "3"))
MAX_WORKERS = int(os.getenv('MAX_WORKERS', "2"))
KITE_API_REQUEST_RATE_PER_SECOND = int(os.getenv('KITE_API_REQUEST_RATE_PER_SECOND', "3"))
BUFFER_SIZE = int(os.getenv('BUFFER_SIZE', "750"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
API_KEY = os.getenv('API_KEY')
API_SECRET = os.getenv('API_SECRET')
USER_ID = os.getenv('USER_ID')
PASSWORD = os.getenv('PASSWORD')
TOTP_SECRET = os.getenv('TOTP_SECRET')  # This is your 2FA secret key
INTRADAY_IS_AUTOMATIC_ENTRY_ENABLED = str_to_bool(os.getenv('INTRADAY_IS_AUTOMATIC_ENTRY_ENABLED', "False"))
SWING_IS_AUTOMATIC_ENTRY_ENABLED = str_to_bool(os.getenv('SWING_IS_AUTOMATIC_ENTRY_ENABLED', "False"))
