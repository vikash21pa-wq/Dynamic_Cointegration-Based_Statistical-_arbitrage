# ☁️ Deploying to Oracle Cloud Infrastructure (OCI) Always-Free Tier

This comprehensive guide walks you through deploying the **Cryptocurrency Cointegration Statistical Arbitrage Bot & Dashboard** to run 24/7 permanently on **Oracle Cloud Infrastructure (OCI) Always-Free Tier** at zero cost.

---

## 📋 Overview of Always-Free Resources

Oracle Cloud offers the most generous free cloud tier in the industry:
- **Compute (Recommended)**: **Ampere A1 ARM** Compute instance with up to **4 OCPUs and 24 GB RAM** (or 2 OCPUs / 12 GB RAM for this bot), **100% Free Forever**.
- **Alternative Compute**: `VM.Standard.E2.1.Micro` (AMD, 1/8 OCPU, 1 GB RAM).
- **Storage**: Up to 200 GB Block Storage free.
- **Networking**: 1 Reserved Static Public IPv4 Address, 10 TB/month outbound bandwidth free.

---

## 🚀 Step 1: Create Your Always-Free OCI Compute Instance

1. Log into your **[Oracle Cloud Console](https://cloud.oracle.com)**.
2. In the search bar or hamburger menu, navigate to **Compute > Instances**.
3. Click **Create Instance**.
4. Configure the instance settings:
   - **Name**: `crypto-stat-arb-vm`
   - **Placement**: Keep default Availability Domain.
   - **Image and Shape**:
     - Click **Change Image**: Select **Ubuntu 22.04 LTS** (or **Ubuntu 24.04 LTS**).
     - Click **Change Shape**:
       - Choose **Ampere (ARM)** > `VM.Standard.A1.Flex` (Always Free Eligible).
       - Allocate **2 OCPUs** and **12 GB RAM** (plenty for high-frequency tick processing and statistical modeling).
       - *(Alternatively, choose Specialty and Legacy > AMD `VM.Standard.E2.1.Micro`)*.
   - **Networking**:
     - Choose **Create new virtual cloud network (VCN)**.
     - Choose **Assign a public IPv4 address**: Select **Yes**.
   - **Add SSH Keys**:
     - Select **Generate a key pair for me** and click **Save private key** (`.key` file saved to your computer).
     - *(Or select **Paste public keys** if you already have an `id_rsa.pub`)*.
   - **Boot Volume**: Default (50 GB is free).
5. Click **Create**. Within 1–2 minutes, your instance state will turn **RUNNING** (Green), and an **Engine Public IP** will be displayed.

---

## 🛡️ Step 2: Open Ingress Ports in Oracle Cloud VCN (Crucial)

By default, Oracle Cloud VCN blocks all incoming ports except Port 22 (SSH). You must add ingress rules for ports **8000** (Terminal Dashboard API) and **80** (HTTP):

1. On your Instance Details page, click your **Virtual Cloud Network** link (under *Primary VNIC*).
2. Click **Security Lists** in the left sidebar, then click **Default Security List for...**.
3. Under **Ingress Rules**, click **Add Ingress Rules**.
4. Add the following rule for Dashboard Port `8000`:
   - **Source CIDR**: `0.0.0.0/0`
   - **IP Protocol**: `TCP`
   - **Source Port Range**: `All`
   - **Destination Port Range**: `8000`
   - **Description**: `Statistical Arbitrage Web Dashboard & API`
5. *(Optional for HTTP/HTTPS)* Add another rule:
   - **Source CIDR**: `0.0.0.0/0`
   - **IP Protocol**: `TCP`
   - **Destination Port Range**: `80,443`
   - **Description**: `HTTP and HTTPS web traffic`
6. Click **Add Ingress Rules**.

---

## 🔑 Step 3: Connect to Your VM via SSH

Open your local terminal (PowerShell, Command Prompt, macOS/Linux terminal) and connect:

```bash
# Set secure file permissions on your saved private key (Windows PowerShell / Git Bash / Linux / Mac)
chmod 400 <path_to_your_key_file>.key

# SSH into the Oracle Cloud Ubuntu VM (replace with your Public IP)
ssh -i <path_to_your_key_file>.key ubuntu@<YOUR_ORACLE_PUBLIC_IP>
```

---

## ⚡ Step 4: Clone & Run 1-Click Turnkey Deployment

Once connected to your Oracle Cloud VM, execute the following commands:

```bash
# 1. Clone the repository
git clone https://github.com/vikash21pa-wq/Dynamic_Cointegration-Based_Statistical-_arbitrage.git

# 2. Enter repository directory
cd Dynamic_Cointegration-Based_Statistical-_arbitrage

# 3. Make deployment script executable and run it
chmod +x deploy_oci.sh
./deploy_oci.sh
```

### What `deploy_oci.sh` automatically does:
- Opens ports `80`, `443`, and `8000` inside the Oracle Cloud Linux OS firewall (`iptables`/`ufw`).
- Installs Docker Engine & Docker Compose with multi-arch ARM/AMD buildx support.
- Configures `.env` with pre-configured Delta Exchange integration.
- Launches the autonomous background trading engine in a restart-resilient container (`restart: unless-stopped`).
- Tests container health via `/health` probe and outputs your live terminal URL.

---

## 🌐 Step 5: Access Your Live Dashboard Terminal

Open your browser and navigate to:

```text
http://<YOUR_ORACLE_PUBLIC_IP>:8000
```

You will see:
- Real-time live prices streaming from Delta Exchange WebSocket.
- Active pair telemetry (`BTCUSD/ETHUSD` with correlation 0.89–0.97 and verified spread volatility).
- Live Z-score mean-reversion tracker and virtual order execution.
- Real-time PnL, margin utilization, and risk indicators.

---

## 🛠️ Step 6: Managing Your Trading Bot on Oracle Cloud

Once deployed, the bot runs automatically in the background 24/7 even after you disconnect your SSH session or reboot the VM.

### View Live Logs in Real Time:
```bash
docker compose logs -f --tail=100
```

### Check Container Status:
```bash
docker compose ps
```

### Restart Engine:
```bash
docker compose restart
```

### Stop Engine:
```bash
docker compose down
```

### Update Code to Latest Commit:
```bash
git pull
docker compose up -d --build
```

---

## 🔒 Step 7: (Optional) Free SSL / HTTPS with Let's Encrypt

If you have a domain pointing to your Oracle Cloud Public IP (e.g., `algo.yourdomain.com`), you can set up free automatic SSL in 2 minutes:

```bash
sudo apt-get install -y certbot python3-certbot-nginx nginx

# Stop temporary container port 80 mapping
docker compose down

# Obtain SSL Certificate
sudo certbot --nginx -d algo.yourdomain.com

# Create Nginx proxy configuration
sudo tee /etc/nginx/sites-available/stat-arb << 'EOF'
server {
    server_name algo.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 86400;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/stat-arb /etc/nginx/sites-enabled/
sudo systemctl restart nginx
```
Now access securely via `https://algo.yourdomain.com` with full WebSocket multiplex support!

