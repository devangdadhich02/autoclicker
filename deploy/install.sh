#!/usr/bin/env bash
# Velora Auto Clicker — Bare-Metal VPS Installation Script
# Tested on Ubuntu 22.04 LTS
# Usage: sudo bash install.sh
set -euo pipefail

VELORA_USER="velora"
VELORA_DIR="/opt/velora"
PYTHON_VERSION="3.13"
NODE_VERSION="20"

echo "============================================"
echo " Velora Auto Clicker — VPS Installer"
echo "============================================"

# --- System packages ---
echo "[1/8] Installing system packages..."
apt-get update -qq
apt-get install -y --no-install-recommends \
    curl wget git build-essential \
    libpq-dev libssl-dev libffi-dev \
    postgresql postgresql-contrib \
    nginx certbot python3-certbot-nginx \
    supervisor

# --- Python 3.13 ---
echo "[2/8] Installing Python ${PYTHON_VERSION}..."
add-apt-repository -y ppa:deadsnakes/ppa
apt-get install -y python${PYTHON_VERSION} python${PYTHON_VERSION}-venv python${PYTHON_VERSION}-dev

# --- Node.js ---
echo "[3/8] Installing Node.js ${NODE_VERSION}..."
curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash -
apt-get install -y nodejs

# --- Create velora user ---
echo "[4/8] Creating system user..."
id -u ${VELORA_USER} &>/dev/null || useradd --system --create-home --home-dir ${VELORA_DIR} ${VELORA_USER}

# --- Clone / copy code ---
echo "[5/8] Setting up application directory..."
mkdir -p ${VELORA_DIR}
chown ${VELORA_USER}:${VELORA_USER} ${VELORA_DIR}
mkdir -p /data/browser_profiles /data/screenshots /data/logs
chown -R ${VELORA_USER}:${VELORA_USER} /data

# --- Python venv + deps ---
echo "[6/8] Installing Python dependencies..."
python${PYTHON_VERSION} -m venv ${VELORA_DIR}/.venv
${VELORA_DIR}/.venv/bin/pip install --upgrade pip
${VELORA_DIR}/.venv/bin/pip install -e "${VELORA_DIR}/backend[dev]"
sudo -u ${VELORA_USER} ${VELORA_DIR}/.venv/bin/playwright install chromium --with-deps

# --- Frontend build ---
echo "[7/8] Building frontend..."
cd ${VELORA_DIR}/frontend
npm ci
npm run build

# --- Services ---
echo "[8/8] Configuring services..."
cp ${VELORA_DIR}/deploy/velora.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable velora
systemctl start velora

echo ""
echo "============================================"
echo " Installation complete!"
echo " Configure Nginx: ${VELORA_DIR}/deploy/nginx-vps.conf"
echo " Backend logs:    journalctl -u velora -f"
echo " .env location:   ${VELORA_DIR}/backend/.env"
echo "============================================"
