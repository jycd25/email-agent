"""OutlookSource.fetch against a fake Graph session: batching, skip, since-filter."""

import base64
from datetime import UTC, datetime

from conftest import SAMPLE_PLAIN
from email_agent.sources.outlook import OutlookSource


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class FakeGraph:
    """Answers /me/messages with a listing and /$batch with base64 MIME bodies."""

    def __init__(self, msgs: dict[str, str], *, base64_bodies: bool = True):
        self.msgs = msgs  # id -> receivedDateTime (Graph form)
        self.headers = {}
        self.list_params = None
        self.batches: list[list[str]] = []
        self.base64_bodies = base64_bodies

    def get(self, url, params=None, timeout=None):
        assert url.endswith("/me/messages")
        self.list_params = params
        return _Resp({"value": [{"id": i, "receivedDateTime": t} for i, t in self.msgs.items()]})

    def post(self, url, json=None, timeout=None):
        assert url.endswith("/$batch")
        ids = [r["id"] for r in json["requests"]]
        self.batches.append(ids)
        body = (
            base64.b64encode(SAMPLE_PLAIN).decode() if self.base64_bodies else SAMPLE_PLAIN.decode()
        )
        return _Resp({"responses": [{"id": i, "status": 200, "body": body} for i in ids]})


def _src(tmp_path, graph):
    s = OutlookSource(tmp_path / "t.json", client_id="cid")
    s._session = graph
    s.authorize = lambda **_: "tok"  # no MSAL in tests
    return s


def test_fetch_uses_one_batch_and_honors_skip_and_since(tmp_path):
    g = FakeGraph(
        {
            "a": "2025-03-03T09:00:00Z",
            "b": "2025-03-03T10:00:00Z",
            "old": "2025-01-01T00:00:00Z",
        }
    )
    out = _src(tmp_path, g).fetch(
        since="2025-03-01T00:00:00+00:00",
        limit=10,
        skip=lambda mid: mid == "outlook:b",
    )
    assert [m.message_id for m in out] == ["outlook:a"]
    assert out[0].raw == SAMPLE_PLAIN
    assert out[0].received_at == "2025-03-03T09:00:00+00:00"
    assert g.batches == [["a", "old"]]
    assert "receivedDateTime ge 2025-03-01T00:00:00Z" in g.list_params["$filter"]
    assert "isRead eq false" in g.list_params["$filter"]
    assert g.headers["Prefer"] == 'IdType="ImmutableId"'


def test_fetch_limit_caps_and_splits_batches_at_twenty(tmp_path):
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    g = FakeGraph({f"m{i}": now for i in range(40)})
    out = _src(tmp_path, g).fetch(since=None, limit=25)
    assert len(out) == 25
    assert [len(b) for b in g.batches] == [20, 5]
    assert "$filter" in g.list_params  # unread-only still applied without `since`


def test_fetch_empty_mailbox_makes_no_batch(tmp_path):
    g = FakeGraph({})
    assert _src(tmp_path, g).fetch(since=None, limit=5) == [] and g.batches == []


def test_plain_text_batch_body_is_accepted(tmp_path):
    g = FakeGraph({"a": "2025-03-03T09:00:00Z"}, base64_bodies=False)
    out = _src(tmp_path, g).fetch(since=None, limit=5)
    assert out[0].raw == SAMPLE_PLAIN


def test_unauthorized_without_client_id(tmp_path):
    s = OutlookSource(tmp_path / "t.json", client_id=None)
    (tmp_path / "t.json").write_text("{}")
    assert not s.is_authorized()
    assert OutlookSource(tmp_path / "t.json", client_id="cid").is_authorized()
