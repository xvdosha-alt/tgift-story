from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock

MAX_TRACKED_KEYS = 10_000


@dataclass
class RateLimiter:
    max_requests: int
    window_seconds: float
    _hits: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    _lock: Lock = field(default_factory=Lock)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > MAX_TRACKED_KEYS:
                self._prune(now)
            bucket = [t for t in self._hits[key] if t > now - self.window_seconds]
            if len(bucket) >= self.max_requests:
                self._hits[key] = bucket
                return False
            bucket.append(now)
            self._hits[key] = bucket
            return True

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        stale = [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]
        for key in stale[:5000]:
            del self._hits[key]
