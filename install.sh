#!/usr/bin/env bash
###############################################################################
# MailPulse — one-file installer for Ubuntu/Debian VPS
#
#   sudo bash install.sh
#
# Installs & configures everything: Python, Node, Yarn, MongoDB, Nginx,
# the FastAPI backend (systemd, single worker) and the built React frontend,
# served same-origin through Nginx with /api proxied to the backend.
#
# Re-runnable (idempotent-ish). Run from the project root (the folder that
# contains  backend/  and  frontend/ ).
###############################################################################
set -euo pipefail

# ---- config (override via env before running) -------------------------------
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_NAME="${DB_NAME:-mailpulse}"
SERVER_NAME="${SERVER_NAME:-_}"          # your domain or "_" for any/IP
BACKEND_PORT=8001
NODE_MAJOR=20
SMTP_HELO_NAME="${SMTP_HELO_NAME:-mailpulse.local}"
SMTP_MAIL_FROM="${SMTP_MAIL_FROM:-verify@mailpulse.local}"

log()  { echo -e "\n\033[1;32m==>\033[0m \033[1m$*\033[0m"; }
warn() { echo -e "\033[1;33m[warn]\033[0m $*"; }
die()  { echo -e "\033[1;31m[error]\033[0m $*"; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Please run as root:  sudo bash install.sh"
[ -d "$APP_DIR/backend" ] && [ -d "$APP_DIR/frontend" ] || die "Run this from the project root (needs backend/ and frontend/)."

export DEBIAN_FRONTEND=noninteractive

# ---- 1. base packages -------------------------------------------------------
log "Installing base packages"
apt-get update -y
apt-get install -y curl wget gnupg ca-certificates lsb-release apt-transport-https \
                   build-essential python3 python3-venv python3-dev nginx ufw

. /etc/os-release
CODENAME="${VERSION_CODENAME:-$(lsb_release -sc)}"

# ---- 2. Node.js + Yarn ------------------------------------------------------
if ! command -v node >/dev/null 2>&1 || [ "$(node -v | cut -d. -f1 | tr -d v)" -lt "$NODE_MAJOR" ]; then
  log "Installing Node.js ${NODE_MAJOR}.x"
  curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
  apt-get install -y nodejs
fi
if ! command -v yarn >/dev/null 2>&1; then
  log "Installing Yarn"
  npm install -g yarn
fi

# ---- 3. MongoDB 7.0 ---------------------------------------------------------
if ! command -v mongod >/dev/null 2>&1; then
  log "Installing MongoDB 7.0"
  MONGO_LIST="/etc/apt/sources.list.d/mongodb-org-7.0.list"
  curl -fsSL https://pgp.mongodb.com/server-7.0.asc | gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor --yes
  if [ "${ID:-}" = "debian" ]; then
    echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] http://repo.mongodb.org/apt/debian ${CODENAME}/mongodb-org/7.0 main" > "$MONGO_LIST"
  else
    echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu ${CODENAME}/mongodb-org/7.0 multiverse" > "$MONGO_LIST"
  fi
  apt-get update -y
  apt-get install -y mongodb-org || warn "MongoDB repo may not have '${CODENAME}'. Install MongoDB manually if this failed."
fi
log "Starting MongoDB"
systemctl enable mongod >/dev/null 2>&1 || true
systemctl restart mongod || die "MongoDB failed to start. Check: journalctl -u mongod"

# ---- 4. Backend (venv + deps + .env) ---------------------------------------
log "Setting up backend"
cd "$APP_DIR/backend"
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip wheel
./.venv/bin/pip install -r requirements.txt

if [ ! -f "$APP_DIR/backend/.env" ]; then
  cat > "$APP_DIR/backend/.env" <<EOF
MONGO_URL="mongodb://localhost:27017"
DB_NAME="${DB_NAME}"
CORS_ORIGINS="*"
SMTP_HELO_NAME="${SMTP_HELO_NAME}"
SMTP_MAIL_FROM="${SMTP_MAIL_FROM}"
EOF
  log "Wrote backend/.env"
else
  warn "backend/.env already exists — leaving it untouched"
fi
mkdir -p "$APP_DIR/backend/data"

# ---- 5. Frontend (build static) --------------------------------------------
log "Building frontend (this can take a few minutes)"
cd "$APP_DIR/frontend"
# Same-origin: empty backend URL => calls go to /api on the same host via Nginx
cat > "$APP_DIR/frontend/.env" <<EOF
REACT_APP_BACKEND_URL=
WDS_SOCKET_PORT=443
ENABLE_HEALTH_CHECK=false
EOF
yarn install --frozen-lockfile || yarn install
yarn build

# ---- 6. systemd service for backend (single worker!) ------------------------
log "Creating systemd service: mailpulse"
cat > /etc/systemd/system/mailpulse.service <<EOF
[Unit]
Description=MailPulse FastAPI backend
After=network.target mongod.service
Wants=mongod.service

[Service]
Type=simple
WorkingDirectory=${APP_DIR}/backend
ExecStart=${APP_DIR}/backend/.venv/bin/uvicorn server:app --host 127.0.0.1 --port ${BACKEND_PORT} --workers 1
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable mailpulse >/dev/null 2>&1 || true
systemctl restart mailpulse

# ---- 7. Nginx (serve build + proxy /api) ------------------------------------
log "Configuring Nginx"
cat > /etc/nginx/sites-available/mailpulse <<EOF
server {
    listen 80;
    server_name ${SERVER_NAME};

    client_max_body_size 2048M;        # large bulk uploads

    root ${APP_DIR}/frontend/build;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:${BACKEND_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;           # stream CSV downloads
    }

    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
EOF
ln -sf /etc/nginx/sites-available/mailpulse /etc/nginx/sites-enabled/mailpulse
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx

# ---- 8. Firewall ------------------------------------------------------------
if command -v ufw >/dev/null 2>&1; then
  log "Opening firewall (22, 80, 443)"
  ufw allow 22/tcp  >/dev/null 2>&1 || true
  ufw allow 80/tcp  >/dev/null 2>&1 || true
  ufw allow 443/tcp >/dev/null 2>&1 || true
fi

# ---- 9. port-25 check -------------------------------------------------------
log "Checking outbound port 25 (needed for SMTP mailbox verification)"
if timeout 8 bash -c 'cat < /dev/null > /dev/tcp/alt1.gmail-smtp-in.l.google.com/25' 2>/dev/null; then
  echo "   ✓ Outbound port 25 is OPEN — SMTP verification will work."
else
  warn "Outbound port 25 appears BLOCKED. Ask your VPS provider to unblock it,"
  warn "or add SOCKS5 proxies (port-25 capable) in the app's Proxies panel."
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
cat <<EOF

===============================================================================
 ✅ MailPulse installed.

   Frontend + API :  http://${IP:-your-server-ip}/     (or your domain)
   Backend service:  systemctl status mailpulse
   Backend logs   :  journalctl -u mailpulse -f
   MongoDB        :  systemctl status mongod

 Next (optional):
   • Point a domain at this server, set SERVER_NAME and re-run, then add HTTPS:
       apt-get install -y certbot python3-certbot-nginx && certbot --nginx
   • For accurate Yahoo/iCloud checks, set FCrDNS + SMTP_HELO_NAME / SMTP_MAIL_FROM
     in backend/.env to your own domain, then: systemctl restart mailpulse
===============================================================================
EOF
