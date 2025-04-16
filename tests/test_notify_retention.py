
from email_agent.alerts import AlertLevel, AlertService, AlertType
from email_agent.core.events import EventBus


def test_notifier_respects_floor_and_toggle(store):
    sent = []
    enabled = {"on": True}
    svc = AlertService(
        store,
        EventBus(),
        lambda t, m: sent.append((t, m)) or True,
        min_notify_level=lambda: "high",
        notifications_enabled=lambda: enabled["on"],
    )
    svc.raise_alert(AlertType.SYSTEM, AlertLevel.MEDIUM, "quiet")
    svc.raise_alert(AlertType.URGENCY, AlertLevel.CRITICAL, "loud")
    assert [m for _, m in sent] == ["loud"]
    enabled["on"] = False
    svc.raise_alert(AlertType.URGENCY, AlertLevel.CRITICAL, "muted")
    assert len(sent) == 1
    assert store.unread_alert_count() == 3  # alerts are stored regardless


def test_notifier_failure_does_not_break_alerts(store):
    def boom(t, m):
        raise RuntimeError("no display")

    svc = AlertService(store, EventBus(), boom, notifications_enabled=lambda: True)
    try:
        svc.raise_alert(AlertType.URGENCY, AlertLevel.HIGH, "x")
    except RuntimeError:
        # notify() itself swallows errors; a custom notifier that raises is the caller's problem,
        # but the alert must already be persisted before the notifier runs.
        pass
    assert store.unread_alert_count() == 1
