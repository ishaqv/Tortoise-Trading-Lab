import os

import functions_framework
from flask import Request, Response
from google.cloud import secretmanager
from kiteconnect import KiteConnect

# --- Config ---
KITE_API_KEY = os.environ["KITE_API_KEY"]
KITE_API_SECRET = os.environ["KITE_API_SECRET"]
PROJECT_ID = "trading-vps-463502"


def store_token(token):
    client = secretmanager.SecretManagerServiceClient()

    client.add_secret_version(
        request={
            "parent": f"projects/{PROJECT_ID}/secrets/KITE_ACCESS_TOKEN",
            "payload": {"data": token.encode()}
        }
    )


def send_response(message, status):
    if status == 200:
        color = "green"
    else:
        color = "red"

    return Response(
        f"<h3 style='color:{color};'>{message}</h3>",
        status=status,
        mimetype='text/html'
    )


@functions_framework.http
def kite_login_callback(request: Request):
    # Only allow GET
    if request.method != "GET":
        return send_response("Method Not Allowed", 405)

    status = request.args.get("status")
    if status != "success":
        return send_response("Kite Login Failed", 400)

    # 1. Extract request token
    request_token = request.args.get("request_token")
    if not request_token:
        return send_response("Missing Request Token", 400)

    # 2. Generate access token
    kite = KiteConnect(api_key=KITE_API_KEY)
    try:
        session_data = kite.generate_session(request_token, api_secret=KITE_API_SECRET)
        access_token = session_data["access_token"]
    except Exception as e:
        return send_response("Kite Session Error", 500)

    # 3. Store token in GCP SecretManager
    try:
        store_token(access_token)
    except Exception as e:
        return send_response("Token Save Error", 500)

    return send_response("Token Saved Successfully!", 200)
