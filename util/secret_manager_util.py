import json

from google.cloud import secretmanager

from util.global_variables import GCP_PROJECT_ID
from util.trade_logger import log

kite_access_token = None
db_config = None
telegram_config = None
kite_api_key = None


def get_secret(secret_id: str, project_id: str, version: str = "latest") -> str:
    """
    Fetch a secret value from GCP Secret Manager.

    Args:
        secret_id: Name of the secret (e.g. 'KITE_ACCESS_TOKEN')
        project_id: GCP project ID (or number)
        version: Secret version (default: 'latest')

    Returns:
        Secret value as string
    """

    try:
        client = secretmanager.SecretManagerServiceClient()

        name = f"projects/{project_id}/secrets/{secret_id}/versions/{version}"

        response = client.access_secret_version(name=name)

        secret_value = response.payload.data.decode("UTF-8")

        if not secret_value:
            raise ValueError("Secret is empty")

        return secret_value

    except Exception:
        log("error", "Failed to fetch secret from Secret Manager")
        raise


def get_kite_access_token():
    global kite_access_token

    if not kite_access_token:
        kite_access_token = get_secret("KITE_ACCESS_TOKEN", GCP_PROJECT_ID)

    return kite_access_token


def get_kite_api_key():
    global kite_api_key

    if not kite_api_key:
        kite_api_key = get_secret("KITE_API_KEY", GCP_PROJECT_ID)

    return kite_api_key


def get_db_config():
    global db_config

    if not db_config:
        db_config = json.loads(get_secret("DB_CONFIG", GCP_PROJECT_ID))

    return db_config


def get_telegram_config():
    global telegram_config

    if not telegram_config:
        telegram_config = json.loads(get_secret("TELEGRAM_CONFIG", GCP_PROJECT_ID))

    return telegram_config
