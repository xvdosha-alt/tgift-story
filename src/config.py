import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    redis_url: str
    bot_token: str
    web_host: str
    web_port: int
    web_base_url: str
    logger_worker_id: int
    logger_workers: int
    poll_interval: float
    request_timeout: float
    logger_batch_size: int
    logger_concurrency: int
    logger_request_delay: float
    fetch_cache_ttl: float
    update_lock_ttl: int
    rate_limit_requests: int
    rate_limit_window: float
    bot_rate_limit_requests: int
    bot_rate_limit_window: float
    api_enabled: bool
    api_token: str
    admin_host: str
    admin_port: int
    admin_base_url: str
    admin_password_hash: str
    admin_gate_path: str
    admin_session_secret: str


def get_settings() -> Settings:
    return Settings(
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        bot_token=os.getenv("BOT_TOKEN", ""),
        web_host=os.getenv("WEB_HOST", "0.0.0.0"),
        web_port=int(os.getenv("WEB_PORT", "8080")),
        web_base_url=os.getenv("WEB_BASE_URL", "http://localhost:8080").rstrip("/"),
        logger_worker_id=int(os.getenv("LOGGER_WORKER_ID", "0")),
        logger_workers=max(1, int(os.getenv("LOGGER_WORKERS", "1"))),
        poll_interval=float(os.getenv("POLL_INTERVAL", "60")),
        request_timeout=float(os.getenv("REQUEST_TIMEOUT", "15")),
        logger_batch_size=max(1, int(os.getenv("LOGGER_BATCH_SIZE", "5"))),
        logger_concurrency=max(1, int(os.getenv("LOGGER_CONCURRENCY", "2"))),
        logger_request_delay=max(0.0, float(os.getenv("LOGGER_REQUEST_DELAY", "1.5"))),
        fetch_cache_ttl=max(0.0, float(os.getenv("FETCH_CACHE_TTL", "90"))),
        update_lock_ttl=max(5, int(os.getenv("UPDATE_LOCK_TTL", "30"))),
        rate_limit_requests=max(1, int(os.getenv("RATE_LIMIT_REQUESTS", "30"))),
        rate_limit_window=max(1.0, float(os.getenv("RATE_LIMIT_WINDOW", "60"))),
        bot_rate_limit_requests=max(1, int(os.getenv("BOT_RATE_LIMIT_REQUESTS", "10"))),
        bot_rate_limit_window=max(1.0, float(os.getenv("BOT_RATE_LIMIT_WINDOW", "60"))),
        api_enabled=os.getenv("API_ENABLED", "false").lower() in ("1", "true", "yes"),
        api_token=os.getenv("API_TOKEN", ""),
        admin_host=os.getenv("ADMIN_HOST", "127.0.0.1"),
        admin_port=int(os.getenv("ADMIN_PORT", "8878")),
        admin_base_url=os.getenv("ADMIN_BASE_URL", "https://admin.lostgifts.ru").rstrip("/"),
        admin_password_hash=os.getenv("ADMIN_PASSWORD_HASH", ""),
        admin_gate_path=os.getenv("ADMIN_GATE_PATH", "").strip("/"),
        admin_session_secret=os.getenv("ADMIN_SESSION_SECRET", ""),
    )
