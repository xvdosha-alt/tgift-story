from __future__ import annotations

import asyncio
import logging

from starlette.requests import Request

from src.activity.store import ActivityStore
from src.config import get_settings
from src.validation import GiftLinkError, parse_gift_link
from src.web.security import client_ip, truncate_field

log = logging.getLogger("gift-activity")

_store: ActivityStore | None = None


def _get_store() -> ActivityStore:
    global _store
    if _store is None:
        _store = ActivityStore(get_settings().redis_url)
        _store.connect()
    return _store


def _record_sync(
    *,
    ip: str,
    event: str,
    input_value: str = "",
    slug: str = "",
    path: str = "",
    source: str = "web",
    ua: str = "",
) -> None:
    try:
        _get_store().record(
            ip=ip,
            event=event,
            input_value=input_value,
            slug=slug,
            path=path,
            source=source,
            ua=ua,
        )
    except Exception:
        log.exception("activity log failed")


async def log_web_event(
    request: Request,
    *,
    event: str,
    input_value: str = "",
    slug: str = "",
) -> None:
    await asyncio.to_thread(
        _record_sync,
        ip=client_ip(request),
        event=event,
        input_value=input_value,
        slug=slug,
        path=str(request.url.path),
        source="web",
        ua=request.headers.get("user-agent", ""),
    )


async def log_web_request(request: Request) -> None:
    path = request.url.path
    query_link = truncate_field(request.query_params.get("link", ""))

    if path == "/":
        await log_web_event(request, event="index")
        return

    if path == "/search":
        slug = ""
        if query_link:
            try:
                slug = parse_gift_link(query_link).slug
            except GiftLinkError:
                slug = ""
        await log_web_event(
            request,
            event="search",
            input_value=query_link,
            slug=slug,
        )
        return

    if path.startswith("/gift/"):
        raw_slug = path.removeprefix("/gift/").split("/")[0]
        slug = raw_slug
        try:
            slug = parse_gift_link(raw_slug).slug
        except GiftLinkError:
            pass
        await log_web_event(
            request,
            event="gift_view",
            input_value=raw_slug,
            slug=slug,
        )


async def log_bot_request(
    *,
    telegram_user_id: int,
    username: str,
    input_value: str,
    slug: str,
    event: str = "bot_hist",
) -> None:
    pseudo_ip = f"tg:{telegram_user_id}"
    label = f"@{username}" if username else str(telegram_user_id)
    await asyncio.to_thread(
        _record_sync,
        ip=pseudo_ip,
        event=event,
        input_value=input_value,
        slug=slug,
        path="/bot",
        source=f"bot:{label}",
        ua="telegram",
    )
