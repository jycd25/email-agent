from __future__ import annotations

import logging
import re
from enum import Enum

from pydantic import BaseModel, Field

from ..core.config import Profile
from ..llm import LLM
from ..store import Store
from . import prompts

log = logging.getLogger(__name__)


class SenderCategory(str, Enum):
    TRUSTED = "trusted"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"
    VIP = "vip"
    NEWSLETTER = "newsletter"
    MARKETING = "marketing"
    SOCIAL = "social"
    WORK = "work"
    PERSONAL = "personal"


TRUSTED_CATEGORIES = {
    SenderCategory.TRUSTED,
    SenderCategory.VIP,
    SenderCategory.WORK,
    SenderCategory.PERSONAL,
}


class SenderLLMAnalysis(BaseModel):
    category: SenderCategory
    confidence_score: float = Field(description="0 to 1")
    notes: str | None = None
    suggested_rule: str | None = Field(None, description="exact address or *@domain")


class SenderResult(BaseModel):
    email: str
    category: SenderCategory
    rule_matched: str | None = None
    is_trusted: bool = False
    is_blocked: bool = False
    notes: str | None = None
    confidence_score: float = 1.0
    suggested_rule: str | None = None
    analysis_method: str = "rule"


def pattern_matches(pattern: str, address: str) -> bool:
    address, pattern = address.lower().strip(), pattern.lower().strip()
    if pattern == address:
        return True
    if pattern.startswith("*@"):
        return address.endswith("@" + pattern[2:])
    if len(pattern) > 2 and pattern.startswith("/") and pattern.endswith("/"):
        try:
            return re.fullmatch(pattern[1:-1], address) is not None
        except re.error:
            log.warning("invalid sender regex %r", pattern)
    return False


class SenderAnalyzer:
    """Rules first (from the store), LLM only when rules say nothing."""

    def __init__(
        self,
        store: Store,
        llm: LLM | None,
        *,
        mode: str = "auto",
        profile: Profile = Profile.GENERAL,
        rules: list | None = None,
    ) -> None:
        self.store = store
        self.llm = llm
        self.mode = mode
        self.profile = profile
        self._rules = rules  # None = read from the store on each call

    def by_rule(self, address: str) -> SenderResult | None:
        address = address.lower().strip()
        rules = self._rules if self._rules is not None else self.store.list_rules()
        for rule in rules:
            if pattern_matches(rule.pattern, address):
                self.store.touch_rule(rule.pattern)
                cat = SenderCategory(rule.category)
                return SenderResult(
                    email=address,
                    category=cat,
                    rule_matched=rule.pattern,
                    notes=rule.notes,
                    is_trusted=cat in TRUSTED_CATEGORIES,
                    is_blocked=cat == SenderCategory.BLOCKED,
                )
        return None

    def by_llm(self, address: str, content: str | None = None) -> SenderResult:
        address = address.lower().strip()
        if self.llm is None:
            return SenderResult(
                email=address,
                category=SenderCategory.UNKNOWN,
                confidence_score=0.0,
                notes="no model configured",
                analysis_method="none",
            )
        user = f"Sender address: {address}"
        if content:
            user += f"\n\nEmail excerpt:\n{content[:1500]}"
        a = self.llm.structured(SenderLLMAnalysis, system=prompts.sender(self.profile), user=user)
        conf = a.confidence_score if 0 <= a.confidence_score <= 1 else 0.5
        return SenderResult(
            email=address,
            category=a.category,
            notes=a.notes,
            confidence_score=conf,
            suggested_rule=a.suggested_rule,
            analysis_method="llm",
            is_trusted=a.category in TRUSTED_CATEGORIES,
            is_blocked=a.category == SenderCategory.BLOCKED,
        )

    def analyze(self, address: str, content: str | None = None) -> SenderResult:
        if self.mode == "llm":
            return self.by_llm(address, content)
        hit = self.by_rule(address)
        if hit or self.mode == "rule":
            return hit or SenderResult(
                email=address.lower().strip(), category=SenderCategory.UNKNOWN
            )
        return self.by_llm(address, content)
