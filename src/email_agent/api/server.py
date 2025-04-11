from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..agent import EmailAgent
from ..core.config import PROFILE_TOPICS, Profile
from ..core.errors import AnalysisError, ConfigurationError
from ..instruction import parse_instruction
from ..store import EmailStatus

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


class AnalyzeIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=50_000)


class InstructionIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class RuleIn(BaseModel):
    pattern: str = Field(min_length=3, max_length=200)
    category: str
    notes: str | None = None


def create_api(app_ctx) -> FastAPI:
    from ..app import App

    ctx: App = app_ctx

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await ctx.start()
        try:
            yield
        finally:
            await ctx.stop()

    api = FastAPI(title="email-agent", version=__version__, lifespan=lifespan)

    # -- meta -------------------------------------------------------------

    @api.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @api.get("/api/status")
    def status() -> dict[str, Any]:
        return ctx.status()

    @api.post("/api/fetch")
    async def fetch_now() -> dict[str, int]:
        return await ctx.worker.tick()

    # -- emails -----------------------------------------------------------

    @api.get("/api/emails")
    def list_emails(
        status: EmailStatus | None = None,
        q: str | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> list[dict]:
        rows = ctx.store.list_emails(status=status, q=q, limit=limit, offset=offset)
        latest = ctx.store.latest_analyses([r.id for r in rows])
        return [
            {**r.model_dump(), "body_text": r.body_text[:300], "analyses": latest.get(r.id, {})}
            for r in rows
        ]

    @api.get("/api/emails/{email_id}")
    def get_email(email_id: int) -> dict:
        row = ctx.store.get_email(email_id)
        if not row:
            raise HTTPException(404, "email not found")
        return {
            **row.model_dump(),
            "analyses": [a.model_dump() for a in ctx.store.analyses_for(email_id)],
        }

    @api.post("/api/emails/{email_id}/retry")
    def retry(email_id: int) -> dict[str, bool]:
        ok = ctx.store.retry_email(email_id)
        if not ok:
            raise HTTPException(409, "email is not in failed state")
        ctx.worker.wake()
        return {"ok": True}

    # -- ad-hoc analysis --------------------------------------------------

    @api.post("/api/analyze")
    async def analyze(body: AnalyzeIn) -> dict[str, Any]:
        agent = EmailAgent(ctx.store, ctx.settings(), ctx.make_llm(), ctx.selector_client())
        try:
            return await asyncio.to_thread(agent.process, body.prompt)
        except (AnalysisError, ConfigurationError) as e:
            raise HTTPException(503, str(e)) from e

    @api.post("/api/instruction")
    def instruction(body: InstructionIn) -> dict[str, Any]:
        try:
            changes = parse_instruction(body.text)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        sender = changes.pop("_sender", None)
        if sender:
            ctx.store.upsert_rule(sender, "vip", "added from instruction")
        s = ctx.update_settings(changes)
        ctx.worker.wake()
        return {"applied": changes, "settings": s.model_dump(mode="json")}

    # -- alerts -----------------------------------------------------------

    @api.get("/api/alerts")
    def alerts(limit: int = Query(50, ge=1, le=500), unread: bool = False) -> list[dict]:
        return [a.model_dump() for a in ctx.store.list_alerts(limit=limit, unread_only=unread)]

    @api.post("/api/alerts/{alert_id}/read")
    def alert_read(alert_id: int) -> dict[str, bool]:
        if not ctx.store.mark_alert_read(alert_id):
            raise HTTPException(404, "alert not found")
        return {"ok": True}

    @api.post("/api/alerts/read-all")
    def alerts_read_all() -> dict[str, int]:
        return {"updated": ctx.store.mark_all_alerts_read()}

    # -- settings & rules -------------------------------------------------

    @api.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return ctx.settings().model_dump(mode="json")

    @api.put("/api/settings")
    def put_settings(patch: dict[str, Any]) -> dict[str, Any]:
        try:
            s = ctx.update_settings(patch)
        except Exception as e:  # noqa: BLE001 - validation error text is the useful part
            raise HTTPException(422, str(e)) from e
        ctx.worker.wake()
        return s.model_dump(mode="json")

    @api.get("/api/profiles")
    def profiles() -> dict[str, list[str]]:
        return {p.value: PROFILE_TOPICS[p] for p in Profile}

    @api.get("/api/sender-rules")
    def rules() -> list[dict]:
        return [r.model_dump() for r in ctx.store.list_rules()]

    @api.post("/api/sender-rules")
    def add_rule(body: RuleIn) -> dict:
        return ctx.store.upsert_rule(body.pattern, body.category, body.notes).model_dump()

    @api.delete("/api/sender-rules/{pattern:path}")
    def delete_rule(pattern: str) -> dict[str, bool]:
        if not ctx.store.delete_rule(pattern):
            raise HTTPException(404, "rule not found")
        return {"ok": True}

    # -- live events ------------------------------------------------------

    @api.get("/api/events")
    async def events() -> StreamingResponse:
        async def gen():
            yield "event: hello\ndata: {}\n\n"
            async for ev in ctx.bus.subscribe():
                yield f"event: {ev['type']}\ndata: {json.dumps(ev, default=str)}\n\n"

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # -- frontend ---------------------------------------------------------

    if WEB_DIST.exists():
        api.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @api.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            target = WEB_DIST / path
            if path and target.is_file():
                return FileResponse(target)
            return FileResponse(WEB_DIST / "index.html")

    return api
