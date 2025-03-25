from __future__ import annotations

from typing import TypeVar

import pytest
from pydantic import BaseModel

from email_agent.core.config import AppConfig
from email_agent.store import Store

T = TypeVar("T", bound=BaseModel)


@pytest.fixture
def store(tmp_path) -> Store:
    return Store(tmp_path / "t.db")


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
