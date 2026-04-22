import requests

from util.global_variables import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from util.trade_logger import log


def send_telegram_alert(message):
    """
        Sends a message to a Telegram chat using the Telegram Bot API.
    """
    formatted_message = f"-------------------------------------\n{message}"
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": formatted_message,
            "parse_mode": "HTML"
        }

        response = requests.post(url, data=payload)
        if response.status_code != 200:
            log("error", f"Received invalid telegram response:{response.status_code}")
    except Exception as e:
        log("error", f"⚠️ Error sending telegram message: {e}")
