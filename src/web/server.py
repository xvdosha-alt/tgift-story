from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.activity.logger import log_web_request
from src.config import get_settings
from src.fragment_links import FragmentGiftLinks, fetch_fragment_metadata
from src.gift_access import fetch_gift_sync
from src.history_service import parse_started_notice
from src.models import GiftQueryResult, format_datetime
from src.validation import GiftLinkError, parse_gift_link
from src.web.rate_limit import RateLimiter
from src.web.sanitize import sanitize_fragment_links, sanitize_gift_result
from src.web.security import (
    MAX_ERROR_MSG_LEN,
    SECURITY_HEADERS,
    client_ip,
    is_local_request,
    safe_external_url,
    truncate_field,
)
from src.web.token import constant_time_compare

log = logging.getLogger("gift-web")
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
TEMPLATES.env.filters["safe_url"] = safe_external_url

app = FastAPI(title="Lost Gifts", docs_url=None, redoc_url=None)
_rate_limiter: RateLimiter | None = None
_search_limiter: RateLimiter | None = None


def _get_rate_limiter() -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        settings = get_settings()
        _rate_limiter = RateLimiter(
            max_requests=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window,
        )
    return _rate_limiter


def _get_search_limiter() -> RateLimiter:
    global _search_limiter
    if _search_limiter is None:
        settings = get_settings()
        _search_limiter = RateLimiter(
            max_requests=max(10, settings.rate_limit_requests // 2),
            window_seconds=settings.rate_limit_window,
        )
    return _search_limiter


def _is_rate_limited(request: Request) -> bool:
    ip = client_ip(request)
    path = request.url.path
    if path.startswith(("/gift/", "/api/hist/")):
        return not _get_rate_limiter().allow(ip)
    if path in ("/search", "/"):
        return not _get_search_limiter().allow(ip)
    return False


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    if _is_rate_limited(request):
        return JSONResponse(
            status_code=429,
            content={"detail": "Слишком много запросов. Попробуйте позже."},
            headers=SECURITY_HEADERS,
        )

    response = await call_next(request)

    if (
        request.method == "GET"
        and response.status_code < 400
        and request.url.path not in ("/health",)
    ):
        try:
            await log_web_request(request)
        except Exception:
            log.exception("activity log failed")

    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    return response


def _fetch_fragment_sync(slug: str) -> FragmentGiftLinks:
    return sanitize_fragment_links(fetch_fragment_metadata(slug))


async def _fetch_gift(link: str) -> GiftQueryResult:
    result = await asyncio.to_thread(fetch_gift_sync, link)
    return sanitize_gift_result(result)


async def _fetch_fragment(slug: str) -> FragmentGiftLinks:
    return await asyncio.to_thread(_fetch_fragment_sync, slug)


def _gift_context(
    request: Request,
    parsed_slug: str,
    result: GiftQueryResult,
    fragment: FragmentGiftLinks,
    settings,
) -> dict:
    return {
        "request": request,
        "slug": parsed_slug,
        "snapshot": result.snapshot,
        "fragment": fragment,
        "history": [
            event
            for event in result.history
            if event.event_type in ("owner_transfer", "discovered")
        ],
        "parse_started_at": result.parse_started_at,
        "parse_started_label": format_datetime(result.parse_started_at),
        "parse_notice": parse_started_notice(result.parse_started_at),
        "fetched_live": result.fetched_live,
        "web_base_url": settings.web_base_url,
    }


def _check_api_access(request: Request) -> None:
    settings = get_settings()
    if not settings.api_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    if not settings.api_token:
        raise HTTPException(status_code=404, detail="Not found")

    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth[7:].strip()
    if not constant_time_compare(token, settings.api_token):
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
async def health(request: Request) -> dict[str, str]:
    if not is_local_request(request):
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {
            "link": truncate_field(request.query_params.get("link", "")),
            "error": truncate_field(
                request.query_params.get("error", ""),
                MAX_ERROR_MSG_LEN,
            ),
        },
    )


@app.get("/search")
async def search(link: str = Query(default="", max_length=256)) -> RedirectResponse:
    from urllib.parse import quote

    clean_link = truncate_field(link)
    try:
        parsed = parse_gift_link(clean_link)
        return RedirectResponse(url=f"/gift/{parsed.slug}", status_code=302)
    except GiftLinkError as exc:
        return RedirectResponse(
            url=f"/?link={quote(clean_link)}&error={quote(str(exc)[:MAX_ERROR_MSG_LEN])}",
            status_code=302,
        )


@app.get("/gift/{slug}", response_class=HTMLResponse)
async def gift_page(request: Request, slug: str) -> HTMLResponse:
    if len(slug) > 128:
        raise HTTPException(status_code=400, detail="Invalid slug")
    settings = get_settings()
    try:
        parsed = parse_gift_link(slug)
        result, fragment = await asyncio.gather(
            _fetch_gift(parsed.url),
            _fetch_fragment(parsed.slug),
        )
    except GiftLinkError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        log.exception("gift page failed for %s", slug)
        raise HTTPException(status_code=502, detail="Не удалось загрузить данные подарка")

    return TEMPLATES.TemplateResponse(
        request,
        "gift.html",
        _gift_context(request, parsed.slug, result, fragment, settings),
    )


@app.get("/api/hist/{slug}")
async def api_hist(request: Request, slug: str) -> dict:
    if len(slug) > 128:
        raise HTTPException(status_code=400, detail="Invalid slug")
    _check_api_access(request)
    try:
        parsed = parse_gift_link(slug)
        result, fragment = await asyncio.gather(
            _fetch_gift(parsed.url),
            _fetch_fragment(parsed.slug),
        )
        return {
            "slug": parsed.slug,
            "snapshot": result.snapshot.to_dict(),
            "history": [event.to_dict() for event in result.history],
            "parse_started_at": result.parse_started_at,
            "parse_started_label": format_datetime(result.parse_started_at),
            "parse_notice": parse_started_notice(result.parse_started_at),
            "fetched_live": result.fetched_live,
            "fragment": {
                "telegram_url": fragment.telegram_url,
                "fragment_json": fragment.fragment_json,
                "fragment_webp": fragment.fragment_webp,
                "lottie_url": fragment.lottie_url,
                "metadata": fragment.metadata,
            },
        }
    except GiftLinkError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        log.exception("api hist failed for %s", slug)
        raise HTTPException(status_code=502, detail="Не удалось загрузить данные подарка")
