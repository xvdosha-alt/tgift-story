from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_datetime(iso: str) -> str:
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")


@dataclass
class GiftSnapshot:
    slug: str
    name: str = ""
    number: str = ""
    owner: str = ""
    owner_photo: str = ""
    model: str = ""
    backdrop: str = ""
    symbol: str = ""
    quantity: str = ""
    og_image: str = ""
    fetched_at: str = field(default_factory=utcnow_iso)
    response_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GiftSnapshot:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def fingerprint(self) -> str:
        payload = {
            "owner": self.owner,
            "model": self.model,
            "backdrop": self.backdrop,
            "symbol": self.symbol,
            "quantity": self.quantity,
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)


@dataclass
class TransferEvent:
    slug: str
    event_type: str
    from_owner: str = ""
    to_owner: str = ""
    owner_photo: str = ""
    snapshot: dict[str, Any] = field(default_factory=dict)
    diff: dict[str, Any] = field(default_factory=dict)
    recorded_at: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransferEvent:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class GiftQueryResult:
    slug: str
    snapshot: GiftSnapshot
    history: list[TransferEvent]
    parse_started_at: str
    fetched_live: bool = False
