#!/usr/bin/env bash
# ==============================================================================
# 🚀 Oracle Cloud Infrastructure (OCI) Free Tier 1-Click Deployment Script
# Automatically deploys the Cryptocurrency Cointegration Statistical Arbitrage Bot
# Compatible with: Ubuntu 22.04/24.04 LTS & Oracle Linux 8/9 (x86_64 and ARM64 Ampere)
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}"
echo "=============================================================================="
echo "    ORACLE CLOUD FREE TIER - CRYPTO STATISTICAL ARBITRAGE DEPLOYMENT"
echo "=============================================================================="
echo -e "${NC}"

# 1. Root check & privilege verification
if [ "$EUID" -ne 0 ]; then
    SUDO="sudo"
else
    SUDO=""
fi

# 2. Detect Operating System
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS_NAME=$ID
else
    OS_NAME="unknown"
fi

echo -e "${BLUE}[1/6] Detected Operating System: ${OS_NAME} (${VERSION_ID:-unknown})${NC}"

# 3. CRITICAL: Configure Oracle Cloud Firewall (iptables / UFW)
# Oracle Cloud Ubuntu/Oracle Linux VM images block all non-SSH incoming traffic by default
echo -e "${YELLOW}[2/6] Configuring Oracle Cloud Linux Firewall for Ports 80, 443, 8000...${NC}"

if command -v iptables &> /dev/null; then
    # Open TCP ports 80, 443, and 8000 in iptables before any DROP/REJECT rule
    $SUDO iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT 2>/dev/null || $SUDO iptables -I INPUT 1 -p tcp --dport 80 -j ACCEPT
    $SUDO iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT 2>/dev/null || $SUDO iptables -I INPUT 1 -p tcp --dport 443 -j ACCEPT
    $SUDO iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT 2>/dev/null || $SUDO iptables -I INPUT 1 -p tcp --dport 8000 -j ACCEPT

    # Persist iptables across VM reboots
    if [ "$OS_NAME" = "ubuntu" ] || [ "$OS_NAME" = "debian" ]; then
        $SUDO apt-get update -y > /dev/null 2>&1
        $SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent > /dev/null 2>&1 || true
        $SUDO netfilter-persistent save > /dev/null 2>&1 || true
    elif [ "$OS_NAME" = "ol" ] || [ "$OS_NAME" = "rhel" ] || [ "$OS_NAME" = "centos" ]; then
        if command -v firewall-cmd &> /dev/null; then
            $SUDO firewall-cmd --zone=public --permanent --add-port=80/tcp || true
            $SUDO firewall-cmd --zone=public --permanent --add-port=443/tcp || true
            $SUDO firewall-cmd --zone=public --permanent --add-port=8000/tcp || true
            $SUDO firewall-cmd --reload || true
        fi
    fi
    echo -e "${GREEN}✓ OS Firewall rules applied (Ports 80, 443, 8000 allowed).${NC}"
fi

# 4. Install Docker & Docker Compose if not present
echo -e "${BLUE}[3/6] Verifying Docker and Container Runtime...${NC}"
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}Installing Docker Engine...${NC}"
    if [ "$OS_NAME" = "ubuntu" ] || [ "$OS_NAME" = "debian" ]; then
        $SUDO apt-get update -y
        $SUDO apt-get install -y ca-certificates curl gnupg lsb-release
        $SUDO install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/$OS_NAME/gpg | $SUDO gpg --dearmor -o /etc/apt/keyrings/docker.gpg --yes
        $SUDO chmod a+r /etc/apt/keyrings/docker.gpg
        echo \
          "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/$OS_NAME \
          $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
          $SUDO tee /etc/apt/sources.list.d/docker.list > /dev/null
        $SUDO apt-get update -y
        $SUDO apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    else
        curl -fsSL https://get.docker.com | $SUDO sh
    fi
    $SUDO systemctl enable --now docker
    # Add non-root user to docker group if applicable
    if [ -n "${SUDO_USER:-}" ]; then
        $SUDO usermod -aG docker "$SUDO_USER" || true
    fi
    echo -e "${GREEN}✓ Docker installed successfully.${NC}"
