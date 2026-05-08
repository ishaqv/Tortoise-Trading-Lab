import threading
import time

from kiteconnect import KiteConnect
from kiteconnect.exceptions import NetworkException, DataException

from util.global_variables import KITE_API_REQUEST_RATE_PER_SECOND
from util.secret_manager_util import get_kite_access_token, get_kite_api_key
from util.telegram_bot import send_telegram_alert
from util.trade_logger import log

kite_lock = threading.Lock()
kite = None
_last_request_time: float = 0


def get_kite() -> KiteConnect:
    global kite
    if kite is None:
        init_kite_session()
    return kite


def init_kite_session(max_wait=600, retry_interval=30):
    global kite

    # 🔒 Ensure only ONE thread can run this at a time
    with kite_lock:

        # ✅ Double-check: maybe another thread already fixed it
        if kite is not None:
            try:
                kite.profile()
                log("info", "✅ Kite session already active. Skipping init.")
                return
            except:
                pass  # token invalid → continue re-init

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

                if not alert_sent:
                    message = (
                        "🚨 <b>Kite Token Expired</b>\n\n"
                        "Manual re-authentication required.\n\n"
                        f"🔗 <a href='{login_url}'>Login to Zerodha KiteConnect API</a>"
                    )

                    send_telegram_alert(message)
                    alert_sent = True
                    time.sleep(120)
                    continue

                time.sleep(retry_interval)

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
            kite_throttle()  # this call is mandatory to avoid 429
            historical_data = get_kite().historical_data(
                instrument_token,
                from_date,
                to_date,
                interval
            )
            log("info", f"Fetched {len(historical_data)} candles data from:{from_date} - to:{to_date} for {symbol}")

            # Silent failure checks
            if not historical_data:
                log("warning", f"EMPTY data returned from kite for : {symbol} | {from_date} to {to_date}")

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
