from conftest import SAMPLE_HTML, SAMPLE_PLAIN
from email_agent.sources.parse import html_to_text, parse_raw


def test_plain_email():
    p = parse_raw(SAMPLE_PLAIN)
    assert p.from_addr == "ada@university.edu"
    assert p.from_name == "Prof. Ada"
    assert p.subject == "Assignment 3 deadline moved to Friday"
    assert "Friday 5pm" in p.body_text


def test_html_only_email_is_converted_and_scripts_dropped():
    p = parse_raw(SAMPLE_HTML)
    assert p.from_addr == "alerts@pagerduty.com"
    assert "Error rate 12% on api-prod." in p.body_text
    assert "Ack within 5 minutes." in p.body_text
    assert "alert(1)" not in p.body_text
    assert "p{}" not in p.body_text


def test_html_to_text_keeps_line_breaks():
    assert html_to_text("a<br>b") == "a\nb"


def test_encoded_subject_header():
    raw = b"From: x@y.z\nSubject: =?utf-8?q?Caf=C3=A9_deadline?=\n\nbody\n"
    assert parse_raw(raw).subject == "Café deadline"
