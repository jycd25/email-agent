from datetime import UTC, datetime

import pytest

from conftest import FakeLLM
from email_agent.agent import EmailAgent, extract_address, extract_content, route_by_keywords
from email_agent.core.config import RuntimeSettings
from email_agent.instruction import parse_instruction


def test_extract_content():
    assert extract_content("is this urgent: {server down}") == "server down"
    assert extract_content("check urgency: hello there") == "hello there"
    assert extract_content("plain text") == "plain text"


def test_extract_address():
    assert extract_address("who is Bob.Smith+x@Corp.co.uk ?") == "bob.smith+x@corp.co.uk"
    assert extract_address("nothing") is None


@pytest.mark.parametrize(
    "p,tool",
    [
        ("is this urgent: {x}", "analyze_email_urgency"),
        ("what topic is this about: {x}", "analyze_email_topics"),
        ("analyze sender bob@x.com", "analyze_email_sender"),
        ("bob@x.com", "analyze_email_sender"),
        ("check urgency and sender: {x}", "comprehensive_email_analysis"),
        ("full analysis: {x}", "comprehensive_email_analysis"),
        ("{x}", "comprehensive_email_analysis"),
    ],
)
def test_keyword_router(p, tool):
    assert route_by_keywords(p) == tool


def test_agent_process_urgency(store, fake_llm):
    a = EmailAgent(store, RuntimeSettings(), fake_llm)
    r = a.process("is this urgent: {prod is down}")
    assert r["tool"] == "analyze_email_urgency" and "urgency" in r and "topic" not in r
    assert "Urgency:" in EmailAgent.format(r)


def test_agent_sender_only_makes_no_content_calls(store):
    llm = FakeLLM()
    a = EmailAgent(store, RuntimeSettings(), llm)
    r = a.process("analyze sender new@corp.com")
    assert r["sender"]["analysis_method"] == "llm" and "urgency" not in r


def test_agent_without_model(store):
    r = EmailAgent(store, RuntimeSettings(), None).process("is this urgent: {x}")
    assert r["error"] == "no model configured"


NOW = datetime(2025, 3, 3, 15, 30, tzinfo=UTC)


def test_instruction_rejects_nonsense():
    with pytest.raises(ValueError):
        parse_instruction("hello", NOW)


def test_instruction_urgency_now():
    c = parse_instruction("monitor urgency, starting now", NOW)
    assert c["analyze_urgency"] and c["fetch_since"] == "2025-03-03T15:30:00+00:00"


def test_instruction_topic_today_time():
    c = parse_instruction("monitor topic Security Incident, starting today 9am", NOW)
    assert c["watchlist_topics"] == ["security incident"]
    assert c["fetch_since"] == "2025-03-03T09:00:00+00:00"


def test_instruction_sender_llm_yesterday():
    c = parse_instruction("track sender john@example.com using llm, from yesterday", NOW)
    assert c["_sender"] == "john@example.com" and c["sender_mode"] == "llm"
    assert c["fetch_since"].startswith("2025-03-02T00:00:00")


def test_instruction_all():
    c = parse_instruction("monitor all emails", NOW)
    assert c["analyze_urgency"] and c["analyze_topics"] and c["analyze_sender"]
