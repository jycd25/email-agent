"""GmailSource.fetch against a fake API client: batching, skip, since-filter."""

import base64
from datetime import UTC, datetime

from conftest import SAMPLE_PLAIN
from email_agent.sources.gmail import GmailSource


class _Req:
    def __init__(self, result):
        self._r = result

    def execute(self):
        return self._r


class _Batch:
    def __init__(self, cb):
        self.cb = cb
        self.items = []

    def add(self, req, request_id):
        self.items.append((request_id, req))

    def execute(self):
        for rid, req in self.items:
            self.cb(rid, req.execute(), None)


class FakeService:
    def __init__(self, msgs: dict[str, int]):
        # id -> internalDate (ms)
        self.msgs = msgs
        self.gets = 0
        self.batches = 0

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, **kw):
        return _Req({"messages": [{"id": i} for i in self.msgs]})

    def get(self, *, userId, id, format):
        self.gets += 1
        return _Req(
            {
                "id": id,
                "internalDate": str(self.msgs[id]),
                "raw": base64.urlsafe_b64encode(SAMPLE_PLAIN).decode(),
            }
        )

    def new_batch_http_request(self, callback):
        self.batches += 1
        return _Batch(callback)


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def test_fetch_uses_one_batch_and_honors_skip_and_since(tmp_path):
    svc = FakeService(
        {
            "a": _ms("2025-03-03T09:00:00+00:00"),
            "b": _ms("2025-03-03T10:00:00+00:00"),
            "old": _ms("2025-01-01T00:00:00+00:00"),
        }
    )
    g = GmailSource(tmp_path / "c.json", tmp_path / "t.json")
    g._service = svc
    out = g.fetch(
        since="2025-03-01T00:00:00+00:00",
        limit=10,
        skip=lambda mid: mid == "gmail:b",  # store-form ids, as the worker passes
    )
    assert [m.message_id for m in out] == ["gmail:a"]
    assert out[0].raw == SAMPLE_PLAIN
    assert out[0].received_at == "2025-03-03T09:00:00+00:00"
    assert svc.batches == 1 and svc.gets == 2  # a and old fetched in one batch, b skipped


def test_fetch_limit_caps_batch_size(tmp_path):
    now = int(datetime.now(UTC).timestamp() * 1000)
    svc = FakeService({f"m{i}": now for i in range(30)})
    g = GmailSource(tmp_path / "c.json", tmp_path / "t.json")
    g._service = svc
    out = g.fetch(since=None, limit=5)
    assert len(out) == 5 and svc.gets == 5


def test_fetch_empty_mailbox_makes_no_batch(tmp_path):
    svc = FakeService({})
    g = GmailSource(tmp_path / "c.json", tmp_path / "t.json")
    g._service = svc
    assert g.fetch(since=None, limit=5) == [] and svc.batches == 0
