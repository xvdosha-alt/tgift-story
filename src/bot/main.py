#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, ContextTypes

from src.activity.logger import log_bot_request
from src.bot import emojis as e
from src.bot.formatters import format_transfer_chain_html
from src.config import get_settings
from src.gift_access import fetch_gift_sync
from src.validation import GiftLinkError, parse_gift_link
from src.web.rate_limit import RateLimiter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("gift-bot")

_hist_limiter: RateLimiter | None = None


def _get_hist_limiter() -> RateLimiter:
    global _hist_limiter
    if _hist_limiter is None:
        settings = get_settings()
        _hist_limiter = RateLimiter(
            max_requests=settings.bot_rate_limit_requests,
            window_seconds=settings.bot_rate_limit_window,
        )
    return _hist_limiter


def _strip_html(text: str) -> str:
    plain = re.sub(r'<tg-emoji emoji-id="\d+">(.+?)</tg-emoji>', r"\1", text)
    return re.sub(r"<[^>]+>", "", plain)


async def _send_html(message, text: str) -> None:
    try:
        await message.reply_text(text, parse_mode=ParseMode.HTML)
    except BadRequest as exc:
        if "entity" not in str(exc).lower():
            raise
        log.warning("HTML send failed, fallback to plain: %s", exc)
        await message.reply_text(_strip_html(text))


async def _edit_html(message, text: str, reply_markup=None) -> None:
    try:
        await message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    except BadRequest as exc:
        if "entity" not in str(exc).lower():
            raise
        log.warning("HTML edit failed, fallback to plain: %s", exc)
        await message.edit_text(_strip_html(text), reply_markup=reply_markup)


def _gift_page_keyboard(slug: str, web_base_url: str) -> InlineKeyboardMarkup:
    page_url = f"{web_base_url.rstrip('/')}/gift/{slug}"
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text="🌐 lostgifts.ru", url=page_url)]]
    )


def _extract_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str | None:
    if context.args:
        return " ".join(context.args)
    text = (update.message.text or "").strip()
    for word in text.split():
        if "t.me/nft/" in word or re.search(r"^[A-Za-z][A-Za-z0-9]*-\d+$", word):
            return word
    return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = get_settings()
    site = settings.web_base_url.rstrip("/")
    await _send_html(
        update.message,
        f"{e.e(e.GIFT, '🎁')} <b>Lost Gifts</b>\n\n"
        f"{e.e(e.INTERNET, '🌐')} Сайт: <a href=\"{site}\">{e.esc(site)}</a>\n\n"
        f"{e.e(e.MENU, '📋')} Команды:\n"
        f"{e.e(e.SLASH, '💬')} <code>/hist</code> {e.e(e.LINK, '🔗')} "
        f"— история подарка\n"
        f"{e.e(e.SLASH, '💬')} <code>/web</code> {e.e(e.INTERNET, '🌐')} "
        f"— ссылка на web-страницу\n\n"
        f"{e.e(e.INFO, 'ℹ️')} Пример:\n"
        f"<code>/hist https://t.me/nft/PlushPepe-1</code>",
    )


async def hist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    link = _extract_link(update, context)
    if not link:
        await _send_html(
            update.message,
            f"{e.e(e.EXCLAMATION, '❗')} Укажи ссылку на подарок.\n\n"
            f"{e.e(e.QUESTION, '❓')} Пример:\n"
            f"<code>/hist https://t.me/nft/PlushPepe-1</code>",
        )
        return

    user = update.effective_user
    user_key = str(user.id) if user else "unknown"
    if not _get_hist_limiter().allow(user_key):
        await _send_html(
            update.message,
            f"{e.e(e.EXCLAMATION, '❗')} Слишком много запросов. Подожди минуту.",
        )
        return

    loading = await update.message.reply_text("⚡ Загружаю подарок…")
    settings = get_settings()

    try:
        parsed = parse_gift_link(link)
        result = await asyncio.to_thread(fetch_gift_sync, parsed.url)
        await log_bot_request(
            telegram_user_id=update.effective_user.id if update.effective_user else 0,
            username=(update.effective_user.username or "") if update.effective_user else "",
            input_value=link,
            slug=parsed.slug,
        )
        text = format_transfer_chain_html(result)
        if len(text) > 4000:
            text = text[:3990] + "\n…(обрезано)"
        keyboard = _gift_page_keyboard(parsed.slug, settings.web_base_url)
        await _edit_html(loading, text, reply_markup=keyboard)
    except GiftLinkError as exc:
        await _edit_html(
            loading,
            f"{e.e(e.EXCLAMATION, '❗')} {e.e(e.LINK, '🔗')} {e.esc(str(exc))}",
        )
    except Exception:
        log.exception("hist command failed")
        await _edit_html(
            loading,
            f"{e.e(e.EXCLAMATION, '❗')} Не удалось загрузить данные. Попробуй позже.",
        )


async def web(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    link = _extract_link(update, context)
    if not link:
        await _send_html(
            update.message,
            f"{e.e(e.EXCLAMATION, '❗')} Укажи ссылку на подарок.\n\n"
            f"{e.e(e.QUESTION, '❓')} Пример:\n"
            f"<code>/web https://t.me/nft/PlushPepe-1</code>",
        )
        return

    settings = get_settings()

    try:
        parsed = parse_gift_link(link)
        page_url = f"{settings.web_base_url}/gift/{parsed.slug}"
        await _send_html(
            update.message,
            f"{e.e(e.INTERNET, '🌐')} {e.e(e.SHARE, '📤')} HTML-страница:\n"
            f"{e.e(e.LINK, '🔗')} <a href=\"{page_url}\">{e.esc(page_url)}</a>",
        )
    except GiftLinkError as exc:
        await _send_html(
            update.message,
            f"{e.e(e.EXCLAMATION, '❗')} {e.e(e.LINK, '🔗')} {e.esc(str(exc))}",
        )


async def _post_init(app: Application) -> None:
    await app.bot.set_my_commands(
        [
            ("start", "Справка"),
            ("hist", "История подарка по ссылке"),
            ("web", "HTML-страница с историей"),
        ]
    )


def main() -> None:
    settings = get_settings()
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN не задан в .env")

    app = (
        Application.builder()
        .token(settings.bot_token)
        .post_init(_post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("hist", hist))
    app.add_handler(CommandHandler("web", web))

    log.info("Bot starting…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
