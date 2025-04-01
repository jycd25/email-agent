"""The single processing loop.

    source.fetch  ->  store (queued)  ->  claim  ->  analyze  ->  store results / alerts

Replaces the two previous, unconnected loops (SMTP directory queue and Gmail
JSON queue). Everything queued gets processed on the next tick; nothing waits
for a restart.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from ..alerts import AlertLevel, AlertService, AlertType
from ..analyzers import SenderAnalyzer, SenderCategory, TopicAnalyzer, UrgencyAnalyzer
from ..analyzers.urgency import exceeds
from ..core.config import RuntimeSettings
from ..core.errors import ConfigurationError, SourceError
from ..core.events import EventBus
from ..llm import LLM
from ..sources import EmailSource, is_authorized, parse_raw
from ..store import EmailRow, EmailStatus, Store

log = logging.getLogger(__name__)

# Local models slow down sharply with long inputs and the signal is almost always
# near the top of an email. Keep the head and a little of the tail.
MAX_CONTENT_CHARS = 6000


def clip(text: str, limit: int = MAX_CONTENT_CHARS) -> str:
    if len(text) <= limit:
        return text
    head, tail = int(limit * 0.8), limit - int(limit * 0.8)
    return text[:head] + "\n[...]\n" + text[-tail:]


SettingsGetter = Callable[[], RuntimeSettings]
LLMFactory = Callable[[RuntimeSettings], LLM | None]


class Worker:
    def __init__(
        self,
        store: Store,
        bus: EventBus,
        alerts: AlertService,
        *,
        settings: SettingsGetter,
        llm_factory: LLMFactory,
        sources: list[EmailSource],
    ) -> None:
        self.store = store
        self.bus = bus
        self.alerts = alerts
        self.settings = settings
        self.llm_factory = llm_factory
        self.sources = sources
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self.last_fetch_error: str | None = None
        self.last_fetch_at: str | None = None

    # -- lifecycle --------------------------------------------------------

    async def run(self) -> None:
        requeued = self.store.requeue_stale_processing()
        if requeued:
            log.info("requeued %d interrupted emails", requeued)
        while not self._stop.is_set():
            # Clear before the tick so a wake() that arrives mid-tick is not lost.
            self._wake.clear()
            try:
                await self.tick()
            except Exception as e:  # noqa: BLE001 - the loop must outlive any single failure
                log.exception("tick failed")
                self.alerts.raise_alert(AlertType.SYSTEM, AlertLevel.HIGH, f"Worker error: {e}")
            try:
                await asyncio.wait_for(
                    self._wake.wait(), timeout=self.settings().poll_interval_seconds
                )
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def wake(self) -> None:
        """Run a tick as soon as possible (UI 'check now', new SMTP mail)."""
        self._wake.set()

    # -- one iteration ----------------------------------------------------

    async def tick(self) -> dict[str, int]:
        fetched = await asyncio.to_thread(self.fetch_all)
        processed = await self.process_queue()
        return {"fetched": fetched, "processed": processed}

    def fetch_all(self) -> int:
        s = self.settings()
        added = 0
        active = [src for src in self.sources if is_authorized(src)]
        if not active and self.sources:
            self.last_fetch_error = (
                "No mail account is authorized. Run `email-agent auth gmail` or "
                "`email-agent auth outlook`."
            )
        for src in active:
            try:
                new = src.fetch(
                    since=s.fetch_since, limit=s.batch_size, skip=self.store.has_message
                )
            except ConfigurationError as e:
                self.last_fetch_error = str(e)
                continue
            except Exception as e:  # noqa: BLE001 - auth refresh, network, quota: keep polling
                self.last_fetch_error = str(e)
                level = AlertLevel.HIGH if isinstance(e, SourceError) else AlertLevel.MEDIUM
                log.warning("%s fetch failed: %s", src.name, e)
                self.alerts.raise_alert(AlertType.SYSTEM, level, f"{src.name}: {e}")
                continue
            self.last_fetch_error = None
            for m in new:
                p = parse_raw(m.raw)
                eid = self.store.add_email(
                    source=m.source,
                    message_id=m.message_id,
                    received_at=m.received_at,
                    from_addr=p.from_addr,
                    subject=p.subject,
                    raw=m.raw,
                    body_text=p.body_text,
                )
                if eid:
                    added += 1
                    self.bus.publish("email", id=eid, status="queued")
        from ..store.db import utcnow

        self.last_fetch_at = utcnow()
        if added:
            log.info("fetched %d new emails", added)
        return added

    async def process_queue(self) -> int:
        s = self.settings()
        llm = self.llm_factory(s)
        rules = self.store.list_rules() if s.analyze_sender else []
        count = 0
        seen: set[int] = set()
        while not self._stop.is_set():
            batch = self.store.claim_queued(s.batch_size, exclude=seen)
            if not batch:
                break
            for row in batch:
                seen.add(row.id)
                self.bus.publish("email", id=row.id, status="processing")
                try:
                    await asyncio.to_thread(self.process_one, row, s, llm, rules)
                    self.store.set_status(row.id, EmailStatus.DONE)
                    self.bus.publish("email", id=row.id, status="done")
                    count += 1
                except Exception as e:  # noqa: BLE001 - one bad email must not stop the loop
                    log.exception("processing email %s failed", row.id)
                    if row.attempts >= s.max_attempts:
                        self.store.set_status(row.id, EmailStatus.FAILED, str(e))
                        self.bus.publish("email", id=row.id, status="failed")
                        self.alerts.raise_alert(
                            AlertType.SYSTEM,
                            AlertLevel.MEDIUM,
                            f"Gave up on '{row.subject}' after {row.attempts} attempts",
                            email_id=row.id,
                            error=str(e),
                        )
                    else:
                        self.store.set_status(row.id, EmailStatus.QUEUED, str(e))
                        self.bus.publish("email", id=row.id, status="queued")
            if self._stop.is_set():
                break
        return count

    # -- analysis of one email -------------------------------------------

    def process_one(
        self, row: EmailRow, s: RuntimeSettings, llm: LLM | None, rules: list | None = None
    ) -> dict[str, Any]:
        content = f"Subject: {row.subject}\nFrom: {row.from_addr}\n\n{clip(row.body_text)}"
        results: dict[str, Any] = {}

        if s.analyze_sender and row.from_addr:
            sa = SenderAnalyzer(self.store, llm, mode=s.sender_mode, profile=s.profile, rules=rules)
            r = sa.analyze(row.from_addr, row.body_text[:1500])
            results["sender"] = r.model_dump()
            self.store.add_analysis(row.id, "sender", results["sender"])
            if r.is_blocked:
                self.alerts.raise_alert(
                    AlertType.SENDER,
                    AlertLevel.HIGH,
                    f"Blocked sender: {row.from_addr}",
                    email_id=row.id,
                    category=r.category.value,
                    subject=row.subject,
                )
            elif r.category == SenderCategory.VIP:
                self.alerts.raise_alert(
                    AlertType.SENDER,
                    AlertLevel.MEDIUM,
                    f"VIP sender: {row.from_addr}",
                    email_id=row.id,
                    category=r.category.value,
                    subject=row.subject,
                )
            elif r.category == SenderCategory.UNKNOWN and s.alert_on_unknown_sender:
                self.alerts.raise_alert(
                    AlertType.SENDER,
                    AlertLevel.LOW,
                    f"Unknown sender: {row.from_addr}",
                    email_id=row.id,
                    subject=row.subject,
                )
            if r.is_blocked:
                return results  # do not spend model calls on blocked mail

        if llm is None:
            raise ConfigurationError("no model configured; cannot analyze content")

        if s.analyze_urgency:
            r = UrgencyAnalyzer(llm, s.profile).analyze(
                content, threshold=s.urgency_threshold, min_confidence=s.min_confidence
            )
            results["urgency"] = r.model_dump()
            self.store.add_analysis(row.id, "urgency", results["urgency"])
            if (
                exceeds(r.urgency_level, s.urgency_threshold)
                and r.confidence_score >= s.min_confidence
            ):
                level = AlertLevel.CRITICAL if r.urgency_level == "urgent" else AlertLevel.HIGH
                self.alerts.raise_alert(
                    AlertType.URGENCY,
                    level,
                    f"{r.urgency_level.upper()}: {r.summary}",
                    email_id=row.id,
                    subject=row.subject,
                    from_addr=row.from_addr,
                    deadline=r.deadline,
                    keywords=r.keywords_detected,
                )

        if s.analyze_topics and s.watchlist_topics:
            r = TopicAnalyzer(llm, s.watchlist_topics, s.profile).analyze(
                content, threshold=s.topic_threshold
            )
            results["topic"] = r.model_dump()
            self.store.add_analysis(row.id, "topic", results["topic"])
            if r.is_watchlist_topic and r.confidence_score >= s.min_confidence:
                self.alerts.raise_alert(
                    AlertType.TOPIC,
                    AlertLevel.HIGH,
                    f"Watchlist: {r.primary_topic}",
                    email_id=row.id,
                    subject=row.subject,
                    from_addr=row.from_addr,
                    summary=r.message_summary,
                    score=r.similarity_score,
                )

        return results
