# 🧠 Algo Trading Lab – GCP Deployment Guide

This guide walks you through setting up a secure Debian-based VPS on Google Cloud/any cloud to run Python-based trading
bot using MySQL and scheduled cron jobs.

---

## 🚀 1. Create Your GCP VM Instance

Go to [Google Cloud Console](https://console.cloud.google.com) and click “Create Instance”. Use the following
configuration:

- **Name**: `trading-vm`
- **Region**: `asia-south1` (Mumbai)
- **Zone**: `asia-south1-a`
- **Machine Type**: `e2-medium` (2 vCPU, 4 GB RAM)
- **Boot Disk**: debian-12-bookworm-v20260417, 10 GB SSD (Default)
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

## 🔑 9. Generate SSH Key for GitHub

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

## 🐍 10. Upload Your App (via SSH or Git)

Using Git:

```bash
git clone git@github.com:your_username/Tortoise-Trading-Lab.git
cd Tortoise-Trading-Lab
git pull origin master
```

---

## 📦 11. Set Up Python Virtual Environment

```bash
sudo apt install python3-venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Set the VPS Timezone to IST (Recommended for trading in NSE)

`sudo timedatectl set-timezone Asia/Kolkata`

## ⏰ 12. Automate Script with Cron

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

## ▶️ 13. Run App Manually

```sudo nano .env```
Then add your environment variables
Save(Ctrl+O)
Exit(Ctrl+X)

```bash
cd Algo-Trading-Lab
git pull origin master
source venv/bin/activate
python3 main_app.py
```

---

### Accessing log file

Download log file using the absolute path **/home/user/Tortoise-Trading-Lab/**/**.log(replace with actual path)**

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

✅ Step 2: Create a Persistent SSH Tunnel to MySQL

Instead of a basic tunnel, use a keepalive-enabled tunnel:

```
gcloud compute ssh INSTANCE_NAME --zone=ZONE_NAME -- -N -L 3306:localhost:3306 -o ServerAliveInterval=30 -o ServerAliveCountMax=3
```
Replace:

- `INSTANCE_NAME` → Your VM instance name
- `ZONE_NAME` → The zone where your VM is deployed

---

- `-N` → Runs tunnel without opening a shell (clean + stable)
- `ServerAliveInterval=30` → Sends keepalive ping every 30s
- `ServerAliveCountMax=3` → Retries before dropping

This command forwards your **local port 3306** to the VM’s **MySQL port 3306**.

---

#### Step 3: Connect to MySQL Locally

Once the SSH tunnel is active, connect using any MySQL client (e.g., MySQL Workbench, DBeaver, or Python scripts):

- **Host:** `127.0.0.1`
- **Port:** `3306`
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

### VM Resource Check

From the SSH terminal

### Disk usage

``` 
df -h / 
```

sample output

```
Filesystem      Size  Used Avail Use% Mounted on
/dev/sda1       9.7G  5.2G  4.0G  57% /

```

### RAM usage

```free -h```

sample output

```
               total        used        free      shared  buff/cache   available
Mem:           3.8Gi       593Mi       2.9Gi       544Ki       531Mi       3.3Gi
Swap:             0B          0B          0B
```

## ✅ You're Ready!

Your trading bot is now set up to run securely, automatically, and reliably on a Google Cloud VM with MySQL and cron
scheduling.

