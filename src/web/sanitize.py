from __future__ import annotations

from src.fragment_links import FragmentGiftLinks
from src.models import GiftQueryResult, GiftSnapshot, TransferEvent
from src.web.security import safe_external_url


def _safe_or_empty(url: str) -> str:
    return safe_external_url(url)


def _sanitize_metadata(metadata: dict | None) -> dict | None:
    if not metadata:
        return metadata
    clean = dict(metadata)
    for key in ("image", "lottie", "webp", "url", "content_url"):
        if key in clean and isinstance(clean[key], str):
            clean[key] = _safe_or_empty(clean[key])
    return clean


def sanitize_snapshot(snapshot: GiftSnapshot) -> GiftSnapshot:
    snapshot.owner_photo = _safe_or_empty(snapshot.owner_photo)
    snapshot.og_image = _safe_or_empty(snapshot.og_image)
    snapshot.owner = (snapshot.owner or "")[:256]
    snapshot.name = (snapshot.name or "")[:128]
    return snapshot


def sanitize_transfer_event(event: TransferEvent) -> TransferEvent:
    event.owner_photo = _safe_or_empty(event.owner_photo)
    event.from_owner = (event.from_owner or "")[:256]
    event.to_owner = (event.to_owner or "")[:256]
    return event


def sanitize_fragment_links(fragment: FragmentGiftLinks) -> FragmentGiftLinks:
    metadata = _sanitize_metadata(fragment.metadata)
    webp = _safe_or_empty(fragment.fragment_webp)
    lottie = _safe_or_empty(fragment.fragment_lottie)
    if metadata:
        if metadata.get("image"):
            webp = metadata["image"]
        if metadata.get("lottie"):
            lottie = metadata["lottie"]
    return FragmentGiftLinks(
        slug=fragment.slug,
        fragment_slug=fragment.fragment_slug,
        telegram_url=_safe_or_empty(fragment.telegram_url),
        fragment_json=_safe_or_empty(fragment.fragment_json),
        fragment_webp=webp,
        fragment_lottie=lottie,
        metadata=metadata,
    )


def sanitize_gift_result(result: GiftQueryResult) -> GiftQueryResult:
    result.snapshot = sanitize_snapshot(result.snapshot)
    result.history = [sanitize_transfer_event(event) for event in result.history]
    return result
