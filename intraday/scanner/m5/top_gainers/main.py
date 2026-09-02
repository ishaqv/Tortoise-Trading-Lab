"""
GCP Cloud Functions: NSE Top Gainers Scanner - Telegram-driven upload workflow.

Two HTTP-triggered functions, deployed separately from this same file:

1. notify_gainers  -> triggered daily by Cloud Scheduler.
   Sends a Telegram message with the upload link (same link every day).

2. scan_upload     -> the link's target.
   GET  -> serves a small HTML page with a multi-file upload form.
   POST -> receives the uploaded CSVs, runs the scan logic and alert the resulting watchlist via Telegram.



Environment variables required (set at deploy time):

  TELEGRAM_BOT_TOKEN            - Telegram bot token from @BotFather
  TELEGRAM_CHAT_ID              - chat/user id to message
  UPLOAD_FUNCTION_URL           - public HTTPS URL of the deployed scan_upload function
  TRADING_CAPITAL               - e.g. "100000"
  INTRADAY_LEVERAGE_MULTIPLIER  - e.g. "4.75"
"""
import functools
import logging
import os
import re
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import functions_framework
import numpy as np
import pandas as pd
import requests
from flask import Request, Response

# ── CONFIG ──────────────
MIN_PCT_CHANGE = 2.5
MIN_PCT_CHANGE_LOW_PARTICIPATION = 1.5
MAX_PCT_CHANGE = 8.0
MAX_OPENING_GAP_PCT = 3.0
MAX_PARTICIPATION_RATE = 0.75
PARTICIPATION_THRESHOLD = 0.35
TRADING_CAPITAL = int(os.environ.get("TRADING_CAPITAL", "500000"))
INTRADAY_LEVERAGE_MULTIPLIER = float(os.environ.get("INTRADAY_LEVERAGE_MULTIPLIER", "4.75"))
UPLOAD_FUNCTION_URL = os.environ.get("UPLOAD_FUNCTION_URL", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
BUYING_POWER = TRADING_CAPITAL * INTRADAY_LEVERAGE_MULTIPLIER


def _send_telegram_message(message):
    """Low-level Telegram sender. Raises if Telegram/network fails."""
    formatted_message = (
        "-------------------------------------\n"
        f"{message}"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": formatted_message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "protect_content": True,
    }

    response = requests.post(url, data=payload, timeout=15)
    response.raise_for_status()

    response_data = response.json()
    if not response_data.get("ok", False):
        raise RuntimeError(
            f"Telegram API returned ok=false: {response.text}"
        )


def send_telegram_alert(message):
    """Send a normal Telegram alert."""
    _send_telegram_message(message)


def _send_error_telegram_alert(function_name, exc):
    """Best-effort minimal error notification."""
    try:
        timestamp = datetime.now(
            ZoneInfo("Asia/Kolkata")
        ).strftime("%d-%b-%Y %H:%M:%S IST")

        message = (
            "🚨 <b>Cloud Function Error</b>\n"
            f"<b>Function:</b> {escape(function_name)}\n"
            f"<b>Error:</b> {escape(type(exc).__name__)}: "
            f"{escape(str(exc))}\n"
            f"<b>Time:</b> {escape(timestamp)}"
        )

        # Never call send_telegram_alert() here. If Telegram itself
        # failed, error reporting must not recursively fail.
        _send_telegram_message(message)

    except Exception:
        # Never hide the original exception because Telegram failed.
        logging.exception("Failed to send error notification to Telegram")


def global_exception_handler(function):
    """Catch unexpected exceptions from a Cloud Function in one place."""

    @functools.wraps(function)
    def wrapper(request: Request):
        try:
            return function(request)

        except Exception as exc:
            # Full traceback is available in Cloud Logging.
            # Telegram gets only a short notification.
            logging.exception(
                "Unhandled exception in Cloud Function '%s'",
                function.__name__,
            )

            _send_error_telegram_alert(function.__name__, exc)

            return Response(
                "❌ Internal server error. The error has been reported.",
                status=500,
                mimetype="text/plain",
            )

    return wrapper


def get_label(filename):
    """Best-effort short label from the uploaded filename, e.g.
    'T20-GL-gainers-NIFTYNEXT50-06-Aug-2026.csv' -> 'NIFTYNEXT50'.
    Falls back to the filename stem if the pattern isn't found."""
    match = re.search(r"gainers-(.+?)-\d{2}-[A-Za-z]{3}-\d{4}", filename)
    if match:
        return match.group(1)
    return os.path.splitext(os.path.basename(filename))[0]


def scan_dataframe(df, label):
    """Same calculations and filter conditions as scan_file() in the
    original script, operating on an in-memory DataFrame."""
    df = df.copy()

    required_columns = ["OPEN", "PREV. CLOSE", "LTP", "VOLUME", "SYMBOL"]
    missing = [c for c in required_columns if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    for col in ["OPEN", "PREV. CLOSE", "LTP", "VOLUME"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    valid = (
            df["OPEN"].gt(0) &
            df["PREV. CLOSE"].gt(0) &
            df["LTP"].gt(0) &
            df["VOLUME"].gt(0)
    )
    df = df.loc[valid].copy()

    df["GAP_PCT"] = (((df["OPEN"] - df["PREV. CLOSE"]) / df["PREV. CLOSE"]) * 100).abs().round(1)
    df["PRICE_CHANGE_PCT"] = (((df["LTP"] - df["OPEN"]) / df["OPEN"]) * 100).round(1)
    denominator = df["LTP"] * df["VOLUME"]
    df["PARTICIPATION_RATE"] = (BUYING_POWER / denominator.where(denominator > 0) * 100).round(2)
    df["INDEX"] = label

    filtered = df[
        (df["PRICE_CHANGE_PCT"] >= np.where(
            df["PARTICIPATION_RATE"] < PARTICIPATION_THRESHOLD,
            MIN_PCT_CHANGE_LOW_PARTICIPATION,
            MIN_PCT_CHANGE
        )) &
        (df["PRICE_CHANGE_PCT"] <= MAX_PCT_CHANGE) &
        (df["GAP_PCT"] <= MAX_OPENING_GAP_PCT) &
        (df["PARTICIPATION_RATE"] < MAX_PARTICIPATION_RATE)
        ]
    return filtered[["INDEX", "SYMBOL", "GAP_PCT", "PRICE_CHANGE_PCT", "PARTICIPATION_RATE"]]


def process_uploaded_files(files):
    """Scan uploaded CSVs and build Telegram-ready HTML sections."""
    sections = []

    for f in files:
        filename = f.filename or "Unnamed file"

        try:
            df = pd.read_csv(f.stream)

            label = get_label(filename)
            result = scan_dataframe(df, label)

        except Exception as exc:
            # Keep processing the remaining files.
            # Full traceback is logged; Telegram is not spammed for
            # individual bad files.
            logging.exception(
                "Failed to process uploaded file '%s'",
                filename,
            )

            sections.append(
                f"❌ <b>{escape(filename)}</b>\n"
                f"Could not process this CSV.\n"
                f"<i>Reason: {escape(str(exc))}</i>"
            )
            continue

        if result.empty:
            continue

        # Pick top 2:
        # 1. Lowest participation rate
        # 2. Highest price change as tie-breaker
        top2 = (
            result
            .sort_values(
                by=["PARTICIPATION_RATE", "PRICE_CHANGE_PCT"],
                ascending=[True, False],
            )
            .head(2)
        )

        rows = []

        for rank, (_, row) in enumerate(top2.iterrows(), start=1):
            symbol = escape(str(row["SYMBOL"]))
            price_change = float(row["PRICE_CHANGE_PCT"])
            gap = float(row["GAP_PCT"])
            participation = float(row["PARTICIPATION_RATE"])

            rows.append(
                f"<b>{rank}. {symbol}</b>\n"
                f"   Price Change: {price_change:+.1f}%\n"
                f"   Opening Gap: {gap:.1f}%\n"
                f"   Participation Rate: {participation:.2f}%"
            )

        sections.append(
            f"📊 <b>INDEX - {escape(label)}</b>\n\n"
            + "\n\n".join(rows)
        )

    return sections


# ── HTML for the upload page ────────────────────────────────────────────

UPLOAD_PAGE_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#0f172a">
  <title>NSE Top Gainers</title>
  <style>
    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f1f5f9;
      color: #0f172a;
    }

    .card {
      width: min(420px, 100%);
      background: #ffffff;
      border-radius: 20px;
      padding: 32px 24px;
      text-align: center;
      box-shadow: 0 12px 40px rgba(15, 23, 42, 0.10);
    }

    .icon {
      width: 64px;
      height: 64px;
      margin: 0 auto 18px;
      display: grid;
      place-items: center;
      border-radius: 18px;
      background: #0f172a;
      color: #ffffff;
      font-size: 30px;
    }

    h1 {
      margin: 0 0 24px;
      font-size: 21px;
      font-weight: 650;
    }

    .file-input {
      display: none;
    }

    .upload-btn {
      display: block;
      width: 100%;
      padding: 15px 20px;
      border: 0;
      border-radius: 12px;
      background: #0f172a;
      color: #ffffff;
      font-size: 16px;
      font-weight: 600;
      cursor: pointer;
      transition: transform .15s, background .15s;
    }

    .upload-btn:hover {
      background: #1e293b;
      transform: translateY(-1px);
    }

    .upload-btn:active {
      transform: translateY(0);
    }

    .file-name {
      margin-top: 12px;
      color: #64748b;
      font-size: 13px;
      min-height: 18px;
      word-break: break-word;
    }

    .scan-btn {
      display: none;
      width: 100%;
      margin-top: 14px;
      padding: 14px 20px;
      border: 0;
      border-radius: 12px;
      background: #16a34a;
      color: #ffffff;
      font-size: 16px;
      font-weight: 600;
      cursor: pointer;
    }

    .scan-btn:hover {
      background: #15803d;
    }

    .scan-btn:disabled {
      opacity: .65;
      cursor: wait;
    }

    #status {
      display: none;
      margin-top: 16px;
      padding: 12px 14px;
      border-radius: 10px;
      font-size: 14px;
      line-height: 1.45;
      white-space: pre-wrap;
    }

    #status.loading {
      display: block;
      background: #eff6ff;
      color: #1d4ed8;
    }

    #status.success {
      display: block;
      background: #f0fdf4;
      color: #166534;
    }

    #status.error {
      display: block;
      background: #fef2f2;
      color: #991b1b;
    }
  </style>
