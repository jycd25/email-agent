from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from ..core.config import Profile
from ..llm import LLM
from . import prompts

log = logging.getLogger(__name__)

URGENCY_LEVELS = {"low": 1, "medium": 2, "high": 3, "urgent": 4}


class UrgencyCheck(BaseModel):
    urgency_level: str = Field(description="one of: low, medium, high, urgent")
    confidence_score: float = Field(description="0 to 1")


class UrgencyResult(BaseModel):
    urgency_level: str = Field(description="one of: low, medium, high, urgent")
    time_sensitive: bool = Field(description="whether a deadline or time constraint exists")
    deadline: str | None = Field(None, description="the deadline, verbatim, if stated")
    keywords_detected: list[str] = Field(default_factory=list)
    confidence_score: float = Field(description="0 to 1")
    summary: str = Field(description="what the user must do and by when")
    detailed: bool = Field(True, description="false when only the quick check ran")


def level_value(level: str) -> int:
    return URGENCY_LEVELS.get(level.strip().lower(), 0)


def exceeds(level: str, threshold: str) -> bool:
    return level_value(level) >= level_value(threshold) > 0


class UrgencyAnalyzer:
    """Two-stage: a cheap check first, the full analysis only if it might matter."""

    def __init__(self, llm: LLM, profile: Profile = Profile.GENERAL) -> None:
        self.llm = llm
        self.profile = profile

    def quick(self, content: str) -> UrgencyCheck:
        r = self.llm.structured(
            UrgencyCheck, system=prompts.urgency_quick(self.profile), user=content
        )
        return _clamp_check(r)

    def full(self, content: str) -> UrgencyResult:
        r = self.llm.structured(
            UrgencyResult, system=prompts.urgency_full(self.profile), user=content
        )
        r.urgency_level = r.urgency_level.strip().lower()
        if r.urgency_level not in URGENCY_LEVELS:
            log.warning("invalid urgency level %r -> low", r.urgency_level)
            r.urgency_level = "low"
        r.confidence_score = _unit(r.confidence_score)
        r.detailed = True
        return r

    def analyze(self, content: str, *, threshold: str, min_confidence: float) -> UrgencyResult:
        q = self.quick(content)
        # Anything below threshold or too uncertain stops here: one cheap call.
        # A low-confidence "urgent" still gets the full pass so we do not miss it.
        if not exceeds(q.urgency_level, threshold) and q.confidence_score >= min_confidence:
            return UrgencyResult(
                urgency_level=q.urgency_level,
                time_sensitive=False,
                deadline=None,
                keywords_detected=[],
                confidence_score=q.confidence_score,
                summary=f"Quick check: {q.urgency_level} urgency.",
                detailed=False,
            )
        return self.full(content)


def _unit(x: float) -> float:
    return 0.0 if x < 0 or x > 1 else float(x)


def _clamp_check(r: UrgencyCheck) -> UrgencyCheck:
    r.urgency_level = r.urgency_level.strip().lower()
    if r.urgency_level not in URGENCY_LEVELS:
        r.urgency_level = "low"
    r.confidence_score = _unit(r.confidence_score)
    return r
