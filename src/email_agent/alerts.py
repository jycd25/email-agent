from __future__ import annotations

import logging
from collections.abc import Callable
from enum import Enum
from typing import Any

from .core.events import EventBus
from .store import Alert, Store

log = logging.getLogger(__name__)


class AlertLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertType(str, Enum):
    URGENCY = "urgency"
    TOPIC = "topic"
    SENDER = "sender"
    SYSTEM = "system"


LEVEL_ORDER = {AlertLevel.LOW: 0, AlertLevel.MEDIUM: 1, AlertLevel.HIGH: 2, AlertLevel.CRITICAL: 3}


class AlertService:
    def __init__(
        self,
        store: Store,
        bus: EventBus,
        notifier: Callable[[str, str], bool] | None = None,
        *,
        min_notify_level: Callable[[], str] = lambda: "high",
        notifications_enabled: Callable[[], bool] = lambda: False,
    ) -> None:
        self.store = store
        self.bus = bus
        self.notifier = notifier
        self.min_notify_level = min_notify_level
        self.notifications_enabled = notifications_enabled

    def raise_alert(
        self,
        type: AlertType,
        level: AlertLevel,
        message: str,
        *,
        email_id: int | None = None,
        **details: Any,
    ) -> Alert:
        alert = self.store.add_alert(
            email_id=email_id, type=type.value, level=level.value, message=message, details=details
        )
        log.log(_LOG_LEVEL[level], "ALERT [%s/%s] %s", type.value, level.value, message)
        self.bus.publish("alert", alert=alert.model_dump())
        if self.notifier and self.notifications_enabled() and self._notifiable(level):
            self.notifier(f"email-agent: {type.value} {level.value}", message)
        return alert

    def _notifiable(self, level: AlertLevel) -> bool:
        try:
            floor = AlertLevel(self.min_notify_level().lower())
        except ValueError:
            floor = AlertLevel.HIGH
        return LEVEL_ORDER[level] >= LEVEL_ORDER[floor]


_LOG_LEVEL = {
    AlertLevel.LOW: logging.INFO,
    AlertLevel.MEDIUM: logging.INFO,
    AlertLevel.HIGH: logging.WARNING,
    AlertLevel.CRITICAL: logging.ERROR,
}
