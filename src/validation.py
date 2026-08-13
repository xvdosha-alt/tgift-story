import re
from dataclasses import dataclass

GIFT_LINK_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?t\.me/nft/(?P<slug>[A-Za-z][A-Za-z0-9]*-\d+)$",
    re.IGNORECASE,
)
GIFT_SLUG_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*-\d+$")
MAX_LINK_LEN = 256
MAX_SLUG_LEN = 128


@dataclass(frozen=True)
class ParsedGiftLink:
    slug: str
    url: str


class GiftLinkError(ValueError):
    pass


def parse_gift_link(raw: str) -> ParsedGiftLink:
    text = raw.strip()
    if not text:
        raise GiftLinkError("Пустая ссылка")
    if len(text) > MAX_LINK_LEN:
        raise GiftLinkError("Ссылка слишком длинная")

    match = GIFT_LINK_RE.match(text)
    if match:
        slug = match.group("slug")
        if len(slug) > MAX_SLUG_LEN:
            raise GiftLinkError("Невалидная ссылка")
        return ParsedGiftLink(slug=slug, url=f"https://t.me/nft/{slug}")

    if GIFT_SLUG_RE.match(text):
        if len(text) > MAX_SLUG_LEN:
            raise GiftLinkError("Невалидная ссылка")
        return ParsedGiftLink(slug=text, url=f"https://t.me/nft/{text}")

    raise GiftLinkError(
        "Невалидная ссылка. Пример: https://t.me/nft/PlushPepe-1 или PlushPepe-1"
    )
