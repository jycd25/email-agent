import pytest

from conftest import FakeLLM
from email_agent.analyzers import SenderAnalyzer, SenderCategory, TopicAnalyzer, UrgencyAnalyzer
from email_agent.analyzers.sender import pattern_matches
from email_agent.analyzers.topic import TopicCheck
from email_agent.analyzers.urgency import UrgencyCheck, exceeds
from email_agent.core.config import Profile


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


def test_persona_lands_in_prompt(fake_llm):
    UrgencyAnalyzer(fake_llm, Profile.ONCALL).quick("x")
    assert "on call for production" in fake_llm.calls[0][1]
    UrgencyAnalyzer(fake_llm, Profile.STUDENT).quick("x")
    assert "college student" in fake_llm.calls[1][1]


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


def test_pattern_matching():
    assert pattern_matches("Bob@X.com", "bob@x.com")
    assert pattern_matches("*@x.com", "anyone@x.com")
    assert not pattern_matches("*@x.com", "anyone@notx.com")
    assert pattern_matches("/.*@(a|b)\\.com/", "z@b.com")
    assert not pattern_matches("/[/", "z@b.com")


def test_sender_rule_hit_skips_llm(store, fake_llm):
    store.upsert_rule("*@corp.com", "vip")
    r = SenderAnalyzer(store, fake_llm, mode="auto").analyze("ceo@corp.com")
    assert r.category == SenderCategory.VIP and r.rule_matched == "*@corp.com" and r.is_trusted
    assert fake_llm.calls == []
    assert store.list_rules()[0].match_count == 1


def test_sender_falls_back_to_llm(store, fake_llm):
    r = SenderAnalyzer(store, fake_llm, mode="auto").analyze("new@corp.com", "hello")
    assert r.analysis_method == "llm" and r.category == SenderCategory.WORK
    assert r.suggested_rule == "*@corp.com"


def test_sender_rule_mode_never_calls_llm(store, fake_llm):
    r = SenderAnalyzer(store, fake_llm, mode="rule").analyze("new@corp.com")
    assert r.category == SenderCategory.UNKNOWN and fake_llm.calls == []


def test_sender_without_llm(store):
    r = SenderAnalyzer(store, None, mode="auto").analyze("x@y.z")
    assert r.category == SenderCategory.UNKNOWN and r.analysis_method == "none"


def test_llm_client_translates_connection_errors():
    from email_agent.core.config import Provider
    from email_agent.core.errors import AnalysisError
    from email_agent.llm import LLMClient

    c = LLMClient(Provider.OLLAMA, "m", base_url="http://127.0.0.1:9", timeout=0.5)
    with pytest.raises(AnalysisError, match="ollama serve"):
        c.structured(UrgencyCheck, system="s", user="u")
