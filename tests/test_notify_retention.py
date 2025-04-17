from datetime import UTC, datetime, timedelta

from email_agent.alerts import AlertLevel, AlertService, AlertType
from email_agent.core.events import EventBus
from email_agent.store import EmailStatus


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


def test_prune_removes_only_old_finished_emails(store):
    old = (datetime.now(UTC) - timedelta(days=100)).isoformat(timespec="seconds")
    new = datetime.now(UTC).isoformat(timespec="seconds")
    a = store.add_email(
        source="t",
        message_id="old-done",
        received_at=old,
        from_addr="",
        subject="",
        raw=b"",
        body_text="",
    )
    b = store.add_email(
        source="t",
        message_id="old-queued",
        received_at=old,
        from_addr="",
        subject="",
        raw=b"",
        body_text="",
    )
    c = store.add_email(
        source="t",
        message_id="new-done",
        received_at=new,
        from_addr="",
        subject="",
        raw=b"",
        body_text="",
    )
    store.set_status(a, EmailStatus.DONE)
    store.set_status(c, EmailStatus.DONE)
    # retention counts from when processing finished, so backdate a's updated_at
    with store._tx() as conn:
        conn.execute("UPDATE emails SET updated_at=? WHERE id=?", (old, a))
    store.add_analysis(a, "urgency", {"x": 1})
    store.add_alert(email_id=a, type="urgency", level="high", message="m", details={})
    assert store.prune(older_than_days=0) == {"emails": 0}
    assert store.prune(older_than_days=90) == {"emails": 1}
    assert store.get_email(a) is None and store.get_email(b) and store.get_email(c)
    assert store.analyses_for(a) == []
    assert store.list_alerts()[0].email_id is None  # FK set null, alert history kept
