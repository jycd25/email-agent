from email_agent.store import EmailStatus, Store


def _add(store: Store, n: int) -> int | None:
    return store.add_email(
        source="t",
        message_id=f"m{n}",
        received_at="2025-01-01T00:00:00+00:00",
        from_addr="a@b.c",
        subject=f"s{n}",
        raw=b"raw",
        body_text="body",
    )


def test_add_is_idempotent(store):
    assert _add(store, 1) == 1
    assert _add(store, 1) is None
    assert store.has_message("m1")
    assert store.queue_stats()["queued"] == 1


def test_claim_moves_to_processing_and_increments_attempts(store):
    for i in range(5):
        _add(store, i)
    batch = store.claim_queued(2)
    assert [e.id for e in batch] == [1, 2]
    assert all(e.status == EmailStatus.PROCESSING and e.attempts == 1 for e in batch)
    assert store.queue_stats() == {"queued": 3, "processing": 2, "done": 0, "failed": 0, "total": 5}
    assert store.claim_queued(10) and store.claim_queued(10) == []


def test_requeue_stale_processing_on_startup(store):
    _add(store, 1)
    store.claim_queued(1)
    assert store.requeue_stale_processing() == 1
    assert store.get_email(1).status == EmailStatus.QUEUED


def test_retry_only_from_failed(store):
    _add(store, 1)
    assert store.retry_email(1) is False
    store.set_status(1, EmailStatus.FAILED, "boom")
    assert store.get_email(1).error == "boom"
    assert store.retry_email(1) is True
    e = store.get_email(1)
    assert e.status == EmailStatus.QUEUED and e.attempts == 0 and e.error is None


def test_analyses_and_latest(store):
    _add(store, 1)
    store.add_analysis(1, "urgency", {"urgency_level": "low"})
    store.add_analysis(1, "urgency", {"urgency_level": "high"})
    assert [a.result["urgency_level"] for a in store.analyses_for(1)] == ["low", "high"]
    assert store.latest_analyses([1])[1]["urgency"]["urgency_level"] == "high"


def test_alerts(store):
    a = store.add_alert(email_id=None, type="system", level="low", message="hi", details={"k": 1})
    assert store.unread_alert_count() == 1
    assert store.list_alerts(unread_only=True)[0].id == a.id
    assert store.mark_alert_read(a.id)
    assert store.unread_alert_count() == 0
    assert store.mark_alert_read(999) is False


def test_settings_roundtrip(store):
    assert store.get_setting("x") is None
    store.set_setting("x", {"a": [1, 2]})
    assert store.get_setting("x") == {"a": [1, 2]}


def test_list_emails_filters_and_search(store):
    for i in range(3):
        _add(store, i)
    store.set_status(2, EmailStatus.DONE)
    assert len(store.list_emails(status=EmailStatus.DONE)) == 1
    assert [e.subject for e in store.list_emails(q="s1")] == ["s1"]
    assert len(store.list_emails(limit=2)) == 2


def test_connections_are_per_thread_and_reused(store):
    import threading

    c1 = store._connect()
    assert store._connect() is c1
    seen = {}

    def other():
        seen["conn"] = store._connect()
        _add(store, 42)

    t = threading.Thread(target=other)
    t.start()
    t.join()
    assert seen["conn"] is not c1
    assert store.get_email(1).message_id == "m42"
