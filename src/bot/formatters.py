from __future__ import annotations

from src.bot import emojis as e
from src.history_service import parse_started_notice
from src.models import GiftQueryResult, format_datetime


def format_transfer_chain_html(result: GiftQueryResult) -> str:
    slug = result.slug
    snapshot = result.snapshot
    history = result.history

    lines = [
        f"{e.e(e.GIFT, '🎁')} {e.e(e.STAR, '⭐')} <b>{e.esc(slug)}</b>",
        "",
    ]

    if snapshot:
        lines.extend(
            [
                f"{e.e(e.INFO, 'ℹ️')} <b>{e.esc(snapshot.name)}</b> #{e.esc(snapshot.number)}",
                f"{e.e(e.BIO, '👤')} {e.esc(snapshot.owner or '—')}",
                f"{e.e(e.EDIT, '✏️')} {e.esc(snapshot.model or '—')}",
                f"{e.e(e.SUN, '🎨')} {e.esc(snapshot.backdrop or '—')}",
                f"{e.e(e.STAR, '⭐')} {e.esc(snapshot.symbol or '—')}",
                f"{e.e(e.CHART, '📊')} {e.esc(snapshot.quantity or '—')}",
                "",
            ]
        )

    notice = parse_started_notice(result.parse_started_at)
    lines.append(
        f"{e.e(e.INFO, 'ℹ️')} {e.e(e.SEARCH_DATE, '📅')} "
        f"<i>{e.esc(notice)}</i>"
    )
    if result.fetched_live:
        lines.append(
            f"{e.e(e.SPEED, '⚡')} <i>данные получены вне очереди</i>"
        )
    lines.append("")
    lines.append(
        f"{e.e(e.TRANSFER, '🔁')} {e.e(e.CHART, '📈')} <b>Цепочка передач</b>"
    )

    transfer_events = [
        ev for ev in history if ev.event_type in ("owner_transfer", "discovered")
    ]

    if not transfer_events:
        lines.append("")
        lines.append(
            f"{e.e(e.DATABASE, '💾')} передач пока не зафиксировано"
        )
        if snapshot and snapshot.owner:
            lines.append(
                f"{e.e(e.ARROW_DOWN, '⬇️')} сейчас: <b>{e.esc(snapshot.owner)}</b>"
            )
        return "\n".join(lines)

    lines.append("")
    for event in transfer_events:
        ts = format_datetime(event.recorded_at)
        if event.event_type == "owner_transfer":
            arrow = (
                f"{e.esc(event.from_owner or '?')} → {e.esc(event.to_owner or '?')}"
            )
            lines.append(
                f"{e.e(e.DATE, '📅')} <code>{ts}</code> "
                f"{e.e(e.TRANSFER, '🔁')} {arrow}"
            )
        elif event.event_type == "discovered":
            lines.append(
                f"{e.e(e.DATE, '📅')} <code>{ts}</code> "
                f"{e.e(e.SEARCH, '🔍')} обнаружен → "
                f"<b>{e.esc(event.to_owner or '?')}</b>"
            )

    if snapshot:
        lines.extend(
            [
                "",
                f"{e.e(e.ARROW_DOWN, '⬇️')} сейчас: <b>{e.esc(snapshot.owner)}</b>",
            ]
        )

    return "\n".join(lines)
