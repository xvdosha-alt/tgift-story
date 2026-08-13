from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

FRAGMENT_GIFT_BASE = "https://nft.fragment.com/gift"
TELEGRAM_NFT_BASE = "https://t.me/nft"


@dataclass(frozen=True)
class FragmentGiftLinks:
    slug: str
    fragment_slug: str
    telegram_url: str
    fragment_json: str
    fragment_webp: str
    fragment_lottie: str
    metadata: dict[str, Any] | None = None

    @property
    def name(self) -> str:
        if self.metadata and self.metadata.get("name"):
            return str(self.metadata["name"])
        return self.slug

    @property
    def description(self) -> str:
        if self.metadata and self.metadata.get("description"):
            return str(self.metadata["description"])
        return ""

    @property
    def lottie_url(self) -> str:
        if self.metadata and self.metadata.get("lottie"):
            return str(self.metadata["lottie"])
        return self.fragment_lottie


def fragment_slug_from_telegram(slug: str) -> str:
    return slug.lower()


def build_fragment_links(slug: str) -> FragmentGiftLinks:
    fragment_slug = fragment_slug_from_telegram(slug)
    return FragmentGiftLinks(
        slug=slug,
        fragment_slug=fragment_slug,
        telegram_url=f"{TELEGRAM_NFT_BASE}/{slug}",
        fragment_json=f"{FRAGMENT_GIFT_BASE}/{fragment_slug}.json",
        fragment_webp=f"{FRAGMENT_GIFT_BASE}/{fragment_slug}.webp",
        fragment_lottie=f"{FRAGMENT_GIFT_BASE}/{fragment_slug}.lottie.json",
    )


def fetch_fragment_metadata(slug: str, timeout: float = 10.0) -> FragmentGiftLinks:
    links = build_fragment_links(slug)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(links.fragment_json)
            if response.status_code == 200:
                metadata = response.json()
                return FragmentGiftLinks(
                    slug=slug,
                    fragment_slug=links.fragment_slug,
                    telegram_url=links.telegram_url,
                    fragment_json=links.fragment_json,
                    fragment_webp=str(metadata.get("image", links.fragment_webp)),
                    fragment_lottie=str(metadata.get("lottie", links.fragment_lottie)),
                    metadata=metadata,
                )
    except (httpx.HTTPError, json.JSONDecodeError):
        pass
    return links
