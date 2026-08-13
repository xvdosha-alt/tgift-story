from __future__ import annotations

import hashlib
import hmac


def constant_time_compare(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return hmac.compare_digest(
        hashlib.sha256(left.encode("utf-8")).digest(),
        hashlib.sha256(right.encode("utf-8")).digest(),
    )