</head>
<body>
  <main class="card">
    <div class="icon">📈</div>

    <h1>Upload Top Gainers CSV Files</h1>

    <form id="f">
      <input
        id="files"
        class="file-input"
        type="file"
        name="files"
        multiple
        accept=".csv,text/csv"
      >

      <label class="upload-btn" for="files">
        📤 Upload
      </label>

      <div id="fileName" class="file-name"></div>

      <button id="scanBtn" class="scan-btn" type="submit">
        🔍 Scan 
      </button>
    </form>

    <div id="status" role="status" aria-live="polite"></div>
  </main>

  <script>
    const form = document.getElementById('f');
    const filesInput = document.getElementById('files');
    const fileName = document.getElementById('fileName');
    const scanBtn = document.getElementById('scanBtn');
    const status = document.getElementById('status');

    filesInput.addEventListener('change', () => {
      const count = filesInput.files.length;

      if (!count) {
        fileName.textContent = '';
        scanBtn.style.display = 'none';
        return;
      }

      fileName.textContent =
        count === 1
          ? filesInput.files[0].name
          : `${count} CSV files selected`;

      scanBtn.style.display = 'block';
      status.style.display = 'none';
    });

    form.addEventListener('submit', async (e) => {
      e.preventDefault();

      // Show the status area immediately.
      status.style.display = 'block';

      if (!filesInput.files.length) {
        status.className = 'error';
        status.textContent = '⚠️ Please select at least one CSV file.';
        return;
      }

      scanBtn.disabled = true;
      scanBtn.textContent = '⏳ Scanning...';

      status.className = 'loading';
      status.style.display = 'block';
      status.textContent = '⏳ Uploading and scanning your files...';

      try {
        const data = new FormData(form);

        const resp = await fetch(window.location.href, {
          method: 'POST',
          body: data
        });

        const text = await resp.text();

        console.log('HTTP status:', resp.status);
        console.log('Server response:', text);

        if (resp.ok) {
    status.className = 'success';
    status.style.display = 'block';
    status.textContent = text;

    form.reset();
    fileName.textContent = '';
    scanBtn.style.display = 'none';

    document.body.innerHTML = `
    <main class="card">
        <div class="icon">✅</div>
        <h1>Scan Complete</h1>
        <p>Watchlist sent via Telegram.</p>
        <p style="color:#64748b;font-size:13px;">
            You can close this page.
        </p>
    </main>
    `;
}
        else {
          status.className = 'error';
          status.style.display = 'block';
          status.textContent = '❌ ' + (text || 'The scan failed.');
        }

      } catch (err) {
        console.error('Fetch error:', err);

        status.className = 'error';
        status.style.display = 'block';
        status.textContent =
          '❌ Unable to connect. Please check your connection and try again.';
      } finally {
        if (scanBtn.style.display !== 'none') {
          scanBtn.disabled = false;
          scanBtn.textContent = '🔍 Scan';
        }
      }
    });
  </script>
