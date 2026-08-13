from __future__ import annotations

import hashlib
import hmac
import secrets
import time

import redis as sync_redis

from src.web.security import MAX_PASSWORD_LEN

SESSION_TTL = 86400
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW = 900
CSRF_TTL = 600


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if len(password) > MAX_PASSWORD_LEN:
        return False
    try:
        _, salt_hex, digest_hex = stored.split("$", 2)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, TypeError):
        return False
    actual = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )
    return hmac.compare_digest(actual, expected)


class AdminAuth:
    def __init__(self, redis_url: str, password_hash: str, session_secret: str) -> None:
        self._client = sync_redis.from_url(redis_url, decode_responses=True)
        self._password_hash = password_hash
        self._session_secret = session_secret

    def close(self) -> None:
        self._client.close()

    def _session_key(self, token: str) -> str:
        return f"admin:session:{token}"

    def _login_key(self, ip: str) -> str:
        return f"admin:login_fail:{ip}"

    def _csrf_key(self, token: str) -> str:
        return f"admin:csrf:{token}"

    def login_allowed(self, ip: str) -> bool:
        fails = int(self._client.get(self._login_key(ip)) or 0)
        return fails < LOGIN_MAX_ATTEMPTS

    def register_fail(self, ip: str) -> None:
        key = self._login_key(ip)
        pipe = self._client.pipeline()
        pipe.incr(key)
        pipe.expire(key, LOGIN_WINDOW)
        pipe.execute()

    def clear_fails(self, ip: str) -> None:
        self._client.delete(self._login_key(ip))

    def issue_csrf(self, ip: str) -> str:
        token = secrets.token_urlsafe(24)
        self._client.setex(self._csrf_key(token), CSRF_TTL, ip)
        return token

    def consume_csrf(self, token: str, ip: str) -> bool:
        if not token:
            return False
        key = self._csrf_key(token)
        stored = self._client.get(key)
        if not stored or stored != ip:
            return False
        self._client.delete(key)
        return True

    def verify_login(self, password: str, ip: str) -> str | None:
        if not self.login_allowed(ip):
            return None
        if not verify_password(password, self._password_hash):
            self.register_fail(ip)
            return None
        self.clear_fails(ip)
        token = secrets.token_urlsafe(32)
        self._client.setex(self._session_key(token), SESSION_TTL, ip)
        return token

    def validate_session(self, token: str | None, ip: str) -> bool:
        if not token:
            return False
        stored_ip = self._client.get(self._session_key(token))
        return bool(stored_ip and stored_ip == ip)

    def revoke_session(self, token: str | None) -> None:
        if token:
            self._client.delete(self._session_key(token))
