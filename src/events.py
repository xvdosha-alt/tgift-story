from __future__ import annotations

from typing import Any

from src.models import GiftSnapshot, TransferEvent


def build_transfer_event(slug: str, snapshot: GiftSnapshot, diff: dict[str, Any]) -> TransferEvent:
    if diff.get("initial"):
        return TransferEvent(
            slug=slug,
            event_type="discovered",
            to_owner=snapshot.owner,
            owner_photo=snapshot.owner_photo,
            snapshot=snapshot.to_dict(),
            diff=diff,
        )

    owner_change = diff.get("owner")
    if isinstance(owner_change, dict):
        event_type = "owner_transfer"
        from_owner = owner_change.get("from", "")
        to_owner = owner_change.get("to", snapshot.owner)
    else:
        event_type = "metadata_change"
        from_owner = ""
        to_owner = snapshot.owner

    return TransferEvent(
        slug=slug,
        event_type=event_type,
        from_owner=from_owner,
        to_owner=to_owner,
        owner_photo=snapshot.owner_photo,
        snapshot=snapshot.to_dict(),
        diff=diff,
    )


def should_record_diff(diff: dict[str, Any], *, is_initial_fetch: bool) -> bool:
    if not diff:
        return False
    if diff.get("initial"):
        return is_initial_fetch
    return True
