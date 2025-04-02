from __future__ import annotations

from pydantic import BaseModel, Field

from ..core.config import Profile
from ..llm import LLM
from . import prompts

MAX_CHARS = 10_000


class Classification(BaseModel):
    category: str = Field(
        description="Work, Personal, School, Social, Billing, Marketing, Spam, Other"
    )
    priority: str = Field(description="Urgent, Important, Normal, Low")
    action_required: bool
    action_list: list[str] = Field(default_factory=list)
    important_dates: list[str] = Field(default_factory=list)
    summary: str = ""


class Classifier:
    def __init__(self, llm: LLM, profile: Profile = Profile.GENERAL) -> None:
        self.llm = llm
        self.profile = profile

    def classify(self, content: str, *, subject: str = "", sender: str = "") -> Classification:
        if len(content) > MAX_CHARS:
            content = content[:MAX_CHARS] + "\n[truncated]"
        user = f"From: {sender}\nSubject: {subject}\n\n{content}"
        return self.llm.structured(Classification, system=prompts.classify(self.profile), user=user)