else
    echo -e "${GREEN}✓ Docker is already installed: $(docker --version)${NC}"
fi

# 5. Environment configuration setup
echo -e "${BLUE}[4/6] Setting up environment configuration...${NC}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo -e "${YELLOW}Created .env from .env.example with Delta Exchange credentials.${NC}"
    else
        cat << 'EOF' > .env
ACTIVE_EXCHANGE=delta
DELTA_API_KEY=5QtWt22iUBsBawMj8uIrtJezs8YUjT
DELTA_API_SECRET=NTjv3v9Z0xWPQ8PGBUParbEaYc3pHPrmvzc9ogqjt6Z6nwARfqqVNPLQCCce
DELTA_ENVIRONMENT=india
DEFAULT_PAIR=BTCUSD/ETHUSD
TICK_INTERVAL_SECONDS=3.0
WORKER_DEFAULT_MODE=LIVE
INITIAL_CAPITAL=10000.0
LEVERAGE=1.0
MAX_ACTIVE_PAIRS=2
EOF
        echo -e "${YELLOW}Generated baseline .env configuration.${NC}"
    fi
fi

# 6. Ensure persistent state directories exist
mkdir -p results data/processed data/raw

# 7. Build and run via Docker Compose
echo -e "${BLUE}[5/6] Building & Launching Trading Engine Container...${NC}"
if docker compose version &> /dev/null; then
    COMPOSE_CMD="$SUDO docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="$SUDO docker-compose"
else
    echo -e "${RED}Error: Neither 'docker compose' nor 'docker-compose' found.${NC}"
    exit 1
fi

$COMPOSE_CMD down || true
$COMPOSE_CMD build
$COMPOSE_CMD up -d

# 8. Healthcheck verification
echo -e "${BLUE}[6/6] Verifying engine startup and healthcheck...${NC}"
sleep 5

HEALTH_STATUS="failing"
for i in {1..10}; do
    if curl -s http://127.0.0.1:8000/health | grep -q '"status":"ok"'; then
        HEALTH_STATUS="ok"
        break
    fi
    echo -e "Waiting for engine initialization... (${i}/10)"
    sleep 3
done

# 9. Get Public IP
PUBLIC_IP=$(curl -s https://ifconfig.me || curl -s https://api.ipify.org || echo "<YOUR_ORACLE_PUBLIC_IP>")

echo ""
echo -e "${GREEN}==============================================================================${NC}"
if [ "$HEALTH_STATUS" = "ok" ]; then
    echo -e "${GREEN}  🎉 DEPLOYMENT SUCCESSFUL! STATISTICAL ARBITRAGE ENGINE IS RUNNING 24/7${NC}"
else
    echo -e "${YELLOW}  ⚠️ Container started. Verifying background worker initialization...${NC}"
fi
echo -e "${GREEN}==============================================================================${NC}"
echo ""
echo -e "  🌐 Web Terminal Dashboard : ${CYAN}http://${PUBLIC_IP}:8000${NC} (or http://${PUBLIC_IP})"
echo -e "  🩺 Healthcheck API        : ${CYAN}http://${PUBLIC_IP}:8000/health${NC}"
echo -e "  📊 Active Status API      : ${CYAN}http://${PUBLIC_IP}:8000/api/status${NC}"
echo ""
echo -e "  Useful Management Commands:"
echo -e "    - View live logs        : ${YELLOW}$COMPOSE_CMD logs -f --tail=50${NC}"
echo -e "    - Restart engine        : ${YELLOW}$COMPOSE_CMD restart${NC}"
echo -e "    - Stop engine           : ${YELLOW}$COMPOSE_CMD down${NC}"
echo -e "    - Update & redeploy     : ${YELLOW}git pull && $COMPOSE_CMD up -d --build${NC}"
echo ""
echo -e "${YELLOW}  NOTE: Make sure Port 8000 (and 80) is allowed in your Oracle Cloud VCN${NC}"
echo -e "${YELLOW}  Security List (Ingress Rules: Source 0.0.0.0/0, Destination Port 8000, 80).${NC}"
echo -e "${GREEN}==============================================================================${NC}"

