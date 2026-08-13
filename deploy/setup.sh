#!/bin/bash
set -euo pipefail

APP_DIR="${LOSTGIFTS_DIR:-/opt/alex_gift}"
VENV="$APP_DIR/.venv"
PORT=8877
ADMIN_PORT=8878
REDIS_MEM="128m"

cd "$APP_DIR"

if [ ! -f .env ]; then
  cp .env.example .env
fi

grep -q '^BOT_TOKEN=.' .env || {
  echo "Set BOT_TOKEN in ${APP_DIR}/.env before deploy"
  exit 1
}

set_env_default() {
  local key="$1"
  local val="$2"
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${val}|" .env
  else
    echo "${key}=${val}" >> .env
  fi
}

set_env_default WEB_HOST 127.0.0.1
set_env_default WEB_PORT "${PORT}"
set_env_default WEB_BASE_URL https://lostgifts.ru
set_env_default CERTBOT_EMAIL ssl@lostgifts.ru
set_env_default POLL_INTERVAL 60
set_env_default LOGGER_BATCH_SIZE 5
set_env_default LOGGER_CONCURRENCY 2
set_env_default LOGGER_REQUEST_DELAY 1.5
set_env_default FETCH_CACHE_TTL 90
set_env_default UPDATE_LOCK_TTL 30
set_env_default RATE_LIMIT_REQUESTS 30
set_env_default RATE_LIMIT_WINDOW 60
set_env_default BOT_RATE_LIMIT_REQUESTS 10
set_env_default BOT_RATE_LIMIT_WINDOW 60
set_env_default API_ENABLED false

if grep -q '^API_ENABLED=true' .env && ! grep -q '^API_TOKEN=.' .env; then
  echo "WARNING: API_ENABLED=true but API_TOKEN is empty — disabling API"
  sed -i 's|^API_ENABLED=.*|API_ENABLED=false|' .env
fi

set_env_default ADMIN_HOST 127.0.0.1
set_env_default ADMIN_PORT "${ADMIN_PORT}"
set_env_default ADMIN_BASE_URL https://admin.lostgifts.ru

if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r requirements.txt

if ! grep -q '^ADMIN_PASSWORD_HASH=.\+' .env; then
  ADMIN_PW=$(openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c 32)
  ADMIN_GATE=$(openssl rand -hex 12)
  ADMIN_SECRET=$(openssl rand -hex 32)
  ADMIN_HASH=$(ADMIN_PW="${ADMIN_PW}" "$VENV/bin/python" -c "import os; from src.admin.auth import hash_password; print(hash_password(os.environ['ADMIN_PW']))")
  grep -q '^ADMIN_PASSWORD_HASH=' .env && sed -i "s|^ADMIN_PASSWORD_HASH=.*|ADMIN_PASSWORD_HASH=${ADMIN_HASH}|" .env || echo "ADMIN_PASSWORD_HASH=${ADMIN_HASH}" >> .env
  grep -q '^ADMIN_GATE_PATH=' .env && sed -i "s|^ADMIN_GATE_PATH=.*|ADMIN_GATE_PATH=${ADMIN_GATE}|" .env || echo "ADMIN_GATE_PATH=${ADMIN_GATE}" >> .env
  grep -q '^ADMIN_SESSION_SECRET=' .env && sed -i "s|^ADMIN_SESSION_SECRET=.*|ADMIN_SESSION_SECRET=${ADMIN_SECRET}|" .env || echo "ADMIN_SESSION_SECRET=${ADMIN_SECRET}" >> .env
  echo "=== ADMIN ACCESS (save now, shown once) ==="
  echo "Gate URL: https://admin.lostgifts.ru/${ADMIN_GATE}"
  echo "Password: ${ADMIN_PW}"
fi

if docker ps -a --format '{{.Names}}' | grep -qx alex-gift-redis; then
  if ! docker ps -a --format '{{.Names}}' | grep -qx lostgifts-redis; then
    docker rename alex-gift-redis lostgifts-redis
  fi
fi

if ! docker ps --format '{{.Names}}' | grep -qx lostgifts-redis; then
  docker rm -f lostgifts-redis 2>/dev/null || true
  docker run -d --name lostgifts-redis --restart unless-stopped \
    --memory="${REDIS_MEM}" --memory-swap="${REDIS_MEM}" \
    -p 127.0.0.1:6379:6379 redis:7-alpine \
    redis-server --maxmemory 96mb --maxmemory-policy allkeys-lru
fi

docker update --restart unless-stopped --memory="${REDIS_MEM}" --memory-swap="${REDIS_MEM}" lostgifts-redis 2>/dev/null || true

