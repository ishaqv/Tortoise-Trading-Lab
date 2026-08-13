# Deploying the Telegram-Driven Gainers Scanner

This project consists of:

* **2 Google Cloud Functions**, deployed from the same `main.py`

    * `scan_upload` — handles CSV uploads and generates the trading watchlist
    * `notify_gainers` — sends the daily Telegram notification with the upload link
* **1 Cloud Scheduler job** — triggers `notify_gainers` every weekday at 9:20 AM IST

---

## Architecture

```text
Cloud Scheduler
      │
      │ 9:20 AM IST, Mon–Fri
      ▼
notify_gainers
      │
      │ Telegram message + upload URL
      ▼
Telegram
      │
      ▼
Upload NSE CSVs
      │
      │ Click "Scan"
      ▼
scan_upload
      │
      ├── Process NIFTY NEXT 50 CSV
      ├── Process All Securities CSV
      ├── Apply scanner logic
      └── Generate watchlist
      │
      ▼
Telegram
      │
      ▼
Select #1 Stock
```

---

# Setup & Deployment

## Prerequisites

Install the **Google Cloud SDK (`gcloud`)** if it is not already installed.

Navigate to the project directory:

```bash
cd intraday/scanner/m5/top_gainers
```

Make sure the required environment variables are available in your terminal:

```bash
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
export TRADING_CAPITAL="..."
export INTRADAY_LEVERAGE_MULTIPLIER="..."
export REGION="asia-south1"
```

---

## 1. Grant Cloud Build Permissions

The default Compute Engine service account needs permission to build the Cloud Function artifacts.

Run:

```bash
gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:<PROJECT_NUMBER>-compute@developer.gserviceaccount.com" \
  --role=roles/cloudbuild.builds.builder
```

Replace:

* `<PROJECT_ID>` with your Google Cloud project ID
* `<PROJECT_NUMBER>` with your Google Cloud project number

---

# 2. Deploy `scan_upload`

Deploy `scan_upload` **first** because its URL is required by `notify_gainers`.

This function must be publicly reachable because the upload page is opened directly from Telegram/browser without GCP
authentication.

> **Security note:** Anyone who has the `scan_upload` URL can access it. There is currently no URL signing or
> authentication on this endpoint.

```bash
gcloud functions deploy scan_upload \
  --gen2 \
  --runtime=python312 \
  --region=asia-south1 \
  --source=. \
  --entry-point=scan_upload \
  --trigger-http \
  --allow-unauthenticated \
  --set-env-vars=TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN,TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID,TRADING_CAPITAL=$TRADING_CAPITAL,INTRADAY_LEVERAGE_MULTIPLIER=$INTRADAY_LEVERAGE_MULTIPLIER
```

After deployment, get the function URL:

```bash
gcloud functions describe scan_upload \
  --gen2 \
  --region=asia-south1 \
  --format="value(serviceConfig.uri)"
```

Set this URL as:

```bash
export UPLOAD_URL="https://..."
```

---

# 3. Deploy `notify_gainers`

`notify_gainers` should **not** be publicly accessible.

Only Cloud Scheduler should be able to invoke it.

Therefore, deploy it with:

```bash
gcloud functions deploy notify_gainers \
  --gen2 \
  --runtime=python312 \
  --region=$REGION \
  --source=. \
  --entry-point=notify_gainers \
  --trigger-http \
  --no-allow-unauthenticated \
  --set-env-vars=TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN,TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID,UPLOAD_FUNCTION_URL=$UPLOAD_URL
```

Get the deployed function URL:

```bash
gcloud functions describe notify_gainers \
  --gen2 \
  --region=$REGION \
  --format="value(serviceConfig.uri)"
```

Set it as:

```bash
export NOTIFY_URL="https://..."
```

---

# 4. Allow Cloud Scheduler to Invoke `notify_gainers`

Grant the default Compute Engine service account permission to invoke the function:

```bash
gcloud functions add-invoker-policy-binding notify_gainers \
  --region=$REGION \
  --member="serviceAccount:<PROJECT_NUMBER>-compute@developer.gserviceaccount.com"
```

Replace `<PROJECT_NUMBER>` with your Google Cloud project number.

---

# 5. Create the Cloud Scheduler Job

The scheduler runs **Monday through Friday at 9:20 AM IST**.

```bash
gcloud scheduler jobs create http notify-top-gainers-job \
  --schedule="20 9 * * 1-5" \
  --time-zone="Asia/Kolkata" \
  --uri="$NOTIFY_URL" \
  --http-method=POST \
  --oidc-service-account-email="<PROJECT_NUMBER>-compute@developer.gserviceaccount.com" \
  --oidc-token-audience="$NOTIFY_URL"
```

The schedule:

```text
20 9 * * 1-5
```

means:

```text
Monday–Friday
09:20 AM
Asia/Kolkata
```

---

# 6. Test the Complete Workflow

You do not need to wait until 9:20 AM to test the scheduler.

Manually trigger the scheduler job:

```bash
gcloud scheduler jobs run notify-top-gainers-job
```

You should receive a Telegram message containing a link to the CSV upload page.

Then:

1. Open the upload link.
2. Download the required NSE CSV files.
3. Upload the files.
4. Click **Scan**.
5. Wait for the watchlist to arrive in Telegram.

---

# Daily NSE Top Gainers → Trading Watchlist

Once deployment is complete, the daily process is simple.

## 1. 9:20 AM — Receive Telegram Alert

At **9:20 AM IST**, Cloud Scheduler invokes:

```text
notify-top-gainers-job
        ↓
notify_gainers
```

`notify_gainers` sends a Telegram message containing the upload-page link.

---

## 2. Download NSE Top Gainers CSVs

Open the NSE Top Gainers / Losers page:

[NSE — Top Gainers / Losers](https://www.nseindia.com/market-data/top-gainers-losers?utm_source=chatgpt.com)

Download the latest CSV data for:

1. **NIFTY NEXT 50**
2. **All Securities**

Use the current trading session's data.

---

## 3. Upload the CSV Files

Open the upload page using the link received through Telegram.

Upload both files:

```text
NIFTY NEXT 50
All Securities
```

After both files are uploaded, click:

**Scan**

---

## 4. Scan the Uploaded Data

Clicking **Scan** invokes:

```text
scan_upload
```

The function:

1. Receives the uploaded CSV files.
2. Reads and processes the NSE data.
3. Applies the configured scanner/filtering logic.
4. Generates the trading watchlist.
5. Sends the resulting watchlist to Telegram.

---

## 5. Select the #1 Stock

Review the watchlist received in Telegram.

Select the:

> **#1-ranked stock**

This becomes the primary trading candidate for the day.

---

# Complete A–Z Workflow

```text
┌─────────────────────────────┐
│  9:20 AM IST                │
│  Cloud Scheduler            │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  notify_gainers             │
│  Sends Telegram alert       │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  Telegram                   │
│  Upload-page link           │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  NSE Top Gainers / Losers   │
│                             │
│  Download:                  │
│  • NIFTY NEXT 50            │
│  • All Securities           │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  Upload both CSV files      │
│  Click "Scan"               │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  scan_upload                │
│                             │
│  • Process CSVs             │
│  • Apply scanner logic      │
│  • Generate watchlist       │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  Telegram Watchlist         │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  Select #1 Stock            │
│  ↓                          │
│  Trade                      │
└─────────────────────────────┘
```
