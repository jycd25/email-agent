from __future__ import annotations

from typing import TypeVar

import pytest
from pydantic import BaseModel

from email_agent.analyzers.topic import TopicCheck, TopicResult
from email_agent.analyzers.urgency import UrgencyCheck, UrgencyResult
from email_agent.core.config import AppConfig
from email_agent.store import Store

T = TypeVar("T", bound=BaseModel)


class FakeLLM:
    """Returns canned results per schema. Records every call so tests can
    assert how many model calls a code path made."""

    def __init__(self, overrides: dict | None = None):
        self.calls: list[tuple[str, str]] = []
        self.responses: dict[type, BaseModel] = {
            UrgencyCheck: UrgencyCheck(urgency_level="low", confidence_score=0.9),
            UrgencyResult: UrgencyResult(
                urgency_level="urgent",
                time_sensitive=True,
                deadline="today 5pm",
                keywords_detected=["down"],
                confidence_score=0.95,
                summary="Prod is down; fix now.",
            ),
            TopicCheck: TopicCheck(topic="", similarity_score=0.1, confidence_score=0.9),
            TopicResult: TopicResult(
                primary_topic="Production incident",
                similarity_score=0.9,
                confidence_score=0.9,
                message_summary="Outage in prod.",
            ),
        }
        self.responses.update(overrides or {})

    def structured(self, schema, *, system, user, model=None):
        self.calls.append((schema.__name__, system))
        r = self.responses[schema]
        return r.model_copy()

    def text(self, *, system, user, model=None, max_tokens=256):
        self.calls.append(("text", system))
        return "ok"


@pytest.fixture
def store(tmp_path) -> Store:
    return Store(tmp_path / "t.db")


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def config(tmp_path, monkeypatch) -> AppConfig:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return AppConfig(data_dir=tmp_path / "data", _env_file=None)


SAMPLE_PLAIN = b"""From: Prof. Ada <ada@university.edu>
To: student@university.edu
Subject: Assignment 3 deadline moved to Friday
Date: Mon, 3 Mar 2025 09:00:00 +0000
Content-Type: text/plain; charset=utf-8

Hi all, the deadline for Assignment 3 is now Friday 5pm. No extensions.
"""

SAMPLE_HTML = b"""From: PagerDuty <alerts@pagerduty.com>
Subject: [TRIGGERED] High error rate on api-prod
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="b1"

--b1
Content-Type: text/html; charset=utf-8

<html><head><style>p{}</style><title>x</title></head>
<body><p>Error rate <b>12%</b> on api-prod.</p><script>alert(1)</script><p>Ack within 5 minutes.</p></body></html>
--b1--
"""
