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
