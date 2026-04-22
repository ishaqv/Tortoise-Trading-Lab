# 🧠 Algo Trading Lab – GCP Deployment Guide

This guide walks you through setting up a secure Ubuntu-based VPS on Google Cloud/any cloud to run Python-based trading
bot using MySQL and scheduled cron jobs.

---

## 🚀 1. Create Your GCP VM Instance

Go to [Google Cloud Console](https://console.cloud.google.com) and click “Create Instance”. Use the following
configuration:

- **Name**: `trading-vps`
- **Region**: `asia-south1` (Mumbai)
- **Zone**: `asia-south1-a`
- **Machine Type**: `e2-medium` (2 vCPU, 4 GB RAM)
- **Boot Disk**: Ubuntu 22.04 Jammy (x86_64), 10 GB SSD
- **Firewall**: ✅ Allow HTTP, ✅ Allow HTTPS (optional)

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

---

## 🛡️ 5. Secure MySQL

```bash
sudo mysql_secure_installation
```

**Recommended Choices:**

- Set root password → Yes
- Remove anonymous users → Yes
- Disallow root remote login → Yes
- Remove test DB → Yes
- Reload privilege tables → Yes

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

## 🌐 8. (Optional) Enable Remote MySQL Access

```bash
sudo nano /etc/mysql/mysql.conf.d/mysqld.cnf
```

Change:

```ini
bind-address = 127.0.0.1
```

To:

```ini
bind-address = 0.0.0.0
```

Then:

```bash
sudo systemctl restart mysql
sudo ufw allow 3306
```

---

## 🌎 9. Install Google Chrome (Required for selenium automated login)

```bash
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install ./google-chrome-stable_current_amd64.deb
```

---

## 🐍 10. Upload Your App (via SSH or Git)

Using Git:

```bash
git clone git@github.com:your_username/Algo-Trading-Lab.git
cd Algo-Trading-Lab
git pull origin master
```

use SSH and follow step 12
---

## 📦 11. Set Up Python Virtual Environment

```bash
sudo apt install python3-venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## 🔑 12. Generate SSH Key for GitHub

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

## Set the VPS Timezone to IST (Recommended for trading in NSE)

`sudo timedatectl set-timezone Asia/Kolkata`

## ⏰ 13. Automate Script with Cron

🔁 Cron uses system time. Setting system time to IST makes all jobs run in IST.

```bash
crontab -e
```

Add these lines (adjust path as needed):

```cron
*/5 9-15 * * 1-5 bash -c 'source /home/youruser/Algo-Trading-Lab/venv/bin/activate && python3 /home/youruser/Algo-Trading-Lab/intraday_m5_main_app.py'
30 9 * * 1-5 bash -c 'source /home/youruser/Algo-Trading-Lab/venv/bin/activate && python3 /home/youruser/Algo-Trading-Lab/intraday_m15_main_app.py'
35 15 * * 1-5 bash -c 'source /home/youruser/Algo-Trading-Lab/venv/bin/activate && python3 /home/youruser/Algo-Trading-Lab/intraday_m15_main_app.py'

35 15 * * 1-5 bash -c 'source /home/youruser/Algo-Trading-Lab/venv/bin/activate && python3 /home/youruser/Algo-Trading-Lab/swing_main_app.py'
```

```
# 📖 Breakdown of */15 9-15 * * 1-5
# Field             Value       Meaning
# Minutes           */15        Every 15 minutes
# Hours	            9-15        From 9 AM to 4 PM exclusive (9 to 15 in 24-hour format)
# Day of Month	    *	        Every day of the month
# Month	            *	        Every month
# Day of Week	    1-5	        Only on weekdays: Monday (1) to Friday (5)

# ⏰ What this schedule does:
# Runs every 15 minutes between 9:00 AM and 3:59 PM, Monday through Friday
```

Verify:

```bash
crontab -l
```

---

## ▶️ 14. Run App Manually

```bash
cd Algo-Trading-Lab
git pull origin master
source venv/bin/activate
python3 main_app.py
```

---

### Accessing log file

Download log file using the absolute path **/home/user/Algo-Trading-Lab/logs/trading_scanner_{yyyy-mm-dd}.log**

### Access MySQL(GCP VM) from Your Local Machine

#### Prerequisites

- macOS with Homebrew installed.
- Google Cloud SDK (gcloud CLI).
- Access to a GCP VM running MySQL.

---

#### Step 1: Install Google Cloud SDK via Homebrew

```bash
brew update
brew install --cask google-cloud-sdk
gcloud init
```

- This will open a browser window to authenticate with your Google Cloud account.
- Select your project.
- Configure default zone/region if prompted.

---

#### Step 2: Create an SSH Tunnel to MySQL

```bash
gcloud compute ssh INSTANCE_NAME --zone=ZONE_NAME -- -L 3307:localhost:3306
```

Replace:

- `INSTANCE_NAME` → Your VM instance name.
- `ZONE_NAME` → The zone where your VM is deployed.

This command forwards your **local port 3307** to the VM’s **MySQL port 3306**.

---

#### Step 3: Connect to MySQL Locally

Once the SSH tunnel is active, connect using any MySQL client (e.g., MySQL Workbench, DBeaver, or Python scripts):

- **Host:** `127.0.0.1`
- **Port:** `3307`
- **Username:** (Your MySQL username)
- **Password:** (Your MySQL password)

---

#### Pros and Cons

| Pros                                                              | Cons                                                 |
|-------------------------------------------------------------------|------------------------------------------------------|
| Secure connection (no need to expose MySQL port to the internet). | SSH session must stay active for the tunnel to work. |

---

#### Notes

- Keep the SSH tunnel terminal window open while you're connected.
- To automate reconnections or background the tunnel, consider using `autossh`.

### Update GCP Ubuntu VM

Here’s the one-liner that will fully update your GCP Ubuntu VM and reboot only if a reboot is required:

```sudo apt update && sudo apt full-upgrade -y && sudo apt autoremove -y && sudo apt clean && [ -f /var/run/reboot-required ] && sudo reboot```

## ✅ You're Ready!

Your trading bot is now set up to run securely, automatically, and reliably on a Google Cloud VM with MySQL and cron
scheduling.

ssh -L 3307:localhost:3306 ishaqvattaparambil@34.44.242.21

gcloud compute ssh trading-vps-vm --zone=us-central1-c -- -L 3307:localhost:3306