if [ ! -f /swapfile_lostgifts ] && [ "$(swapon --show | wc -l)" -eq 0 ]; then
  fallocate -l 2G /swapfile_lostgifts 2>/dev/null || dd if=/dev/zero of=/swapfile_lostgifts bs=1M count=2048 status=none
  chmod 600 /swapfile_lostgifts
  mkswap /swapfile_lostgifts
  swapon /swapfile_lostgifts
  grep -q swapfile_lostgifts /etc/fstab || echo '/swapfile_lostgifts none swap sw 0 0' >> /etc/fstab
fi

cat > /etc/systemd/system/lostgifts-redis.service <<UNIT
[Unit]
Description=Lost Gifts Redis
After=docker.service network-online.target
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/docker start lostgifts-redis
ExecStop=/usr/bin/docker stop lostgifts-redis
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/lostgifts-web.service <<UNIT
[Unit]
Description=Lost Gifts Web
After=network-online.target lostgifts-redis.service
Wants=network-online.target lostgifts-redis.service

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${VENV}/bin/uvicorn src.web.server:app --host 127.0.0.1 --port ${PORT} --workers 1 --timeout-keep-alive 30
Restart=always
RestartSec=5
StartLimitIntervalSec=300
StartLimitBurst=10
MemoryHigh=300M
MemoryMax=384M
CPUQuota=60%
OOMScoreAdjust=300
KillSignal=SIGINT
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/lostgifts-logger.service <<UNIT
[Unit]
Description=Lost Gifts Logger
After=network-online.target lostgifts-redis.service
Wants=network-online.target lostgifts-redis.service

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${VENV}/bin/python -m src.logger.worker
Restart=always
RestartSec=15
StartLimitIntervalSec=300
StartLimitBurst=10
MemoryHigh=180M
MemoryMax=256M
CPUQuota=35%
OOMScoreAdjust=500
TimeoutStopSec=45

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/lostgifts-bot.service <<UNIT
[Unit]
Description=Lost Gifts Bot
After=network-online.target lostgifts-redis.service lostgifts-web.service
Wants=network-online.target lostgifts-redis.service

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${VENV}/bin/python -m src.bot.main
Restart=always
RestartSec=10
StartLimitIntervalSec=300
StartLimitBurst=10
MemoryHigh=180M
MemoryMax=256M
CPUQuota=25%
OOMScoreAdjust=400
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/lostgifts-admin.service <<UNIT
[Unit]
Description=Lost Gifts Admin
After=network-online.target lostgifts-redis.service
Wants=network-online.target lostgifts-redis.service

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${VENV}/bin/uvicorn src.admin.server:app --host 127.0.0.1 --port ${ADMIN_PORT} --workers 1 --timeout-keep-alive 15
Restart=always
RestartSec=10
StartLimitIntervalSec=300
StartLimitBurst=5
MemoryHigh=120M
MemoryMax=180M
CPUQuota=20%
OOMScoreAdjust=600
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
UNIT

systemctl stop alex-gift-web alex-gift-bot alex-gift-logger 2>/dev/null || true
systemctl disable alex-gift-redis alex-gift-web alex-gift-logger alex-gift-bot 2>/dev/null || true

systemctl daemon-reload
systemctl enable lostgifts-redis lostgifts-web lostgifts-logger lostgifts-bot lostgifts-admin
systemctl restart lostgifts-redis lostgifts-web lostgifts-logger lostgifts-bot lostgifts-admin

ufw delete allow 8877/tcp 2>/dev/null || true
ufw delete allow 8878/tcp 2>/dev/null || true

if [ -f "${APP_DIR}/deploy/nginx/setup-admin.sh" ]; then
  bash "${APP_DIR}/deploy/nginx/setup-admin.sh" || true
fi

sleep 2
echo "=== RESOURCES ==="
free -h
swapon --show || true
echo "=== STATUS ==="
systemctl is-active lostgifts-redis lostgifts-web lostgifts-logger lostgifts-bot lostgifts-admin
systemctl show lostgifts-logger -p MemoryMax -p CPUQuota -p Restart
echo "=== LOSTGIFTS PORTS (must be 127.0.0.1 only) ==="
ss -tlnp | grep -E ':8877|:8878|:6379' || true
if ss -tlnp | grep -E '0\.0\.0\.0:8877|\[::\]:8877|0\.0\.0\.0:8878|\[::\]:8878|0\.0\.0\.0:6379|\[::\]:6379'; then
  echo "ERROR: lostgifts port exposed publicly!"
  exit 1
fi
