from __future__ import annotations

import time

from src.api.telegram_scraper import TelegramGiftScraper, diff_snapshots
from src.cache import is_cache_fresh
from src.events import build_transfer_event, should_record_diff
from src.models import GiftQueryResult, GiftSnapshot, TransferEvent, format_datetime, utcnow_iso
from src.storage.redis_store import GiftStore
from src.validation import parse_gift_link

_scraper: TelegramGiftScraper | None = None


def _get_scraper() -> TelegramGiftScraper:
    global _scraper
    if _scraper is None:
        _scraper = TelegramGiftScraper()
    return _scraper


def parse_started_notice(parse_started_at: str) -> str:
    when = format_datetime(parse_started_at)
    return (
        f"Парсинг начат с {when}. "
        f"Передачи до этой даты недоступны — видны только изменения после старта отслеживания."
    )


def format_transfer_chain(result: GiftQueryResult) -> str:
    slug = result.slug
    snapshot = result.snapshot
    history = result.history
    lines = [f"🎁 {slug}", ""]

    if snapshot:
        lines.extend(
            [
                f"Название: {snapshot.name} #{snapshot.number}",
                f"Владелец: {snapshot.owner or '—'}",
                f"Model: {snapshot.model or '—'}",
                f"Backdrop: {snapshot.backdrop or '—'}",
                f"Symbol: {snapshot.symbol or '—'}",
                f"Quantity: {snapshot.quantity or '—'}",
                "",
            ]
        )

    lines.append(f"ℹ️ {parse_started_notice(result.parse_started_at)}")
    if result.fetched_live:
        lines.append("⚡ Данные получены вне очереди (первый запрос)")
    lines.append("")
    lines.append("═══ Цепочка передач ═══")

    transfer_events = [
        e for e in history if e.event_type in ("owner_transfer", "discovered")
    ]

    if not transfer_events:
        lines.append("  (передач пока не зафиксировано)")
        if snapshot and snapshot.owner:
            lines.append(f"  → текущий владелец: {snapshot.owner}")
        return "\n".join(lines)

    for idx, event in enumerate(transfer_events, 1):
        ts = event.recorded_at[:19].replace("T", " ")
        if event.event_type == "owner_transfer":
            arrow = f"{event.from_owner or '?'} → {event.to_owner or '?'}"
            lines.append(f"  {idx}. [{ts}] {arrow}")
        elif event.event_type == "discovered":
            lines.append(f"  {idx}. [{ts}] обнаружен → {event.to_owner or '?'}")
        else:
            diff_parts = []
            for field, change in event.diff.items():
                if isinstance(change, dict) and "from" in change and "to" in change:
                    diff_parts.append(f"{field}: {change['from']} → {change['to']}")
                else:
                    diff_parts.append(f"{field}: {change}")
            lines.append(f"  {idx}. [{ts}] {', '.join(diff_parts) or event.event_type}")

    if snapshot:
        lines.append("")
        lines.append(f"→ сейчас: {snapshot.owner}")

    return "\n".join(lines)


def _build_result(
    slug: str,
    snapshot: GiftSnapshot,
    history: list[TransferEvent],
    parse_started: str | None,
    *,
    fetched_live: bool,
) -> GiftQueryResult:
    return GiftQueryResult(
        slug=slug,
        snapshot=snapshot,
        history=history,
        parse_started_at=parse_started or utcnow_iso(),
        fetched_live=fetched_live,
    )


def _load_cached_result(
    store: GiftStore,
    slug: str,
    snapshot: GiftSnapshot,
    *,
    fetched_live: bool = False,
) -> GiftQueryResult:
    history = store.get_history_sync(slug)
    parse_started = store.get_tracked_since_sync(slug)
    return _build_result(slug, snapshot, history, parse_started, fetched_live=fetched_live)


def _persist_snapshot(
    store: GiftStore,
    slug: str,
    old_state: GiftSnapshot | None,
    snapshot: GiftSnapshot,
    parse_started: str | None,
) -> str:
    if parse_started is None:
        parse_started = utcnow_iso()
        store.set_tracked_since_sync(slug, parse_started)

    diff = diff_snapshots(old_state, snapshot)
    if should_record_diff(diff, is_initial_fetch=old_state is None):
        event = build_transfer_event(slug, snapshot, diff)
        store.append_history_sync(event)

    store.save_state_sync(snapshot)
    store.save_response_hash_sync(slug, snapshot.response_hash)
    return parse_started


def _acquire_lock_with_wait(store: GiftStore, slug: str, lock_ttl: int) -> bool:
    if store.acquire_update_lock_sync(slug, lock_ttl):
        return True

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        time.sleep(0.2)
        if store.acquire_update_lock_sync(slug, lock_ttl):
            return True
        if store.get_state_sync(slug):
            return False
    return store.acquire_update_lock_sync(slug, lock_ttl)


def fetch_and_track(
    link: str,
    store: GiftStore,
    *,
    cache_ttl: float = 90.0,
    lock_ttl: int = 30,
) -> GiftQueryResult:
    parsed = parse_gift_link(link)
    slug = parsed.slug
    store.ensure_gift_tracked_sync(slug)

    old_state = store.get_state_sync(slug)
    parse_started = store.get_tracked_since_sync(slug)

    if old_state and is_cache_fresh(old_state.fetched_at, cache_ttl):
        return _load_cached_result(store, slug, old_state)

    if old_state and not _acquire_lock_with_wait(store, slug, lock_ttl):
        return _load_cached_result(store, slug, old_state)

    if old_state is None and not store.acquire_update_lock_sync(slug, lock_ttl):
        if not _acquire_lock_with_wait(store, slug, lock_ttl):
            cached = store.get_state_sync(slug)
            if cached:
                return _load_cached_result(store, slug, cached, fetched_live=True)
            raise RuntimeError("Не удалось начать загрузку подарка")

    try:
        old_state = store.get_state_sync(slug)
        if old_state and is_cache_fresh(old_state.fetched_at, cache_ttl):
            return _load_cached_result(store, slug, old_state)

        fetched_live = old_state is None
        snapshot = _get_scraper().fetch_sync(slug)
        parse_started = _persist_snapshot(store, slug, old_state, snapshot, parse_started)
        history = store.get_history_sync(slug)
        return _build_result(
            slug,
            snapshot,
            history,
            parse_started,
            fetched_live=fetched_live,
        )
    finally:
        store.release_update_lock_sync(slug)
