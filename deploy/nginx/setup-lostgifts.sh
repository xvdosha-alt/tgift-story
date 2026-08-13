#!/bin/bash
set -euo pipefail

DOMAIN="lostgifts.ru"
APP_DIR="${LOSTGIFTS_DIR:-/opt/alex_gift}"
SSL_DIR="/etc/ssl/${DOMAIN}"
NGINX_SITE="/etc/nginx/sites-available/lostgifts.ru.conf"

CERTBOT_EMAIL="ssl@lostgifts.ru"
if [ -f "${APP_DIR}/.env" ] && grep -q '^CERTBOT_EMAIL=' "${APP_DIR}/.env"; then
  CERTBOT_EMAIL="$(grep '^CERTBOT_EMAIL=' "${APP_DIR}/.env" | cut -d= -f2- | tr -d '"')"
fi

mkdir -p /var/www/certbot "${SSL_DIR}"
mkdir -p /etc/nginx/snippets

cat > /etc/nginx/conf.d/lostgifts-rate-limit.conf <<'RATE'
limit_req_zone $binary_remote_addr zone=lostgifts_web:10m rate=3r/s;
limit_req_zone $binary_remote_addr zone=lostgifts_api:10m rate=1r/s;
limit_conn_zone $binary_remote_addr zone=lostgifts_conn:10m;
limit_req_status 429;
RATE

cat > /etc/nginx/snippets/lostgifts-security-headers.conf <<'HDR'
add_header X-Content-Type-Options nosniff always;
add_header X-Frame-Options SAMEORIGIN always;
add_header Referrer-Policy strict-origin-when-cross-origin always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=()" always;
add_header Cross-Origin-Opener-Policy same-origin always;
add_header Cross-Origin-Resource-Policy same-site always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header Content-Security-Policy "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'; object-src 'none'; script-src 'self' https://cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' https: data:; connect-src 'self' https://nft.fragment.com; upgrade-insecure-requests" always;
HDR

cat > /etc/nginx/snippets/cloudflare-allow.conf <<'SNIP'
include /etc/nginx/snippets/cloudflare-real-ip.conf;

allow 103.21.244.0/22;
allow 103.22.200.0/22;
allow 103.31.4.0/22;
allow 104.16.0.0/13;
allow 104.24.0.0/14;
allow 108.162.192.0/18;
allow 131.0.72.0/22;
allow 141.101.64.0/18;
allow 162.158.0.0/15;
allow 172.64.0.0/13;
allow 173.245.48.0/20;
allow 188.114.96.0/20;
allow 190.93.240.0/20;
allow 197.234.240.0/22;
allow 198.41.128.0/17;
allow 2400:cb00::/32;
allow 2606:4700::/32;
allow 2803:f800::/32;
allow 2405:b500::/32;
allow 2405:8100::/32;
allow 2a06:98c0::/29;
allow 2c0f:f248::/32;
deny all;
SNIP

issue_self_signed() {
  openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
    -keyout /etc/ssl/private/${DOMAIN}.key \
    -out "${SSL_DIR}/origin.pem" \
    -subj "/CN=${DOMAIN}" \
    -addext "subjectAltName=DNS:${DOMAIN},DNS:www.${DOMAIN},DNS:admin.${DOMAIN}" 2>/dev/null
  cp "${SSL_DIR}/origin.pem" "${SSL_DIR}/fullchain.pem"
  chmod 600 /etc/ssl/private/${DOMAIN}.key
}

issue_letsencrypt() {
  certbot certonly --webroot \
    -w /var/www/certbot \
    -d "${DOMAIN}" -d "www.${DOMAIN}" \
    --non-interactive --agree-tos -m "${CERTBOT_EMAIL}" \
    --cert-name "${DOMAIN}"
}

if [ ! -f "${SSL_DIR}/fullchain.pem" ] && [ ! -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]; then
  if issue_letsencrypt 2>/dev/null; then
    SSL_CERT="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
    SSL_KEY="/etc/letsencrypt/live/${DOMAIN}/privkey.pem"
  else
    echo "LE failed (DNS pending?) — using origin self-signed for Cloudflare Full"
    issue_self_signed
    SSL_CERT="${SSL_DIR}/fullchain.pem"
    SSL_KEY="/etc/ssl/private/${DOMAIN}.key"
  fi
