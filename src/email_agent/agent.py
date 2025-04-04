"""Prompt-driven entry point: "is this urgent: {...}" -> the right analyzer.

Tool selection uses OpenAI function calling when an OpenAI key is present,
otherwise a small keyword router. Either way the analysis itself runs on the
configured provider.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .analyzers import Classifier, SenderAnalyzer, TopicAnalyzer, UrgencyAnalyzer, prompts
from .core.config import RuntimeSettings
from .llm import LLM
from .pipeline.worker import clip
from .store import Store

log = logging.getLogger(__name__)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "analyze_email_urgency",
            "description": "Determine how urgent an email is (low, medium, high, urgent).",
            "parameters": {
                "type": "object",
                "properties": {"email_content": {"type": "string"}},
                "required": ["email_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_email_topics",
            "description": "Check whether an email is about any watchlist topic.",
            "parameters": {
                "type": "object",
                "properties": {"email_content": {"type": "string"}},
                "required": ["email_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_email_sender",
            "description": "Categorize an email sender address (trusted, blocked, vip, ...).",
            "parameters": {
                "type": "object",
                "properties": {"email_address": {"type": "string"}},
                "required": ["email_address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "comprehensive_email_analysis",
            "description": "Run urgency, topic and sender analysis together.",
            "parameters": {
                "type": "object",
                "properties": {"email_content": {"type": "string"}},
                "required": ["email_content"],
            },
        },
    },
]

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def extract_content(prompt: str) -> str:
    """Body is either inside {braces} or everything after the first colon."""
    m = re.search(r"\{(.*)\}", prompt, re.DOTALL)
    if m:
        return m.group(1).strip()
    if ":" in prompt:
        return prompt.split(":", 1)[1].strip()
    return prompt.strip()


def extract_address(prompt: str) -> str | None:
    m = _EMAIL_RE.search(prompt)
    return m.group(0).lower() if m else None


def route_by_keywords(prompt: str) -> str:
    p = prompt.lower()
    has_addr = extract_address(prompt) is not None
    wants = {
        "analyze_email_urgency": any(
            w in p for w in ("urgen", "priority", "asap", "deadline", "how soon")
        ),
        "analyze_email_topics": any(
            w in p for w in ("topic", "watchlist", "about", "related to", "subject")
        ),
        "analyze_email_sender": any(
            w in p for w in ("sender", "who sent", "from address", "trust", "block")
        ),
    }
    hits = [k for k, v in wants.items() if v]
    if "everything" in p or "comprehensive" in p or "full analysis" in p or len(hits) > 1:
        return "comprehensive_email_analysis"
    if hits:
        return hits[0]
    if has_addr and len(p.split()) < 12:
        return "analyze_email_sender"
    return "comprehensive_email_analysis"


class EmailAgent:
    def __init__(
        self, store: Store, settings: RuntimeSettings, llm: LLM | None, selector: Any | None = None
    ) -> None:
        """`selector` is an openai.OpenAI client used only for tool choice (optional)."""
        self.store = store
        self.s = settings
        self.llm = llm
        self.selector = selector

    def select_tool(self, prompt: str) -> str:
        if self.selector is None:
            return route_by_keywords(prompt)
        try:
            resp = self.selector.chat.completions.create(
                model=self.s.tool_selection_model,
                messages=[
                    {"role": "system", "content": prompts.TOOL_SELECT_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                tools=TOOLS,
                tool_choice="required",
                temperature=0,
            )
            calls = resp.choices[0].message.tool_calls or []
            if calls:
                return calls[0].function.name
        except Exception as e:  # noqa: BLE001 - fall back rather than fail the request
            log.warning("tool selection failed (%s); using keyword router", e)
        return route_by_keywords(prompt)

    def process(self, prompt: str) -> dict[str, Any]:
        tool = self.select_tool(prompt)
        content = clip(extract_content(prompt))
        address = extract_address(prompt)
        out: dict[str, Any] = {"tool": tool}
        if tool in ("analyze_email_sender", "comprehensive_email_analysis") and address:
            r = SenderAnalyzer(
                self.store, self.llm, mode=self.s.sender_mode, profile=self.s.profile
            )
            out["sender"] = r.analyze(
                address, content if tool != "analyze_email_sender" else None
            ).model_dump()
            if tool == "analyze_email_sender":
                return out
        if self.llm is None:
            out["error"] = "no model configured"
            return out
        if tool in ("analyze_email_urgency", "comprehensive_email_analysis"):
            out["urgency"] = (
                UrgencyAnalyzer(self.llm, self.s.profile)
                .analyze(
                    content,
                    threshold=self.s.urgency_threshold,
                    min_confidence=self.s.min_confidence,
                )
                .model_dump()
            )
        if tool in ("analyze_email_topics", "comprehensive_email_analysis"):
            out["topic"] = (
                TopicAnalyzer(self.llm, self.s.watchlist_topics, self.s.profile)
                .analyze(content, threshold=self.s.topic_threshold)
                .model_dump()
            )
        if tool == "comprehensive_email_analysis" and self.s.classify:
            out["classification"] = (
                Classifier(self.llm, self.s.profile).classify(content).model_dump()
            )
        return out

    @staticmethod
    def format(result: dict[str, Any]) -> str:
        lines = [f"Tool: {result.get('tool')}"]
        if "error" in result:
            lines.append(f"Error: {result['error']}")
        if u := result.get("urgency"):
            lines.append(f"Urgency: {u['urgency_level']} (confidence {u['confidence_score']:.2f})")
            if u.get("deadline"):
                lines.append(f"  Deadline: {u['deadline']}")
            lines.append(f"  {u['summary']}")
        if t := result.get("topic"):
            lines.append(
                f"Topic: {t['primary_topic'] or '-'} (similarity {t['similarity_score']:.2f})"
            )
            if t.get("message_summary"):
                lines.append(f"  {t['message_summary']}")
        if s := result.get("sender"):
            lines.append(f"Sender: {s['email']} -> {s['category']} via {s['analysis_method']}")
        if c := result.get("classification"):
            lines.append(f"Class: {c['category']} / {c['priority']}")
            for a in c.get("action_list", []):
                lines.append(f"  - {a}")
        return "\n".join(lines) if len(lines) > 1 else json.dumps(result, indent=2)
