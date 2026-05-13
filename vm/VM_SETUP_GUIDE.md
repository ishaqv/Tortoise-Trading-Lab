# 🧠 Algo Trading Lab – GCP Deployment Guide

---

## 🚀 1. Create Your GCP VM Instance

Go to Google Cloud Console and click “Create Instance”. Use the following configuration:

* **Name**: `trading-vm`
* **Region**: `asia-south1` (Mumbai)
* **Zone**: `asia-south1-a`
* **Machine Type**: `e2-medium` (2 vCPU, 4 GB RAM)
* **Boot Disk**: debian-12-bookworm-v20260417, 10 GB SSD (Default)
* **Firewall**: ✅ Allow HTTP, ✅ Allow HTTPS (optional)

---

## 🔐 2. SSH Into Your VPS

From the VM page, click the **SSH** button to open a terminal in your browser.

---

## 🔄 3. Update Your Server

```bash
sudo apt update && sudo apt upgrade -y
```

---

## 📦 4. Install Required Packages

```bash
sudo apt install -y mysql-server python3-pip build-essential ufw unzip
```

OR

```bash
sudo apt install -y mariadb-server python3-pip build-essential ufw unzip
```

---

## 🛡️ 5. Secure MySQL

```bash
sudo mysql_secure_installation
```

**Recommended Choices:**

* Set root password → Yes
* Remove anonymous users → Yes
* Disallow root remote login → Yes
* Remove test DB → Yes
* Reload privilege tables → Yes

---

## 🗃️ 6. Create a MySQL Database

```bash
sudo mysql -u root -p
```

Inside the MySQL shell:

```sql
CREATE DATABASE db_name;
CREATE USER 'username'@'localhost' IDENTIFIED BY 'password';
GRANT ALL PRIVILEGES ON db_name.* TO 'username'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

---

## 🔥 7. Secure VPS with UFW

```bash
sudo ufw allow OpenSSH
sudo ufw enable
```

---

## 🔑 8. Generate SSH Key for GitHub

From the SSH terminal execute the following commands

```bash
ssh-keygen -t ed25519 -C "your_email@example.com"
```

Just press **Enter** for default location, optionally set a passphrase.

Add your key to ssh-agent:

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
```

Copy public key:

```bash
cat ~/.ssh/id_ed25519.pub
```

🔗 Add to GitHub → **Settings → SSH and GPG Keys → New SSH Key**

---

## 🐍 9. Upload Your App (via SSH or Git)

Using Git:

```bash
git clone git@github.com:your_username/Tortoise-Trading-Lab.git
cd Tortoise-Trading-Lab
git pull origin master
```

---

## 📦 10. Set Up Python Virtual Environment

```bash
sudo apt install python3-venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## ▶️ 11. Run startup file to initialize backend storage

```bash
cd Tortoise
git pull origin master
source venv/bin/activate
python3 startup.py
```

---

## ⏰ 12. Set the VPS Timezone to IST (Recommended for trading in NSE)

`sudo timedatectl set-timezone Asia/Kolkata`

---

## ⏰ 13. Automate Script with Cron

🔁 Cron uses system time. Setting system time to IST makes all jobs run in IST.

From the SSH terminal run the following command

```bash
crontab -e
```

Add those lines from [crontab](../crontab)

Verify:

```bash
crontab -l
```

---

## 🔐 14. Accessing GCP Secret Manager from a VM

To successfully access secrets from **Google Cloud Secret Manager** on a Compute Engine VM, **two configurations must be
correct**. Missing either one will result in a `403 PERMISSION_DENIED` error.

---

### ✅ 1. IAM Role (Authorization)

The VM’s service account must have the following role:

* `roles/secretmanager.secretAccessor`

This allows the service account to **read secrets**.

You can assign it by the following command / using GCP console:

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:<PROJECT_NUMBER>-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

---

### ⚠️ 2. OAuth Scopes (Access Token Permissions)

Even with correct IAM roles, access will fail if the VM does not have proper OAuth scopes.

The VM **must include**:

```
https://www.googleapis.com/auth/cloud-platform
```

This scope allows the VM to request access tokens that can call GCP APIs, including Secret Manager.

---

### 🔍 How to Verify Scopes

Run this inside your VM:

```bash
curl "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/scopes" \
  -H "Metadata-Flavor: Google"
```

If you don’t see `cloud-platform`, Secret Manager access will fail.

---

### 🛠️ How to Fix Missing Scopes

#### Option A — Using gcloud

```bash
gcloud compute instances stop YOUR_VM_NAME

gcloud compute instances set-service-account YOUR_VM_NAME \
  --scopes=https://www.googleapis.com/auth/cloud-platform \
  --zone=YOUR_ZONE

gcloud compute instances start YOUR_VM_NAME
```

---

#### Option B — Using GCP Console

1. Go to Compute Engine → VM Instances
2. Click your VM → **Edit**
3. Under **Access scopes**, select:
   **“Allow full access to all Cloud APIs”**
4. Save and restart the VM

---

### 🚨 Common Pitfall

> Assigning IAM roles alone is **not enough**.

Both must be configured:

| Requirement | Purpose                           |
|-------------|-----------------------------------|
| IAM Role    | What the service account *can do* |
| OAuth Scope | What the VM *is allowed to call*  |

---

## 🔐 Using Google Cloud Secret Manager Locally

If you’re running the application locally and need access to Google Cloud Secret Manager, you must configure local
authentication.

Run:

```
gcloud auth application-default login
```

---

## 📄 Accessing log file

Download log file using the absolute path
`/home/user/Tortoise-Trading-Lab/*.log`

---

## 🧵 Access MySQL (GCP VM) from Your Local Machine

### Prerequisites

* macOS with Homebrew installed
* Google Cloud SDK (gcloud CLI)
* Access to a GCP VM running MySQL

---

### Step 1: Install Google Cloud SDK via Homebrew

```bash
brew update
brew install --cask google-cloud-sdk
gcloud init
```

---

### Step 2: Create a Persistent SSH Tunnel to MySQL

```
gcloud compute ssh INSTANCE_NAME --zone=ZONE_NAME -- -N -L 3306:localhost:3306 -o ServerAliveInterval=30 -o ServerAliveCountMax=3
```

---

### Step 3: Connect to MySQL Locally

* Host: `127.0.0.1`
* Port: `3306`

---

## 🔄 Update GCP VM

```bash
sudo apt update && sudo apt full-upgrade -y && sudo apt autoremove -y && sudo apt clean && [ -f /var/run/reboot-required ] && sudo reboot
```

---

## 📊 VM Resource Check

### Disk usage

```bash
df -h /
```

### RAM usage

```bash
free -h
```

---

## ✅ You're Ready!

Your trading bot is now set up to run securely, automatically, and reliably on a Google Cloud VM with MySQL and cron
scheduling.

---
