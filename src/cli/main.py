#!/usr/bin/env python3
from __future__ import annotations

import sys

import click

from src.config import get_settings
from src.gift_access import fetch_gift_sync
from src.history_service import format_transfer_chain
from src.storage.redis_store import GiftStore
from src.validation import GiftLinkError, parse_gift_link


@click.group()
def cli() -> None:
    pass


@cli.command("hist")
@click.argument("link")
def hist(link: str) -> None:
    settings = get_settings()

    try:
        parsed = parse_gift_link(link)
        result = fetch_gift_sync(parsed.url, settings)
        output = format_transfer_chain(result)
        click.echo(output)
    except GiftLinkError as exc:
        click.echo(f"❌ {exc}", err=True)
        sys.exit(1)
    except Exception as exc:
        click.echo(f"❌ Ошибка: {exc}", err=True)
        sys.exit(1)


@cli.command("track")
@click.argument("links", nargs=-1, required=True)
def track(links: tuple[str, ...]) -> None:
    settings = get_settings()
    store = GiftStore(settings.redis_url)
    store.connect_sync()

    try:
        slugs = []
        for link in links:
            parsed = parse_gift_link(link)
            slugs.append(parsed.slug)
            store.ensure_gift_tracked_sync(parsed.slug)
            click.echo(f"✓ {parsed.slug} добавлен в трекинг")
        click.echo(f"\nВсего: {len(slugs)}")
    except GiftLinkError as exc:
        click.echo(f"❌ {exc}", err=True)
        sys.exit(1)
    finally:
        store.close_sync()


if __name__ == "__main__":
    cli()
