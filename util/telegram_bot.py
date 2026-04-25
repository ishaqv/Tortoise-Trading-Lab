import requests

from util.secret_manager_util import get_telegram_config
from util.trade_logger import log


def send_telegram_alert(message):
    """
        Sends a message to a Telegram chat using the Telegram Bot API.
    """
    formatted_message = f"-------------------------------------\n{message}"
    try:
        url = f"https://api.telegram.org/bot{get_telegram_config()['token']}/sendMessage"
        payload = {
            "chat_id": get_telegram_config()['chat_id'],
            "text": formatted_message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }

        response = requests.post(url, data=payload)
        if response.status_code != 200:
            log("error", f"Received invalid telegram response:{response.status_code}")
    except Exception as e:
        log("error", f"⚠️ Error sending telegram message: {e}")
