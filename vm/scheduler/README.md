# GCP VM Auto Scheduler for NSE Trading Hours

This project automatically **starts and stops a GCP VM** during **NSE trading hours** using **Cloud Functions** and *
*Cloud Scheduler**.

GCP does not support timer-triggered functions directly, so we use an HTTP-triggered Cloud Function scheduled with Cloud
Scheduler.

## Project Structure

```
.
├── main.py              # Contains the Cloud Function code
├── requirements.txt     # Dependencies for the Cloud Function
```

## Deploying the Functions

**Run the following commands inside the local terminal**
Got to project directory and open terminal 
cd vm/scheduler


### 1. Deploy the function to **start** the VM

```bash
gcloud functions deploy start_vm \
  --runtime python312 \
  --region=asia-south1 \
  --trigger-http \
  --allow-unauthenticated \
  --entry-point manage_vm \
  --set-env-vars GCP_PROJECT=project_id,ZONE=zone_name,INSTANCE=vm_instance_name,ACTION=start
```

### 2. Deploy the function to **stop** the VM

```bash
gcloud functions deploy stop_vm \
  --runtime python311 \
  --region=asia-south1 \
  --trigger-http \
  --allow-unauthenticated \
  --entry-point manage_vm \
  --set-env-vars GCP_PROJECT=project_id,ZONE=zone_name,INSTANCE=vm_instance_name,ACTION=stop
```

> `manage_vm` is the function defined inside `main.py`.

## Scheduling the Functions

### 🟢 Start VM at **9:13 AM IST** (03:43 UTC)

```bash
gcloud scheduler jobs create http start-vm-job \
  --schedule="43 3 * * 1-5" \
  --time-zone="Asia/Kolkata" \
  --uri="<function_uri>" \
  --http-method=GET \
  --location=asia-south1
```

### 🔴 Stop VM at **3:32 PM IST** (10:02 UTC)

```bash
gcloud scheduler jobs create http stop-vm-job \
  --schedule="2 10 * * 1-5" \
  --time-zone="Asia/Kolkata" \
  --uri="<function_uri>" \
  --http-method=GET \
  --location=asia-south1
```

> ⚠️ **Note**: The Scheduler cron uses **UTC timezone**, not the server timezone.

---

## ✅ Summary

- Automatically manage your VM lifecycle only during NSE trading hours.
- Avoid unnecessary billing outside trading hours.
- Uses GCP Cloud Functions + Cloud Scheduler combo.
