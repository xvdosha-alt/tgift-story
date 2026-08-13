from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass

import redis as sync_redis

from src.models import utcnow_iso

MAX_EVENTS = 50_000
MAX_CHAIN_LEN = 500
MAX_UA_LEN = 180
MAX_INPUT_LEN = 256
MAX_SLUG_LEN = 128
MAX_PATH_LEN = 256

IP_KEY_RE = re.compile(r"^tg:\d+$")


class ActivityKeys:
    EVENTS = "activity:events"
    IPS = "activity:ips"
    IP_CHAIN = "activity:ip:{ip}:chain"
    STATS = "activity:stats"


def _safe_ip_key(ip: str) -> str:
    ip = (ip or "unknown").strip()
    if IP_KEY_RE.match(ip):
        return ip[:32]
    if re.match(r"^[\d.a-fA-F:]+$", ip):
        return ip[:64]
    cleaned = re.sub(r"[^a-zA-Z0-9:._-]", "_", ip)
    return (cleaned or "unknown")[:64]


@dataclass
class ActivityEvent:
    id: str
    at: str
    ip: str
    event: str
    input: str
    slug: str
    path: str
    source: str
    ua: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "at": self.at,
            "ip": self.ip,
            "event": self.event,
            "input": self.input,
            "slug": self.slug,
            "path": self.path,
            "source": self.source,
            "ua": self.ua,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ActivityEvent:
        return cls(
            id=str(data.get("id", ""))[:64],
            at=str(data.get("at", ""))[:32],
            ip=str(data.get("ip", ""))[:64],
            event=str(data.get("event", ""))[:32],
            input=str(data.get("input", ""))[:MAX_INPUT_LEN],
            slug=str(data.get("slug", ""))[:MAX_SLUG_LEN],
            path=str(data.get("path", ""))[:MAX_PATH_LEN],
            source=str(data.get("source", ""))[:64],
            ua=str(data.get("ua", ""))[:MAX_UA_LEN],
        )


class ActivityStore:
    def __init__(self, redis_url: str) -> None:
        self._client: sync_redis.Redis | None = None
        self._redis_url = redis_url

    def connect(self) -> None:
        self._client = sync_redis.from_url(self._redis_url, decode_responses=True)

    def close(self) -> None:
        if self._client:
            self._client.close()

    @property
    def client(self) -> sync_redis.Redis:
        if not self._client:
            raise RuntimeError("ActivityStore is not connected")
        return self._client

    def record(
        self,
        *,
        ip: str,
        event: str,
        input_value: str = "",
        slug: str = "",
        path: str = "",
        source: str = "web",
        ua: str = "",
    ) -> ActivityEvent:
        safe_event = re.sub(r"[^a-z_]", "", event)[:32] or "unknown"
        item = ActivityEvent(
            id=uuid.uuid4().hex,
            at=utcnow_iso(),
            ip=ip or "unknown",
            event=safe_event,
            input=(input_value or "")[:MAX_INPUT_LEN],
            slug=(slug or "")[:MAX_SLUG_LEN],
            path=(path or "")[:MAX_PATH_LEN],
            source=(source or "web")[:64],
            ua=(ua or "")[:MAX_UA_LEN],
        )
        payload = json.dumps(item.to_dict(), ensure_ascii=False)
        ip_key = ActivityKeys.IP_CHAIN.format(ip=_safe_ip_key(item.ip))
        pipe = self.client.pipeline()
        pipe.lpush(ActivityKeys.EVENTS, payload)
        pipe.ltrim(ActivityKeys.EVENTS, 0, MAX_EVENTS - 1)
        pipe.sadd(ActivityKeys.IPS, _safe_ip_key(item.ip))
        pipe.lpush(ip_key, payload)
        pipe.ltrim(ip_key, 0, MAX_CHAIN_LEN - 1)
        pipe.hincrby(ActivityKeys.STATS, "total_events", 1)
        pipe.hincrby(ActivityKeys.STATS, f"event:{safe_event}", 1)
        pipe.execute()
        return item

    def list_events(self, limit: int = 200, offset: int = 0) -> list[ActivityEvent]:
        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        raw = self.client.lrange(ActivityKeys.EVENTS, offset, offset + limit - 1)
        return [ActivityEvent.from_dict(json.loads(x)) for x in raw]

    def ip_chain(self, ip: str, limit: int = 100) -> list[ActivityEvent]:
        limit = max(1, min(limit, 200))
        raw = self.client.lrange(ActivityKeys.IP_CHAIN.format(ip=_safe_ip_key(ip)), 0, limit - 1)
        return [ActivityEvent.from_dict(json.loads(x)) for x in raw]

    def unique_ips(self) -> int:
        return int(self.client.scard(ActivityKeys.IPS))

    def total_events(self) -> int:
        val = self.client.hget(ActivityKeys.STATS, "total_events")
        return int(val or 0)

    def top_ips(self, limit: int = 50) -> list[tuple[str, int]]:
        limit = max(1, min(limit, 200))
        ips = list(self.client.smembers(ActivityKeys.IPS))
        scored: list[tuple[str, int]] = []
        for ip in ips:
            count = self.client.llen(ActivityKeys.IP_CHAIN.format(ip=ip))
            scored.append((ip, count))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def events_by_ip(self) -> dict[str, list[ActivityEvent]]:
        result: dict[str, list[ActivityEvent]] = {}
        for ip, _ in self.top_ips(100):
            result[ip] = self.ip_chain(ip, 50)
        return result
