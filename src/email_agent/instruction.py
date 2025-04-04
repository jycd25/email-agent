"""'monitor urgency, starting today 9am' -> settings changes. No model needed."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any


def parse_instruction(text: str, now: datetime | None = None) -> dict[str, Any]:
    """Return a partial RuntimeSettings dict, or raise ValueError with a hint."""
    now = now or datetime.now(UTC)
    t = text.strip().lower()
    if not any(w in t for w in ("monitor", "watch", "track", "alert")):
        raise ValueError("Try something like: monitor urgency, starting now")

    changes: dict[str, Any] = {}

    if any(w in t for w in ("urgen", "priority")):
        changes.update(analyze_urgency=True)
    if m := re.search(r"(?:topic|about)\s+[\"']?([^\"',]+)", t):
        topic = m.group(1).strip()
        changes.update(analyze_topics=True, watchlist_topics=[topic])
    if m := re.search(r"(?:sender|from)\s+[\"']?([\w.+*@-]+)", t):
        changes.update(analyze_sender=True, _sender=m.group(1).strip())
        if "llm" in t:
            changes["sender_mode"] = "llm"
        elif "rule" in t or "pattern" in t:
            changes["sender_mode"] = "rule"
    if "everything" in t or "all emails" in t or "comprehensive" in t:
        changes.update(analyze_urgency=True, analyze_topics=True, analyze_sender=True)
    if not any(k.startswith("analyze") for k in changes):
        changes.update(analyze_urgency=True, analyze_topics=True, analyze_sender=True)

    if "starting now" in t or "from now" in t:
        changes["fetch_since"] = now.isoformat(timespec="seconds")
    elif "yesterday" in t:
        changes["fetch_since"] = (
            (now - timedelta(days=1))
            .replace(hour=0, minute=0, second=0)
            .isoformat(timespec="seconds")
        )
    elif "today" in t:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if m := re.search(r"today\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t):
            h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
            if ap == "pm" and h < 12:
                h += 12
            if ap == "am" and h == 12:
                h = 0
            start = start.replace(hour=h, minute=mi)
        changes["fetch_since"] = start.isoformat(timespec="seconds")
    elif "all time" in t or "no filter" in t:
        changes["fetch_since"] = None

    return changes
