"""Optional local SMTP listener so other tools can pipe mail in directly."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from aiosmtpd.controller import Controller

from ..core.events import EventBus
from ..store import Store
from .parse import parse_raw

log = logging.getLogger(__name__)


class _Handler:
    def __init__(self, store: Store, bus: EventBus) -> None:
        self.store = store
        self.bus = bus

    async def handle_DATA(self, server, session, envelope):  # noqa: N802 - aiosmtpd API
        raw: bytes = envelope.content
        digest = hashlib.sha256(raw).hexdigest()[:24]
        parsed = parse_raw(raw)
        eid = self.store.add_email(
            source="smtp",
            message_id=f"smtp:{digest}",
            received_at=datetime.now(UTC).isoformat(timespec="seconds"),
            from_addr=parsed.from_addr or (envelope.mail_from or ""),
            subject=parsed.subject,
            raw=raw,
            body_text=parsed.body_text,
        )
        if eid:
            self.bus.publish("email", id=eid, status="queued")
            log.info("smtp: queued %s from %s", parsed.subject, parsed.from_addr)
        return "250 OK"


class SmtpListener:
    def __init__(
        self, store: Store, bus: EventBus, *, host: str = "127.0.0.1", port: int = 8025
    ) -> None:
        self._controller = Controller(_Handler(store, bus), hostname=host, port=port)

    def start(self) -> None:
        self._controller.start()
        log.info("SMTP listener on %s:%s", self._controller.hostname, self._controller.port)

    def stop(self) -> None:
        self._controller.stop()
