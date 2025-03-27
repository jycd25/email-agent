from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class RawEmail:
    source: str
    message_id: str
    received_at: str  # ISO 8601
    raw: bytes  # RFC 822 bytes


class EmailSource(Protocol):
    name: str

    def fetch(self, *, since: str | None, limit: int) -> list[RawEmail]:
        """Return new messages. Implementations must be safe to call repeatedly."""
        ...


def is_authorized(source: object) -> bool:
    """Sources that need a sign-in expose `is_authorized()`; others are always on."""
    check = getattr(source, "is_authorized", None)
    return True if check is None else bool(check())