</body>
</html>
"""


# ── CLOUD FUNCTION 1: notify_gainers ───────────────────────────────────

@functions_framework.http
@global_exception_handler
def notify_gainers(request: Request):
    """Triggered by Cloud Scheduler each trading day. Sends a Telegram
    message with the  link to the upload top gainers CSVs."""
    date_str = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d-%b-%Y")

    send_telegram_alert(
        f"NSE Top Gainers watchlist scan for {date_str}\n"
        f"🔗 <a href='{UPLOAD_FUNCTION_URL}'>Upload today's CSV file(s) here</a>"
    )
    return Response(status=200)


# ── CLOUD FUNCTION 2: scan_upload ──────────────────────────────────────

@functions_framework.http
@global_exception_handler
def scan_upload(request: Request):
    """GET  -> serves the upload form. Same link works every day.
    POST -> processes uploaded CSVs and sends results to Telegram."""
    if request.method == "GET":
        return Response(UPLOAD_PAGE_HTML, mimetype="text/html")

    if request.method == "POST":
        files = [f for f in request.files.getlist("files") if f and f.filename]
        if not files:
            return Response("⚠️ No files were uploaded. Please choose at least one CSV file and try again.", status=400)

        # Always use IST for the watchlist date.
        date_str = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d-%b-%Y")

        result_sections = process_uploaded_files(files)

        if result_sections:
            result_text = "\n\n".join(result_sections)

            send_telegram_alert(
                f"<b>NSE Top Gainers Watchlist for {escape(date_str)}</b>\n\n"
                f"{result_text}"
            )
        else:
            send_telegram_alert(
                f"<b>NSE Top Gainers Watchlist for {escape(date_str)}</b>\n\n"
                "No qualifying symbols were found."
            )

        return Response("✅Success", status=200)

    return Response("This page supports GET (open the page) and POST (upload CSV files).", status=405)
