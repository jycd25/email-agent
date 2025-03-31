from __future__ import annotations

from pydantic import BaseModel, Field

from ..core.config import Profile
from ..llm import LLM
from . import prompts


class TopicCheck(BaseModel):
    topic: str = Field(description="best matching watchlist topic or empty string")
    similarity_score: float = Field(description="0 to 1")
    confidence_score: float = Field(description="0 to 1")


class TopicResult(BaseModel):
    primary_topic: str
    similarity_score: float
    confidence_score: float
    message_summary: str = ""
    is_watchlist_topic: bool = False
    detailed: bool = True


class TopicAnalyzer:
    def __init__(self, llm: LLM, topics: list[str], profile: Profile = Profile.GENERAL) -> None:
        self.llm = llm
        self.topics = [t for t in topics if t.strip()]
        self.profile = profile

    def quick(self, content: str) -> TopicCheck:
        r = self.llm.structured(
            TopicCheck, system=prompts.topic_quick(self.profile, self.topics), user=content
        )
        r.similarity_score = _unit(r.similarity_score)
        r.confidence_score = _unit(r.confidence_score)
        return r

    def full(self, content: str) -> TopicResult:
        r = self.llm.structured(
            TopicResult, system=prompts.topic_full(self.profile, self.topics), user=content
        )
        r.similarity_score = _unit(r.similarity_score)
        r.confidence_score = _unit(r.confidence_score)
        r.detailed = True
        return r

    def analyze(self, content: str, *, threshold: float) -> TopicResult:
        if not self.topics:
            return TopicResult(
                primary_topic="",
                similarity_score=0.0,
                confidence_score=1.0,
                message_summary="No watchlist topics configured.",
                detailed=False,
            )
        q = self.quick(content)
        if q.similarity_score < threshold:
            return TopicResult(
                primary_topic=q.topic,
                similarity_score=q.similarity_score,
                confidence_score=q.confidence_score,
                detailed=False,
            )
        r = self.full(content)
        r.is_watchlist_topic = r.similarity_score >= threshold
        return r


def _unit(x: float) -> float:
    return 0.0 if x < 0 or x > 1 else float(x)
