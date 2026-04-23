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

### 🛠️ Setup & Run Instructions

1. Install the **Google Cloud SDK (`gcloud`)** if it’s not already installed.

2. Open your terminal and navigate to the project directory:

   ```bash
   cd vm/scheduler
   ```

3. Run the required commands from the following.

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

### 🟢 Start VM at **9:00 AM IST**

```bash
gcloud scheduler jobs create http start-vm-job \
  --schedule="0 9 * * 1-5" \
  --time-zone="Asia/Kolkata" \
  --uri="<function_uri>" \
  --http-method=GET \
  --location=asia-south1
```

### 🔴 Stop VM at **4:00PM IST**

```bash
gcloud scheduler jobs create http stop-vm-job \
  --schedule="0 16 * * 1-5" \
  --time-zone="Asia/Kolkata" \
  --uri="<function_uri>" \
  --http-method=GET \
  --location=asia-south1
```

---

## ✅ Summary

- Automatically manage your VM lifecycle only during NSE trading hours.
- Avoid unnecessary billing outside trading hours.
- Uses GCP Cloud Functions + Cloud Scheduler combo.
