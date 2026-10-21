"""Guard against case-specific tuning in the Phase 6 prompts and tool descriptions.

Every prompt and description set after V1 must stay general. These tests fail if a V2+ text
mentions a fixture member ID (mem_ plus four digits), a fixture username or display name, a
channel ID or channel name, a fixture role name (other than the generic word "Member"), or
copies six or more words in a row from any eval case request. V1 is exempt: it was written
before any results existed, and it must stay unchanged so the baseline can be reproduced.

The wording check looks only at word sequences that are new since V1. Text carried over from
V1 predates the eval cases (some cases reuse a phrase from the V1 descriptions), so it can't
be tuning against them.
"""

import json
import re
from pathlib import Path

import pytest

from toolward.agent.prompts import SYSTEM_PROMPTS
from toolward.evals.cases import load_cases
from toolward.server.descriptions import DESCRIPTIONS

FIXTURES = json.loads(
    (Path(__file__).resolve().parent.parent / "fixtures" / "community.json").read_text()
)
GENERIC_ROLE_WORDS = {"Member"}  # "member" is everywhere in the descriptions
CASE_REQUESTS = [(case.id, case.request) for case in load_cases()]


def _description_text(descriptions: dict[str, dict]) -> str:
    parts = []
    for text in descriptions.values():
        parts.append(text["description"])
        parts.extend(text["params"].values())
    return "\n".join(parts)


def _ngrams(text: str, n: int = 6) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def problems(text: str, baseline: str = "") -> list[str]:
    """Everything in the text that points at specific fixture data or eval cases.

    baseline: the V1 text; word sequences that already appear in it are not counted as copied
    case wording.
    """
    found = []
    if re.search(r"mem_\d{4}", text):
        found.append("a member ID")
    if re.search(r"\bch_\d+", text):
        found.append("a channel ID")
    lowered = text.lower()
    for member in FIXTURES["members"]:
        for name in (member["username"], member["display_name"]):
            if re.search(rf"(?<![a-z0-9_.]){re.escape(name.lower())}(?![a-z0-9_])", lowered):
                found.append(f"member name {name!r}")
    for role in FIXTURES["roles"]:
        if role["name"] not in GENERIC_ROLE_WORDS and re.search(
            rf"\b{re.escape(role['name'])}\b", text
        ):
            found.append(f"role {role['name']!r}")
    for channel in FIXTURES["channels"]:
        if f"#{channel['name'].lower()}" in lowered:
            found.append(f"channel #{channel['name']}")
    grams = _ngrams(text) - _ngrams(baseline)
    for case_id, request in CASE_REQUESTS:
        if _ngrams(request) & grams:
            found.append(f"wording from {case_id}")
    return found


V1_PROMPT = SYSTEM_PROMPTS["V1"]
V1_DESCRIPTIONS = _description_text(DESCRIPTIONS["V1"])
TEXTS = [(f"prompt {v}", text, V1_PROMPT) for v, text in SYSTEM_PROMPTS.items() if v != "V1"] + [
    (f"descriptions {v}", _description_text(d), V1_DESCRIPTIONS)
    for v, d in DESCRIPTIONS.items()
    if v != "V1"
]


def test_there_are_phase6_texts_to_check():
    assert TEXTS, "no V2+ prompt or description set exists yet"


@pytest.mark.parametrize(("name", "text", "baseline"), TEXTS, ids=[t[0] for t in TEXTS])
def test_phase6_text_is_not_case_specific(name, text, baseline):
    assert problems(text, baseline) == [], f"{name} is case-specific"


def test_the_check_catches_planted_examples():
    request_words = " ".join(CASE_REQUESTS[0][1].split()[:6])
    planted = (
        f"Use an ID like mem_0042 for {FIXTURES['members'][5]['display_name']}, give the "
        f"Book Club role, post in ch_01, and handle: {request_words}"
    )
    found = problems(planted)
    assert "a member ID" in found and "a channel ID" in found
    assert any(p.startswith("member name") for p in found)
    assert "role 'Book Club'" in found
    assert any(p.startswith("wording from") for p in found), found
    # The same wording is fine when it was already in the baseline text.
    assert not any(p.startswith("wording from") for p in problems(planted, planted))
    assert problems(DESCRIPTIONS["V1"]["assign_role"]["params"]["member_id"]) == ["a member ID"]
