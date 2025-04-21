"""All model prompts in one place.

Each prompt is built from three parts:
  1. a persona block describing who the user is and what matters to them,
  2. the task rubric,
  3. a short "how to be wrong safely" note (bias false negatives vs false
     positives depending on the task).

Keeping them here means tuning behaviour for a profile is a one-file change.
"""

from __future__ import annotations

from ..core.config import Profile

PERSONA: dict[Profile, str] = {
    Profile.GENERAL: (
        "The user is a professional managing a busy inbox. They care about deadlines, "
        "requests that need a reply, and anything with financial or legal consequences."
    ),
    Profile.STUDENT: (
        "The user is a college student. Their inbox mixes course announcements, "
        "professor and TA emails, registrar / bursar / financial-aid notices, club and "
        "campus event mail, and a lot of promotional noise.\n"
        "What matters most to them, in order:\n"
        "  1. Assignment, project and exam deadlines (especially changes to them).\n"
        "  2. Anything from a professor, TA or advisor addressed to them personally.\n"
        "  3. Registration, enrollment, tuition, financial aid and housing deadlines.\n"
        "  4. Class cancellations, room changes, office-hour changes.\n"
        "  5. Grades posted, feedback returned.\n"
        "Campus newsletters, club digests, dining/parking notices and vendor promotions "
        "are low priority even when they use words like 'urgent' or 'last chance'."
    ),
    Profile.ONCALL: (
        "The user is a software engineer who is on call for production systems. Their "
        "inbox receives monitoring alerts, incident and paging notifications, deploy and "
        "CI results, security advisories, ticket updates and ordinary team email.\n"
        "What matters most to them, in order:\n"
        "  1. Active production incidents: outages, error-rate spikes, latency, data loss, "
        "on-call pages, escalations, customer-impacting failures.\n"
        "  2. Security: vulnerability disclosures, credential leaks, certificate expiry.\n"
        "  3. Failed deploys, failed migrations, rollback requests.\n"
        "  4. Incident post-mortems and follow-up action items assigned to them.\n"
        "Vendor marketing and release-notes digests are low priority."
    ),
}

URGENCY_RUBRIC = """\
Urgency levels:
- low:    routine information, no action needed soon
- medium: needs action within a few days
- high:   needs attention within 24 hours, or a firm deadline is close
- urgent: needs attention now; missing it has real consequences (outage, lost
          grade, missed registration, money lost, security breach)

Guidance:
- Judge urgency from what the email asks the user to DO and by WHEN, not from
  how loud the language is. Marketing that says "act now" is still low.
- Automated notifications count as urgent only if they describe an active
  problem the user must respond to.
- If a deadline is stated, extract it verbatim into `deadline`.
- `confidence_score` is how sure you are of the level, 0 to 1."""

TOPIC_RUBRIC = """\
Similarity score:
- 0.9-1.0: the email is primarily about the topic
- 0.7-0.9: the topic is a significant part of the email
- 0.5-0.7: the topic is mentioned but is not the main point
- 0.2-0.5: loosely related
- 0.0-0.2: unrelated

Pick the single best-matching watchlist topic as `primary_topic`, or an empty
string if nothing matches above 0.2. Do not invent topics not on the list."""

SENDER_RUBRIC = """\
Sender categories:
- trusted:    known, reliable sender that should always get through
- blocked:    malicious, phishing, or unwanted
- unknown:    cannot tell; new or unclassifiable
- vip:        important person needing special attention
- newsletter: mailing lists and digests
- marketing:  promotional / commercial
- social:     social network notifications
- work:       colleagues, school staff, professional contacts
- personal:   friends and family

Judge from the address, display name, domain and any content provided.
Prefer `unknown` over guessing when the evidence is thin. Suggest a reusable
rule pattern when you are confident: an exact address, or `*@domain` for a
whole domain."""

CLASSIFY_RUBRIC = """\
Categories: Work, Personal, School, Social, Billing, Marketing, Spam, Other.
Priority: Urgent, Important, Normal, Low.

- Extract `action_list` as short imperative items the user must actually do.
- Put explicit dates (deadlines, meetings) in `important_dates` as ISO dates
  when the year is clear, otherwise as written.
- Spam and marketing are never Urgent or Important regardless of wording."""


def persona(profile: Profile) -> str:
    return PERSONA.get(profile, PERSONA[Profile.GENERAL])


def urgency_quick(profile: Profile) -> str:
    return (
        f"{persona(profile)}\n\nQuickly assess the urgency of the email below.\n\n"
        f"{URGENCY_RUBRIC}\n\nReturn only the level and your confidence."
    )


def urgency_full(profile: Profile) -> str:
    return (
        f"{persona(profile)}\n\nCarefully analyze the email below for urgency.\n\n"
        f"{URGENCY_RUBRIC}\n\nAlso list the specific words or phrases that drove your "
        "decision in `keywords_detected`, and write a one-sentence `summary` that says what "
        "the user needs to do and by when."
    )


def topic_quick(profile: Profile, topics: list[str]) -> str:
    return (
        f"{persona(profile)}\n\nDecide whether the email below is about any of these "
        f"watchlist topics:\n" + "\n".join(f"- {t}" for t in topics) + f"\n\n{TOPIC_RUBRIC}"
    )


def topic_full(profile: Profile, topics: list[str]) -> str:
    return (
        topic_quick(profile, topics)
        + "\n\nAlso write `message_summary`: one or two sentences saying what the email says "
        "about the topic and what, if anything, the user should do."
    )


def sender(profile: Profile) -> str:
    return f"{persona(profile)}\n\nCategorize the email sender described below.\n\n{SENDER_RUBRIC}"


def classify(profile: Profile) -> str:
    return f"{persona(profile)}\n\nClassify the email below.\n\n{CLASSIFY_RUBRIC}"


TOOL_SELECT_SYSTEM = (
    "You route a user's request to exactly one tool. Pick the tool whose description best "
    "matches what the user is asking for. If the request mentions a specific sender address "
    "and nothing else, choose sender analysis. If it asks about several things at once, "
    "choose the comprehensive analysis."
)
