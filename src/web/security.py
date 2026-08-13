from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

from starlette.requests import Request

MAX_QUERY_FIELD_LEN = 256
MAX_ERROR_MSG_LEN = 200
MAX_PASSWORD_LEN = 128

TRUSTED_PROXY_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

ALLOWED_URL_SUFFIXES = (
    "fragment.com",
    "telesco.pe",
    "telegram.org",
    "telegram-cdn.org",
    "t.me",
    "cdn-telegram.org",
)

PRIVATE_HOST_RE = re.compile(
    r"^(localhost|metadata\.google\.internal|metadata\.google\.com)$",
    re.IGNORECASE,
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'self'; "
        "object-src 'none'; "
        "script-src 'self' https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' https: data:; "
        "connect-src 'self' https://nft.fragment.com; "
        "upgrade-insecure-requests"
    ),
}


def truncate_field(value: str, max_len: int = MAX_QUERY_FIELD_LEN) -> str:
    text = (value or "").strip()
    if len(text) > max_len:
        return text[:max_len]
    return text


def is_valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value.strip())
        return True
    except ValueError:
        return False


def _host_allowed(host: str) -> bool:
    host = host.lower().rstrip(".")
    if PRIVATE_HOST_RE.match(host):
        return False
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    except ValueError:
        pass
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in ALLOWED_URL_SUFFIXES)


def safe_external_url(url: str) -> str:
    if not url:
        return ""
    text = url.strip()
    if len(text) > 2048 or "\x00" in text:
        return ""
    try:
        parsed = urlparse(text)
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https"):
        return ""
    if parsed.username or parsed.password:
        return ""
    host = (parsed.hostname or "").lower()
    if not host or not _host_allowed(host):
        return ""
    return parsed.geturl()


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else ""
    if peer in TRUSTED_PROXY_HOSTS:
        cf_ip = request.headers.get("cf-connecting-ip", "").strip()
        if cf_ip and is_valid_ip(cf_ip):
            return cf_ip
        real_ip = request.headers.get("x-real-ip", "").strip()
        if real_ip and is_valid_ip(real_ip):
            return real_ip
    if peer:
        return peer
    return "unknown"


def is_local_request(request: Request) -> bool:
    peer = request.client.host if request.client else ""
    return peer in TRUSTED_PROXY_HOSTS
