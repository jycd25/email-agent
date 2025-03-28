"""Wires everything together. One object owns the store, bus, worker and sources."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from .alerts import AlertService
from .core.config import AppConfig, Provider, RuntimeSettings
from .core.events import EventBus
from .llm import LLM, LLMClient
from .pipeline import Worker
from .sources.gmail import GmailSource
from .store import Store

log = logging.getLogger(__name__)
SETTINGS_KEY = "runtime"


class App:
    def __init__(self, config: AppConfig | None = None, *, store: Store | None = None) -> None:
        self.config = config or AppConfig()
        self.config.ensure_dirs()
        self.store = store or Store(self.config.db_path)
        self.bus = EventBus()
        self.alerts = AlertService(self.store, self.bus)
        self.gmail = GmailSource(self.config.credentials_path, self.config.token_path)
        self.sources = {self.gmail.name: self.gmail}
        self.worker = Worker(
            self.store,
            self.bus,
            self.alerts,
            settings=self.settings,
            llm_factory=lambda st: self.make_llm(st),
            sources=list(self.sources.values()),
        )
        self._worker_task: asyncio.Task | None = None
        self._llm_cache: tuple[tuple, LLM] | None = None

    # -- settings ---------------------------------------------------------

    def settings(self) -> RuntimeSettings:
        data = self.store.get_setting(SETTINGS_KEY) or {}
        return RuntimeSettings.model_validate(data)

    def update_settings(self, patch: dict) -> RuntimeSettings:
        merged = {
            **self.settings().model_dump(mode="json"),
            **{k: v for k, v in patch.items() if not k.startswith("_")},
        }
        s = RuntimeSettings.model_validate(merged)
        self.store.set_setting(SETTINGS_KEY, s.model_dump(mode="json"))
        self.bus.publish("settings", settings=s.model_dump(mode="json"))
        return s

    # -- model ------------------------------------------------------------

    def make_llm(self, s: RuntimeSettings | None = None) -> LLM | None:
        s = s or self.settings()
        key = (s.provider, s.model, s.base_url)
        if self._llm_cache and self._llm_cache[0] == key:
            return self._llm_cache[1]
        try:
            llm = LLMClient(
                s.provider,
                s.model,
                api_key=self.config.openai_api_key,
                base_url=s.base_url if s.provider == Provider.OLLAMA else None,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("model unavailable: %s", e)
            return None
        self._llm_cache = (key, llm)
        return llm

    # -- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        self.bus.bind(asyncio.get_running_loop())
        self._worker_task = asyncio.create_task(self.worker.run(), name="email-agent-worker")
        log.info("worker started (data: %s)", self.config.data_dir)

    async def stop(self) -> None:
        self.worker.stop()
        if self._worker_task:
            self._worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._worker_task
    def status(self) -> dict:
        s = self.settings()
        return {
            "profile": s.profile.value,
            "provider": s.provider.value,
            "model": s.model,
            "gmail_authorized": self.gmail.is_authorized(),
            "queue": self.store.queue_stats(),
            "unread_alerts": self.store.unread_alert_count(),
            "last_fetch_at": self.worker.last_fetch_at,
            "last_fetch_error": self.worker.last_fetch_error,
        }
