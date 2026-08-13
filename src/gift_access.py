from __future__ import annotations

from src.config import Settings, get_settings
from src.history_service import fetch_and_track
from src.models import GiftQueryResult
from src.storage.redis_store import GiftStore


def fetch_gift_sync(link: str, settings: Settings | None = None) -> GiftQueryResult:
    settings = settings or get_settings()
    store = GiftStore(settings.redis_url)
    store.connect_sync()
    try:
        return fetch_and_track(
            link,
            store,
            cache_ttl=settings.fetch_cache_ttl,
            lock_ttl=settings.update_lock_ttl,
        )
    finally:
        store.close_sync()
