import pytest
from httpx import ASGITransport, AsyncClient

from conftest import SAMPLE_PLAIN, FakeLLM
from email_agent.api import create_api
from email_agent.app import App
from email_agent.store import EmailStatus


@pytest.fixture
async def client(config, monkeypatch):
    ctx = App(config)
    llm = FakeLLM()
    monkeypatch.setattr(ctx, "make_llm", lambda s=None: llm)
    ctx.worker.sources = []  # no Gmail in tests
    api = create_api(ctx)
    async with api.router.lifespan_context(api):
        # Only explicit ticks in tests: stop the background loop but keep the worker usable.
        ctx._worker_task.cancel()
        async with AsyncClient(transport=ASGITransport(app=api), base_url="http://t") as c:
            c.ctx = ctx
            yield c


async def test_health_and_status(client):
    assert (await client.get("/api/health")).json()["status"] == "ok"
    s = (await client.get("/api/status")).json()
    assert s["gmail_authorized"] is False and s["queue"]["total"] == 0


async def test_settings_roundtrip_and_validation(client):
    r = await client.put("/api/settings", json={"profile": "student", "topic_threshold": 0.4})
    assert r.status_code == 200 and r.json()["profile"] == "student"
    assert (await client.get("/api/settings")).json()["topic_threshold"] == 0.4
    assert (await client.put("/api/settings", json={"topic_threshold": 5})).status_code == 422


async def test_profiles(client):
    p = (await client.get("/api/profiles")).json()
    assert "Assignment deadline" in p["student"] and "Production incident" in p["oncall"]


async def test_emails_flow(client):
    st = client.ctx.store
    eid = st.add_email(
        source="t",
        message_id="m1",
        received_at="2025-01-01T00:00:00+00:00",
        from_addr="a@b.c",
        subject="hi",
        raw=SAMPLE_PLAIN,
        body_text="x" * 500,
    )
    r = await client.post("/api/fetch")
    assert r.json()["processed"] == 1
    lst = (await client.get("/api/emails")).json()
    assert (
        lst[0]["status"] == "done"
        and len(lst[0]["body_text"]) == 300
        and "urgency" in lst[0]["analyses"]
    )
    one = (await client.get(f"/api/emails/{eid}")).json()
    assert {a["kind"] for a in one["analyses"]} >= {"urgency", "sender"}
    assert (await client.get("/api/emails/999")).status_code == 404
    assert (await client.post(f"/api/emails/{eid}/retry")).status_code == 409
    st.set_status(eid, EmailStatus.FAILED, "x")
    assert (await client.post(f"/api/emails/{eid}/retry")).json() == {"ok": True}


async def test_analyze_endpoint(client):
    r = await client.post("/api/analyze", json={"prompt": "is this urgent: {prod down}"})
    assert r.status_code == 200 and r.json()["tool"] == "analyze_email_urgency"
    assert (await client.post("/api/analyze", json={"prompt": ""})).status_code == 422


async def test_instruction_endpoint_adds_rule(client):
    r = await client.post(
        "/api/instruction", json={"text": "monitor sender boss@corp.com, starting now"}
    )
    assert r.status_code == 200 and r.json()["settings"]["analyze_sender"]
    rules = (await client.get("/api/sender-rules")).json()
    assert rules[0]["pattern"] == "boss@corp.com" and rules[0]["category"] == "vip"
    assert (await client.post("/api/instruction", json={"text": "lol"})).status_code == 422


async def test_rules_crud(client):
    r = await client.post("/api/sender-rules", json={"pattern": "*@Spam.io", "category": "blocked"})
    assert r.json()["pattern"] == "*@spam.io"
    assert (await client.delete("/api/sender-rules/*@spam.io")).json() == {"ok": True}
    assert (await client.delete("/api/sender-rules/*@spam.io")).status_code == 404


async def test_alerts_endpoints(client):
    client.ctx.store.add_alert(email_id=None, type="system", level="low", message="m", details={})
    a = (await client.get("/api/alerts?unread=true")).json()
    assert len(a) == 1
    assert (await client.post(f"/api/alerts/{a[0]['id']}/read")).json() == {"ok": True}
    assert (await client.get("/api/alerts?unread=true")).json() == []
    assert (await client.post("/api/alerts/read-all")).json() == {"updated": 0}


def test_events_route_is_registered(config):
    api = create_api(App(config))
    route = next(r for r in api.routes if getattr(r, "path", "") == "/api/events")
    assert "GET" in route.methods


async def test_analyze_reports_unreachable_model_as_503(client, monkeypatch):
    from email_agent.core.errors import AnalysisError

    class Down:
        def structured(self, *a, **k):
            raise AnalysisError(
                "Cannot reach Ollama at http://localhost:11434/v1. Start it with `ollama serve`."
            )

        def text(self, *a, **k):
            raise AnalysisError("down")

    monkeypatch.setattr(client.ctx, "make_llm", lambda s=None: Down())
    r = await client.post("/api/analyze", json={"prompt": "is this urgent: {x}"})
    assert r.status_code == 503 and "ollama serve" in r.json()["detail"]
