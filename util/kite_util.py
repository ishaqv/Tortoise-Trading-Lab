import time
from typing import Optional

from kiteconnect import KiteConnect
from kiteconnect.exceptions import NetworkException, DataException

from util.global_variables import KITE_API_REQUEST_RATE_PER_SECOND
from util.secret_manager_util import get_kite_access_token, get_kite_api_key
from util.telegram_bot import send_telegram_alert
from util.trade_logger import log

kite: Optional[KiteConnect] = None
_last_request_time: float = 0


def get_kite() -> KiteConnect:
    global kite
    if kite is None:
        raise RuntimeError("Kite not initialized")
    return kite


def init_kite_session(max_wait=600, retry_interval=30):
    """
    Initialize a valid Kite session.

    Attempts to establish a KiteConnect session using the cached access token.
    If the token is expired or invalid, sends a Telegram alert with a login URL
    and waits 120 seconds for the trader to manually re-authenticate via Zerodha.
    After that, retries every `retry_interval` seconds until the session is
    established or `max_wait` is exceeded.

    Args:
        max_wait (int): Maximum time in seconds to wait for a valid session. Default is 600.
        retry_interval (int): Seconds between retry attempts after the initial 120s wait. Default is 30.

    Raises:
        RuntimeError: If a valid session cannot be established within `max_wait` seconds.

    Note:
        Assumes the trader is present at the desk when this is called — the Telegram
        alert is expected to be acted on promptly.
    """

    global kite

    alert_sent = False
    start_time = time.time()

    api_key = get_kite_api_key()
    login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"

    while time.time() - start_time < max_wait:

        access_token = get_kite_access_token()
        kite_obj = KiteConnect(api_key=api_key)
        kite_obj.set_access_token(access_token)

        try:
            kite_obj.profile()
            kite = kite_obj
            log("info", "✅ Kite session established successfully.")
            return

        except Exception as e:
            log("warning", f"Token invalid/expired: {e}")

            # ✅ Send alert only once
            if not alert_sent:
                message = (
                    "🚨 <b>Kite Token Expired</b>\n"
                    "\n"
                    "Your trading session has ended and requires manual re-authentication.\n"
                    "\n"
                    f"🔗 <a href='{login_url}'>Login to Zerodha KiteConnect API</a>\n"
                )

                send_telegram_alert(message)
                alert_sent = True
                time.sleep(120)  # 2 min waiting time for manual login
                continue

            time.sleep(retry_interval)

    # Hard fail
    raise RuntimeError("Unable to establish Kite session within time limit")


def kite_throttle():
    global _last_request_time

    now = time.time()
    elapsed = now - _last_request_time
    min_interval = 1 / KITE_API_REQUEST_RATE_PER_SECOND  # e.g., 3 req/s → 0.333s

    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)

    _last_request_time = time.time()


def get_nse_instruments():
    return get_kite().instruments("NSE")


def fetch_historical_data_from_kite(symbol, instrument_token, from_date, to_date, interval, retries=3):
    for attempt in range(1, retries + 1):
        try:
            kite_throttle()
            historical_data = get_kite().historical_data(
                instrument_token,
                from_date,
                to_date,
                interval
            )
            return historical_data

        except NetworkException as e:
            wait = 2 ** attempt  # 2s, 4s, 8s
            log("warning", f"   Type: {type(e)}")
            log("warning", f"   Args: {e.args}")
            log("warning", f"   Dict: {e.__dict__}")  # ← often has the real details
            log("warning", f"⚠️ Network error for {symbol} (attempt {attempt}/{retries}): {e}. Retrying in {wait}s...")
            if attempt == retries:
                log("error", f"❌ All retries exhausted for {symbol}: {e}")
                return None
            time.sleep(wait)

        except DataException as e:
            log("error", f"❌ Invalid data/token for {symbol}: {e}", exc_info=True)
            return None  # Don't retry — bad instrument token

        except Exception as e:
            log("error", f"❌ Unexpected error for {symbol}: {e}", exc_info=True)
            return None
    return None
