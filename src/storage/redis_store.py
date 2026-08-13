from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis
import redis as sync_redis

from src.models import GiftSnapshot, TransferEvent


class RedisKeys:
    ALL_GIFTS = "gifts:all"
    WORKER_HEARTBEAT = "gifts:worker:{worker_id}:heartbeat"

    @staticmethod
    def gift_state(slug: str) -> str:
        return f"gift:{slug}:state"

    @staticmethod
    def gift_history(slug: str) -> str:
        return f"gift:{slug}:history"

    @staticmethod
    def gift_response_hash(slug: str) -> str:
        return f"gift:{slug}:response_hash"

    @staticmethod
    def gift_search_index(slug: str) -> str:
        return f"gift:{slug}:search"

    @staticmethod
    def gift_tracked_since(slug: str) -> str:
        return f"gift:{slug}:tracked_since"

    @staticmethod
    def gift_update_lock(slug: str) -> str:
        return f"gift:{slug}:update_lock"

    @staticmethod
    def poll_cursor(worker_id: int) -> str:
        return f"gifts:poll_cursor:{worker_id}"


class GiftStore:
    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client: aioredis.Redis | None = None
        self._sync_client: sync_redis.Redis | None = None

    async def connect(self) -> None:
        self._client = aioredis.from_url(self._redis_url, decode_responses=True)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    def connect_sync(self) -> None:
        self._sync_client = sync_redis.from_url(self._redis_url, decode_responses=True)

    def close_sync(self) -> None:
        if self._sync_client:
            self._sync_client.close()

    @property
    def client(self) -> aioredis.Redis:
        if not self._client:
            raise RuntimeError("Async Redis client is not connected")
        return self._client

    @property
    def sync_client(self) -> sync_redis.Redis:
        if not self._sync_client:
            raise RuntimeError("Sync Redis client is not connected")
        return self._sync_client

    async def register_gift(self, slug: str) -> None:
        await self.client.sadd(RedisKeys.ALL_GIFTS, slug)

    async def register_gifts(self, slugs: list[str]) -> None:
        if slugs:
            await self.client.sadd(RedisKeys.ALL_GIFTS, *slugs)

    async def get_state(self, slug: str) -> GiftSnapshot | None:
        raw = await self.client.get(RedisKeys.gift_state(slug))
        if not raw:
            return None
        return GiftSnapshot.from_dict(json.loads(raw))

    def get_state_sync(self, slug: str) -> GiftSnapshot | None:
        raw = self.sync_client.get(RedisKeys.gift_state(slug))
        if not raw:
            return None
        return GiftSnapshot.from_dict(json.loads(raw))

    async def save_state(self, snapshot: GiftSnapshot) -> None:
        await self.client.set(
            RedisKeys.gift_state(snapshot.slug),
            json.dumps(snapshot.to_dict(), ensure_ascii=False),
        )
        await self._update_search_index(snapshot)

    async def get_response_hash(self, slug: str) -> str | None:
        return await self.client.get(RedisKeys.gift_response_hash(slug))

    def get_response_hash_sync(self, slug: str) -> str | None:
        return self.sync_client.get(RedisKeys.gift_response_hash(slug))

    async def save_response_hash(self, slug: str, response_hash: str) -> None:
        await self.client.set(RedisKeys.gift_response_hash(slug), response_hash)

    def save_response_hash_sync(self, slug: str, response_hash: str) -> None:
        self.sync_client.set(RedisKeys.gift_response_hash(slug), response_hash)

    async def append_history(self, event: TransferEvent) -> None:
        key = RedisKeys.gift_history(event.slug)
        pipe = self.client.pipeline()
        pipe.rpush(key, json.dumps(event.to_dict(), ensure_ascii=False))
        pipe.ltrim(key, -500, -1)
        await pipe.execute()

    async def get_history(self, slug: str) -> list[TransferEvent]:
        raw_items = await self.client.lrange(RedisKeys.gift_history(slug), 0, -1)
        return [TransferEvent.from_dict(json.loads(item)) for item in raw_items]

    def get_history_sync(self, slug: str) -> list[TransferEvent]:
        raw_items = self.sync_client.lrange(RedisKeys.gift_history(slug), 0, -1)
        return [TransferEvent.from_dict(json.loads(item)) for item in raw_items]

    async def get_tracked_since(self, slug: str) -> str | None:
        return await self.client.get(RedisKeys.gift_tracked_since(slug))

    def get_tracked_since_sync(self, slug: str) -> str | None:
        return self.sync_client.get(RedisKeys.gift_tracked_since(slug))

    async def set_tracked_since(self, slug: str, tracked_since: str) -> None:
        await self.client.setnx(RedisKeys.gift_tracked_since(slug), tracked_since)

    def set_tracked_since_sync(self, slug: str, tracked_since: str) -> None:
        self.sync_client.setnx(RedisKeys.gift_tracked_since(slug), tracked_since)

    def save_state_sync(self, snapshot: GiftSnapshot) -> None:
        self.sync_client.set(
            RedisKeys.gift_state(snapshot.slug),
            json.dumps(snapshot.to_dict(), ensure_ascii=False),
        )
        index = {
            "slug": snapshot.slug,
            "name": snapshot.name,
            "owner": snapshot.owner,
            "model": snapshot.model,
        }
        self.sync_client.set(
            RedisKeys.gift_search_index(snapshot.slug),
            json.dumps(index, ensure_ascii=False),
        )

    def append_history_sync(self, event: TransferEvent) -> None:
        key = RedisKeys.gift_history(event.slug)
        pipe = self.sync_client.pipeline()
        pipe.rpush(key, json.dumps(event.to_dict(), ensure_ascii=False))
        pipe.ltrim(key, -500, -1)
        pipe.execute()

    async def acquire_update_lock(self, slug: str, ttl: int) -> bool:
        return bool(
            await self.client.set(
                RedisKeys.gift_update_lock(slug),
                "1",
                nx=True,
                ex=ttl,
            )
        )

    async def release_update_lock(self, slug: str) -> None:
        await self.client.delete(RedisKeys.gift_update_lock(slug))

    def acquire_update_lock_sync(self, slug: str, ttl: int) -> bool:
        return bool(
            self.sync_client.set(
                RedisKeys.gift_update_lock(slug),
                "1",
                nx=True,
                ex=ttl,
            )
        )

    def release_update_lock_sync(self, slug: str) -> None:
        self.sync_client.delete(RedisKeys.gift_update_lock(slug))

    async def pop_poll_batch(self, worker_id: int, workers: int, batch_size: int = 10) -> list[str]:
        all_slugs = await self.client.smembers(RedisKeys.ALL_GIFTS)
        my_slugs = sorted(
            slug for slug in all_slugs if self._shard(slug, workers) == worker_id
        )
        if not my_slugs:
            return []

        cursor_raw = await self.client.get(RedisKeys.poll_cursor(worker_id))
        cursor = int(cursor_raw or 0) % len(my_slugs)
        batch: list[str] = []
        for offset in range(batch_size):
            batch.append(my_slugs[(cursor + offset) % len(my_slugs)])
        next_cursor = (cursor + batch_size) % len(my_slugs)
        await self.client.set(RedisKeys.poll_cursor(worker_id), str(next_cursor))
        return batch

    async def heartbeat(self, worker_id: int) -> None:
        await self.client.set(RedisKeys.WORKER_HEARTBEAT.format(worker_id=worker_id), "1", ex=120)

    async def search_by_owner(self, owner_query: str, limit: int = 20) -> list[str]:
        query = owner_query.lower()
        slugs = await self.client.smembers(RedisKeys.ALL_GIFTS)
        matched: list[str] = []
        for slug in slugs:
            index_raw = await self.client.get(RedisKeys.gift_search_index(slug))
            if not index_raw:
                continue
            index = json.loads(index_raw)
            if query in index.get("owner", "").lower():
                matched.append(slug)
            if len(matched) >= limit:
                break
        return matched

    async def _update_search_index(self, snapshot: GiftSnapshot) -> None:
        index = {
            "slug": snapshot.slug,
            "name": snapshot.name,
            "owner": snapshot.owner,
            "model": snapshot.model,
        }
        await self.client.set(
            RedisKeys.gift_search_index(snapshot.slug),
            json.dumps(index, ensure_ascii=False),
        )

    @staticmethod
    def _shard(slug: str, workers: int) -> int:
        return sum(ord(c) for c in slug) % workers

    async def ensure_gift_tracked(self, slug: str) -> None:
        exists = await self.client.sismember(RedisKeys.ALL_GIFTS, slug)
        if not exists:
            await self.register_gift(slug)

    def ensure_gift_tracked_sync(self, slug: str) -> None:
        self.sync_client.sadd(RedisKeys.ALL_GIFTS, slug)
