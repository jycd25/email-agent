import asyncio

import pytest

from conftest import SAMPLE_HTML, SAMPLE_PLAIN, FakeLLM
from email_agent.alerts import AlertService
from email_agent.analyzers.topic import TopicCheck
from email_agent.analyzers.urgency import UrgencyCheck
from email_agent.core.config import RuntimeSettings
from email_agent.core.events import EventBus
from email_agent.pipeline import Worker
from email_agent.sources import RawEmail
from email_agent.store import EmailStatus


class FakeSource:
    name = "fake"

    def __init__(self, raws):
        self.raws = raws
        self.fetches = 0

    def fetch(self, *, since, limit, skip=lambda _id: False):
        self.fetches += 1
        return [
            RawEmail(
                source="fake",
                message_id=f"fake:{i}",
                received_at="2025-03-03T09:00:00+00:00",
                raw=r,
            )
            for i, r in enumerate(self.raws)
            if not skip(f"fake:{i}")
        ]


def make_worker(store, llm, raws, **settings):
    bus = EventBus()
    s = RuntimeSettings(
        watchlist_topics=["Production incident"], **settings
    )
    src = FakeSource(raws)
    w = Worker(
        store,
        bus,
        AlertService(store, bus),
        settings=lambda: s,
        llm_factory=lambda _: llm,
        sources=[src],
    )
    return w, src, bus


async def test_tick_fetches_and_processes_everything(store):
    llm = FakeLLM(
        {
            UrgencyCheck: UrgencyCheck(urgency_level="urgent", confidence_score=0.9),
            TopicCheck: TopicCheck(
                topic="Production incident", similarity_score=0.9, confidence_score=0.9
            ),
        }
    )
    w, src, bus = make_worker(store, llm, [SAMPLE_PLAIN, SAMPLE_HTML])
    bus.bind(asyncio.get_running_loop())
    out = await w.tick()
    assert (out["fetched"], out["processed"]) == (2, 2)
    assert store.queue_stats()["done"] == 2
    kinds = {a.kind for a in store.analyses_for(1)}
    assert kinds == {"sender", "urgency", "topic"}
    alerts = store.list_alerts()
    assert {a.type for a in alerts} == {"urgency", "topic"}
    assert any(a.level == "critical" for a in alerts)
    # second tick: dedup via skip(), nothing new
    again = await w.tick()
    assert (again["fetched"], again["processed"]) == (0, 0)
    assert src.fetches == 2


async def test_blocked_sender_short_circuits(store, fake_llm):
    store.upsert_rule("alerts@pagerduty.com", "blocked")
    w, _, bus = make_worker(store, fake_llm, [SAMPLE_HTML])
    bus.bind(asyncio.get_running_loop())
    await w.tick()
    assert [a.kind for a in store.analyses_for(1)] == ["sender"]
    assert store.list_alerts()[0].type == "sender" and store.list_alerts()[0].level == "high"
    assert fake_llm.calls == []


async def test_failure_retries_then_fails(store):
    class Boom:
        def structured(self, *a, **k):
            raise RuntimeError("model exploded")

        def text(self, *a, **k):
            raise RuntimeError("model exploded")

    w, _, bus = make_worker(store, Boom(), [SAMPLE_PLAIN], max_attempts=2, analyze_sender=False)
    bus.bind(asyncio.get_running_loop())
    await w.tick()
    e = store.get_email(1)
    assert e.status == EmailStatus.QUEUED and e.attempts == 1 and "exploded" in e.error
    await w.tick()
    e = store.get_email(1)
    assert e.status == EmailStatus.FAILED and e.attempts == 2
    assert any("Gave up" in a.message for a in store.list_alerts())


async def test_no_model_marks_failed_not_crash(store):
    w, _, bus = make_worker(store, None, [SAMPLE_PLAIN], max_attempts=1, analyze_sender=False)
    bus.bind(asyncio.get_running_loop())
    await w.tick()
    assert store.get_email(1).status == EmailStatus.FAILED


async def test_events_are_published(store, fake_llm):
    w, _, bus = make_worker(store, fake_llm, [SAMPLE_PLAIN])
    bus.bind(asyncio.get_running_loop())
    seen = []

    async def listen():
        async for ev in bus.subscribe():
            seen.append(ev)
            if ev.get("status") == "done":
                break

    t = asyncio.create_task(listen())
    await asyncio.sleep(0)
    await w.tick()
    await asyncio.wait_for(t, 2)
    assert [e["status"] for e in seen if e["type"] == "email"] == ["queued", "processing", "done"]


@pytest.mark.parametrize("bad", [b"", b"garbage without headers"])
async def test_unparseable_mail_still_flows(store, fake_llm, bad):
    w, _, bus = make_worker(store, fake_llm, [bad], analyze_sender=False)
    bus.bind(asyncio.get_running_loop())
    await w.tick()
    assert store.get_email(1).status == EmailStatus.DONE


async def test_run_loop_survives_tick_exception(store, fake_llm, monkeypatch):
    w, _, bus = make_worker(store, fake_llm, [SAMPLE_PLAIN])
    bus.bind(asyncio.get_running_loop())
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            w.wake()  # arrives mid-tick; must trigger the next tick immediately
            raise RuntimeError("boom")
        w.stop()
        return {"fetched": 0, "processed": 0}

    monkeypatch.setattr(w, "tick", flaky)
    await asyncio.wait_for(w.run(), 2)
    assert calls["n"] == 2
    assert any("Worker error: boom" in a.message for a in store.list_alerts())


async def test_fetch_error_of_any_kind_is_reported_not_fatal(store, fake_llm):
    class Bad:
        name = "bad"

        def fetch(self, **k):
            raise KeyError("token expired")

    w, _, bus = make_worker(store, fake_llm, [])
    w.sources = [Bad()]
    bus.bind(asyncio.get_running_loop())
    await w.tick()
    assert "token expired" in (w.last_fetch_error or "")
    assert store.list_alerts()[0].type == "system"


def test_clip_keeps_head_and_tail():
    from email_agent.pipeline.worker import clip

    text = "H" * 5000 + "M" * 5000 + "T" * 5000
    out = clip(text, 1000)
    assert (
        len(out) < 1100 and out.startswith("H" * 800) and out.endswith("T" * 200) and "[...]" in out
    )
    assert clip("short", 1000) == "short"


class _NeedsAuth(FakeSource):
    def is_authorized(self):
        return False


async def test_unauthorized_sources_are_skipped(store):
    """A source that reports itself unauthorized is not polled, and the status
    explains it. Sources without is_authorized() are always polled."""
    s = RuntimeSettings(analyze_urgency=False, analyze_topics=False, analyze_sender=False)
    bus = EventBus()
    locked, open_ = _NeedsAuth([SAMPLE_PLAIN]), FakeSource([SAMPLE_PLAIN])
    w = Worker(
        store,
        bus,
        AlertService(store, bus),
        settings=lambda: s,
        llm_factory=lambda _: FakeLLM(),
        sources=[locked, open_],
    )
    assert w.fetch_all() == 1
    assert locked.fetches == 0 and open_.fetches == 1
    assert w.last_fetch_error is None

    w2 = Worker(
        store,
        bus,
        AlertService(store, bus),
        settings=lambda: s,
        llm_factory=lambda _: FakeLLM(),
        sources=[locked],
    )
    assert w2.fetch_all() == 0
    assert "email-agent auth" in (w2.last_fetch_error or "")
