from __future__ import annotations

from datetime import datetime, timezone


def is_cache_fresh(fetched_at: str, ttl_seconds: float) -> bool:
    if ttl_seconds <= 0 or not fetched_at:
        return False
    dt = datetime.fromisoformat(fetched_at)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - dt).total_seconds()
    return age < ttl_seconds
