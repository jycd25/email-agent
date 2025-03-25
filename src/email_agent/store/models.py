from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class EmailStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class EmailRow(BaseModel):
    id: int
    source: str
    message_id: str
    received_at: str
    from_addr: str
    subject: str
    body_text: str
    status: EmailStatus
    attempts: int
    error: str | None
    created_at: str
    updated_at: str


class Analysis(BaseModel):
    id: int
    email_id: int
    kind: str
    result: dict[str, Any]
    created_at: str


class Alert(BaseModel):
    id: int
    email_id: int | None
    type: str
    level: str
    message: str
    details: dict[str, Any]
    read: bool
    created_at: str


class SenderRule(BaseModel):
    pattern: str
    category: str
    notes: str | None = None
    added_at: str
    last_matched: str | None = None
    match_count: int = 0
