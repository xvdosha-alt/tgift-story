#!/bin/bash
set -euo pipefail

ADMIN_DOMAIN="admin.lostgifts.ru"
MAIN_DOMAIN="lostgifts.ru"
APP_DIR="${LOSTGIFTS_DIR:-/opt/alex_gift}"
ADMIN_PORT=8878
SSL_DIR="/etc/ssl/${MAIN_DOMAIN}"
NGINX_SITE="/etc/nginx/sites-available/admin.lostgifts.ru.conf"

if [ -f "/etc/letsencrypt/live/${MAIN_DOMAIN}/fullchain.pem" ]; then
  SSL_CERT="/etc/letsencrypt/live/${MAIN_DOMAIN}/fullchain.pem"
  SSL_KEY="/etc/letsencrypt/live/${MAIN_DOMAIN}/privkey.pem"
elif [ -f "${SSL_DIR}/fullchain.pem" ]; then
  SSL_CERT="${SSL_DIR}/fullchain.pem"
  SSL_KEY="/etc/ssl/private/${MAIN_DOMAIN}.key"
else
  echo "Run setup-lostgifts.sh first (SSL cert missing)"
  exit 1
fi

cat > /etc/nginx/conf.d/lostgifts-admin-rate-limit.conf <<'RATE'
limit_req_zone $binary_remote_addr zone=lostgifts_admin:10m rate=1r/s;
RATE

cat > "${NGINX_SITE}" <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name ${ADMIN_DOMAIN};

    include /etc/nginx/snippets/cloudflare-allow.conf;

    location /.well-known/acme-challenge/ {
        allow all;
        root /var/www/certbot;
    }

    location / {
        return 301 https://${ADMIN_DOMAIN}\$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${ADMIN_DOMAIN};

    include /etc/nginx/snippets/cloudflare-allow.conf;
    ssl_certificate     ${SSL_CERT};
    ssl_certificate_key ${SSL_KEY};
    include /etc/nginx/snippets/ssl-params.conf;

    client_max_body_size 64k;
    limit_req zone=lostgifts_admin burst=5 nodelay;

    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy no-referrer always;
    add_header Content-Security-Policy "default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'" always;

    location / {
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header CF-Connecting-IP \$http_cf_connecting_ip;
        proxy_connect_timeout 15s;
        proxy_send_timeout 15s;
        proxy_read_timeout 15s;
        proxy_pass http://127.0.0.1:${ADMIN_PORT};
    }
}
NGINX

ln -sf "${NGINX_SITE}" /etc/nginx/sites-enabled/admin.lostgifts.ru.conf
nginx -t
systemctl reload nginx

ufw delete allow ${ADMIN_PORT}/tcp 2>/dev/null || true

echo "Admin nginx: https://${ADMIN_DOMAIN}"
