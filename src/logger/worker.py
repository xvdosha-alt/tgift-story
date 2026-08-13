from __future__ import annotations

import asyncio
import logging
import signal
from typing import Iterable

from src.api.telegram_scraper import TelegramGiftScraper, diff_snapshots
from src.events import build_transfer_event, should_record_diff
from src.config import get_settings
from src.models import utcnow_iso
from src.storage.redis_store import GiftStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("gift-logger")


class GiftLoggerWorker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.store = GiftStore(self.settings.redis_url)
        self.scraper = TelegramGiftScraper(timeout=self.settings.request_timeout)
        self._stop = asyncio.Event()
        self._sem = asyncio.Semaphore(self.settings.logger_concurrency)

    async def run(self, seed_slugs: Iterable[str] | None = None) -> None:
        await self.store.connect()
        if seed_slugs:
            await self.store.register_gifts(list(seed_slugs))

        worker_id = self.settings.logger_worker_id
        workers = self.settings.logger_workers
        log.info(
            "Worker %s/%s started (batch=%s concurrency=%s interval=%ss)",
            worker_id,
            workers,
            self.settings.logger_batch_size,
            self.settings.logger_concurrency,
            self.settings.poll_interval,
        )

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._stop.set)

        try:
            while not self._stop.is_set():
                await self.store.heartbeat(worker_id)
                batch = await self.store.pop_poll_batch(
                    worker_id,
                    workers,
                    batch_size=self.settings.logger_batch_size,
                )
                if batch:
                    await asyncio.gather(*(self._poll_slug_safe(slug) for slug in batch))

                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.settings.poll_interval)
                except asyncio.TimeoutError:
                    pass
        finally:
            await self.scraper.aclose()
            await self.store.close()
            log.info("Worker stopped")

    async def _poll_slug_safe(self, slug: str) -> None:
        async with self._sem:
            try:
                await self._poll_slug(slug)
            except Exception as exc:
                log.exception("Unexpected error polling %s: %s", slug, exc)
            if self.settings.logger_request_delay:
                await asyncio.sleep(self.settings.logger_request_delay)

    async def _poll_slug(self, slug: str) -> None:
        try:
            snapshot = await self.scraper.fetch(slug)
        except Exception as exc:
            log.warning("Failed to fetch %s: %s", slug, exc)
            return

        old_hash = await self.store.get_response_hash(slug)
        if old_hash == snapshot.response_hash:
            return

        if not await self.store.acquire_update_lock(slug, self.settings.update_lock_ttl):
            log.debug("Skip update for %s — lock held", slug)
            return

        try:
            old_state = await self.store.get_state(slug)
            old_hash = await self.store.get_response_hash(slug)
            if old_hash == snapshot.response_hash:
                return

            diff = diff_snapshots(old_state, snapshot)
            if old_state is None:
                await self.store.set_tracked_since(slug, utcnow_iso())

            if should_record_diff(diff, is_initial_fetch=old_state is None):
                event = build_transfer_event(slug, snapshot, diff)
                await self.store.append_history(event)
                log.info("Change detected for %s: %s", slug, diff)

            await self.store.save_state(snapshot)
            await self.store.save_response_hash(slug, snapshot.response_hash)
        finally:
            await self.store.release_update_lock(slug)

    async def poll_once(self, slug: str) -> None:
        await self.store.connect()
        try:
            await self.store.ensure_gift_tracked(slug)
            await self._poll_slug(slug)
        finally:
            await self.scraper.aclose()
            await self.store.close()


async def main() -> None:
    import sys

    worker = GiftLoggerWorker()
    seeds = sys.argv[1:] if len(sys.argv) > 1 else None
    await worker.run(seed_slugs=seeds)


if __name__ == "__main__":
    asyncio.run(main())