elif [ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]; then
  SSL_CERT="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
  SSL_KEY="/etc/letsencrypt/live/${DOMAIN}/privkey.pem"
else
  SSL_CERT="${SSL_DIR}/fullchain.pem"
  SSL_KEY="/etc/ssl/private/${DOMAIN}.key"
fi

cat > "${NGINX_SITE}" <<NGINX
map \$http_upgrade \$connection_upgrade_lostgifts {
    default upgrade;
    "" close;
}

server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN} www.${DOMAIN};

    include /etc/nginx/snippets/cloudflare-allow.conf;

    location /.well-known/acme-challenge/ {
        allow all;
        root /var/www/certbot;
    }

    location / {
        return 301 https://${DOMAIN}\$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name www.${DOMAIN};

    include /etc/nginx/snippets/cloudflare-allow.conf;
    ssl_certificate     ${SSL_CERT};
    ssl_certificate_key ${SSL_KEY};
    include /etc/nginx/snippets/ssl-params.conf;
    include /etc/nginx/snippets/lostgifts-security-headers.conf;

    return 301 https://${DOMAIN}\$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${DOMAIN};

    include /etc/nginx/snippets/cloudflare-allow.conf;
    ssl_certificate     ${SSL_CERT};
    ssl_certificate_key ${SSL_KEY};
    include /etc/nginx/snippets/ssl-params.conf;
    include /etc/nginx/snippets/lostgifts-security-headers.conf;

    client_max_body_size 1m;
    limit_conn lostgifts_conn 15;
    limit_req zone=lostgifts_web burst=10 nodelay;

    location = /health {
        allow 127.0.0.1;
        allow ::1;
        deny all;
        proxy_pass http://127.0.0.1:8877;
    }

    location /api/hist/ {
        limit_req zone=lostgifts_api burst=3 nodelay;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header CF-Connecting-IP \$http_cf_connecting_ip;
        proxy_connect_timeout 30s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
        proxy_pass http://127.0.0.1:8877;
    }

    location / {
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header CF-Connecting-IP \$http_cf_connecting_ip;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade_lostgifts;
        proxy_connect_timeout 30s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
        proxy_buffering off;
        proxy_pass http://127.0.0.1:8877;
    }
}
NGINX

ln -sf "${NGINX_SITE}" /etc/nginx/sites-enabled/lostgifts.ru.conf
nginx -t
systemctl reload nginx

sed -i "s|WEB_HOST=.*|WEB_HOST=127.0.0.1|" "${APP_DIR}/.env"
sed -i "s|WEB_BASE_URL=.*|WEB_BASE_URL=https://${DOMAIN}|" "${APP_DIR}/.env"
if ! grep -q '^API_ENABLED=' "${APP_DIR}/.env"; then
  echo 'API_ENABLED=false' >> "${APP_DIR}/.env"
fi
sed -i "s|--host 0.0.0.0|--host 127.0.0.1|g" /etc/systemd/system/lostgifts-web.service 2>/dev/null || \
sed -i "s|--host 0.0.0.0|--host 127.0.0.1|g" /etc/systemd/system/alex-gift-web.service 2>/dev/null || true
ufw delete allow 8877/tcp 2>/dev/null || true
ufw delete allow 6379/tcp 2>/dev/null || true

systemctl daemon-reload
systemctl restart lostgifts-web lostgifts-bot 2>/dev/null || \
systemctl restart alex-gift-web alex-gift-bot 2>/dev/null || true
systemctl reload nginx

echo "SSL cert: ${SSL_CERT}"
echo "Site: https://${DOMAIN}"
echo "Cloudflare NS: albert.ns.cloudflare.com, fiona.ns.cloudflare.com"
echo "Set Cloudflare SSL mode: Full (now) -> Full (strict) after Origin CA or LE cert"
