from __future__ import annotations

import hashlib
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from src.models import GiftSnapshot
from src.validation import parse_gift_link
from src.web.security import safe_external_url

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HTTP_HEADERS = {"User-Agent": USER_AGENT}


class TelegramGiftScraper:
    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = timeout
        self._async_client: httpx.AsyncClient | None = None
        self._sync_client: httpx.Client | None = None

    def _async_http(self) -> httpx.AsyncClient:
        if self._async_client is None or self._async_client.is_closed:
            self._async_client = httpx.AsyncClient(
                timeout=self._timeout,
                headers=HTTP_HEADERS,
                follow_redirects=True,
            )
        return self._async_client

    def _sync_http(self) -> httpx.Client:
        if self._sync_client is None or self._sync_client.is_closed:
            self._sync_client = httpx.Client(
                timeout=self._timeout,
                headers=HTTP_HEADERS,
                follow_redirects=True,
            )
        return self._sync_client

    async def aclose(self) -> None:
        if self._async_client and not self._async_client.is_closed:
            await self._async_client.aclose()
        self._async_client = None

    def close(self) -> None:
        if self._sync_client and not self._sync_client.is_closed:
            self._sync_client.close()
        self._sync_client = None

    async def fetch(self, link_or_slug: str) -> GiftSnapshot:
        parsed = parse_gift_link(link_or_slug)
        response = await self._async_http().get(parsed.url)
        response.raise_for_status()
        return self._parse_html(parsed.slug, response.text, response.text)

    def fetch_sync(self, link_or_slug: str) -> GiftSnapshot:
        parsed = parse_gift_link(link_or_slug)
        response = self._sync_http().get(parsed.url)
        response.raise_for_status()
        return self._parse_html(parsed.slug, response.text, response.text)

    def _parse_html(self, slug: str, html: str, raw: str) -> GiftSnapshot:
        soup = BeautifulSoup(html, "html.parser")

        title = soup.find("meta", property="og:title")
        name = title["content"].split("#")[0].strip() if title and title.get("content") else slug.rsplit("-", 1)[0]
        number_match = re.search(r"#(\d+)", title["content"]) if title and title.get("content") else None
        number = number_match.group(1) if number_match else slug.rsplit("-", 1)[-1]

        og_image_tag = soup.find("meta", property="og:image")
        og_image = og_image_tag["content"] if og_image_tag and og_image_tag.get("content") else ""

        table_data = self._parse_table(soup)
        owner_photo = self._extract_owner_photo(soup)

        snapshot = GiftSnapshot(
            slug=slug,
            name=name,
            number=number,
            owner=table_data.get("owner", ""),
            owner_photo=safe_external_url(owner_photo),
            model=table_data.get("model", ""),
            backdrop=table_data.get("backdrop", ""),
            symbol=table_data.get("symbol", ""),
            quantity=table_data.get("quantity", ""),
            og_image=safe_external_url(og_image),
        )
        snapshot.response_hash = hashlib.sha256(raw.encode()).hexdigest()
        return snapshot

    @staticmethod
    def _parse_table(soup: BeautifulSoup) -> dict[str, str]:
        result: dict[str, str] = {}
        table = soup.select_one("table.tgme_gift_table")
        if not table:
            return result

        for row in table.select("tr"):
            header = row.find("th")
            cell = row.find("td")
            if not header or not cell:
                continue
            key = header.get_text(strip=True).lower()
            value = cell.get_text(" ", strip=True)
            value = re.sub(r"\s+", " ", value)
            result[key] = value
        return result

    @staticmethod
    def _extract_owner_photo(soup: BeautifulSoup) -> str:
        photo = soup.select_one("i.tgme_gift_owner_photo img")
        if photo and photo.get("src"):
            return photo["src"]
        return ""


def diff_snapshots(old: GiftSnapshot | None, new: GiftSnapshot) -> dict[str, Any]:
    if old is None:
        return {"initial": True, "owner": new.owner}

    changes: dict[str, Any] = {}
    for field in ("owner", "model", "backdrop", "symbol", "quantity"):
        old_val = getattr(old, field, "")
        new_val = getattr(new, field, "")
        if old_val != new_val:
            changes[field] = {"from": old_val, "to": new_val}
    return changes
