import pytest

from conftest import FakeLLM
from email_agent.analyzers import TopicAnalyzer, UrgencyAnalyzer
from email_agent.analyzers.topic import TopicCheck
from email_agent.analyzers.urgency import UrgencyCheck, exceeds


def test_exceeds_threshold():
    assert exceeds("urgent", "high") and exceeds("high", "high")
    assert not exceeds("medium", "high")
    assert not exceeds("bogus", "high")


def test_urgency_short_circuits_on_confident_low(fake_llm):
    r = UrgencyAnalyzer(fake_llm).analyze("newsletter", threshold="high", min_confidence=0.7)
    assert r.urgency_level == "low" and r.detailed is False
    assert [c[0] for c in fake_llm.calls] == ["UrgencyCheck"]  # one call only


def test_urgency_runs_full_pass_when_quick_check_is_uncertain():
    llm = FakeLLM({UrgencyCheck: UrgencyCheck(urgency_level="low", confidence_score=0.3)})
    r = UrgencyAnalyzer(llm).analyze("hmm", threshold="high", min_confidence=0.7)
    assert r.detailed and r.urgency_level == "urgent"
    assert [c[0] for c in llm.calls] == ["UrgencyCheck", "UrgencyResult"]


def test_urgency_invalid_level_is_clamped():
    llm = FakeLLM({UrgencyCheck: UrgencyCheck(urgency_level="MEGA", confidence_score=7)})
    q = UrgencyAnalyzer(llm).quick("x")
    assert q.urgency_level == "low" and q.confidence_score == 0.0


def test_topic_skips_full_pass_below_threshold(fake_llm):
    r = TopicAnalyzer(fake_llm, ["Outage"]).analyze("hi", threshold=0.6)
    assert r.detailed is False and not r.is_watchlist_topic
    assert len(fake_llm.calls) == 1


def test_topic_full_pass_above_threshold():
    llm = FakeLLM(
        {TopicCheck: TopicCheck(topic="Outage", similarity_score=0.8, confidence_score=0.9)}
    )
    r = TopicAnalyzer(llm, ["Outage"]).analyze("prod down", threshold=0.6)
    assert r.is_watchlist_topic and r.primary_topic == "Production incident"
    assert "- Outage" in llm.calls[0][1]


def test_topic_with_no_topics_makes_no_calls(fake_llm):
    r = TopicAnalyzer(fake_llm, []).analyze("x", threshold=0.5)
    assert r.detailed is False and fake_llm.calls == []


def test_llm_client_translates_connection_errors():
    from email_agent.core.config import Provider
    from email_agent.core.errors import AnalysisError
    from email_agent.llm import LLMClient

    c = LLMClient(Provider.OLLAMA, "m", base_url="http://127.0.0.1:9", timeout=0.5)
    with pytest.raises(AnalysisError, match="ollama serve"):
        c.structured(UrgencyCheck, system="s", user="u")
