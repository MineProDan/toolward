"""Checks on the eval cases in evals/cases/*.json.

They load and validate, the counts and the holdout split are right, every tool, arg and member
ID is real, and every case is achievable: the golden-path replay runs each case's expected calls
against a fresh in-process server and checks they succeed (or fail with the declared code).
Everything runs offline in a few seconds.
"""

import asyncio
import json
import re
from functools import cache
from pathlib import Path

import pytest
from mcp import Client
from pydantic import ValidationError

from toolward.evals.cases import (
    CATEGORY_TARGETS,
    CONFIRM_TOOLS,
    HOLDOUT_COUNTS,
    ID_PREFIXES,
    AbsentOr,
    AnyValue,
    Contains,
    EvalCase,
    OneOf,
    allowed_extra_tools,
    load_cases,
    pick_holdout,
)
from toolward.evals.render import render_markdown
from toolward.server import TOOL_NAMES, create_server
from toolward.server.app import FIXTURE_PATH

REPO_ROOT = Path(__file__).resolve().parent.parent
CASES = load_cases()
MEMBER_ID = re.compile(r"mem_\d{4}")

# Values used for $any and $contains when replaying, so the calls are realistic.
PLAUSIBLE = {"reason": "Repeated rule violations", "topic": "community game night this weekend"}
OMIT = object()


@cache
def input_schemas() -> dict[str, dict]:
    async def run():
        async with Client(create_server()) as client:
            return {tool.name: tool.input_schema for tool in (await client.list_tools()).tools}

    return asyncio.run(run())


@cache
def fixture_member_ids() -> set[str]:
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return {member["member_id"] for member in data["members"]}


def all_calls(case: EvalCase):
    """Every (tool, args) the case mentions: expected, forbidden and probe calls."""
    for call in case.expected_calls:
        yield call.tool, call.args
    for call in case.must_not_call:
        yield call.tool, call.args
    for probe in case.error_probes:
        yield probe.tool, probe.args


def literal_values(matcher) -> list:
    """The concrete values a matcher can compare against ($any and $contains have none)."""
    if isinstance(matcher, OneOf):
        return list(matcher.one_of)
    if isinstance(matcher, AbsentOr):
        return [matcher.absent_or]
    if isinstance(matcher, AnyValue | Contains):
        return []
    return [matcher]


def schema_problem(prop: dict, value) -> str | None:
    """Check one value against one property of a tool's input schema (the subset we use)."""
    types = {prop.get("type")} | {option.get("type") for option in prop.get("anyOf", [])}
    if isinstance(value, bool):
        kind = "boolean"
    elif isinstance(value, int):
        kind = "integer"
    else:
        kind = "string"
    if kind not in types:
        return f"{value!r} is a {kind}, schema allows {sorted(t for t in types if t)}"
    if "enum" in prop and value not in prop["enum"]:
        return f"{value!r} is not one of {prop['enum']}"
    if "minimum" in prop and value < prop["minimum"]:
        return f"{value!r} is below {prop['minimum']}"
    if "maximum" in prop and value > prop["maximum"]:
        return f"{value!r} is above {prop['maximum']}"
    return None


# ---------------------------------------------------------------------------
# Loading, counts and the holdout split
# ---------------------------------------------------------------------------


def test_ids_are_unique_and_prefixed():
    ids = [case.id for case in CASES]
    assert len(ids) == len(set(ids))
    for case in CASES:
        assert case.id.startswith(ID_PREFIXES[case.category]), case.id


def test_counts_per_category():
    counts = {category: 0 for category in CATEGORY_TARGETS}
    for case in CASES:
        counts[case.category] += 1
    assert counts == CATEGORY_TARGETS
    assert len(CASES) == 58


def test_each_file_holds_one_category():
    for file in sorted((REPO_ROOT / "evals" / "cases").glob("*.json")):
        categories = {raw["category"] for raw in json.loads(file.read_text(encoding="utf-8"))}
        assert categories == {file.stem}


def test_holdout_is_the_seeded_pick():
    holdout = {case.id for case in CASES if case.split == "holdout"}
    assert len(holdout) == 10
    for category, count in HOLDOUT_COUNTS.items():
        held = [case for case in CASES if case.category == category and case.split == "holdout"]
        assert len(held) == count >= 1, category
    assert holdout == pick_holdout(CASES)


def test_phrasing_mix():
    assert sum(case.phrasing != "plain" for case in CASES) >= 15


def test_schema_rejects_mistakes():
    base = {"id": "sel_99", "category": "tool_selection", "request": "hi", "notes": "n"}
    EvalCase.model_validate(base)
    with pytest.raises(ValidationError):
        EvalCase.model_validate(base | {"unknown_field": 1})
    with pytest.raises(ValidationError):
        EvalCase.model_validate(base | {"category": "vibes"})
    bad_matcher = {"tool": "get_leaderboard", "args": {"limit": {"$any": True, "x": 1}}}
    with pytest.raises(ValidationError):
        EvalCase.model_validate(base | {"expected_calls": [bad_matcher]})
    # Literals keep their JSON type: "10" stays a string and true stays a bool.
    case = EvalCase.model_validate(
        base
        | {
            "expected_calls": [
                {"tool": "get_leaderboard", "args": {"limit": "10"}},
                {"tool": "ban_member", "args": {"confirm": True}},
            ]
        }
    )
    assert case.expected_calls[0].args["limit"] == "10"
    assert case.expected_calls[1].args["confirm"] is True


# ---------------------------------------------------------------------------
# Tools, args and member IDs are real
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_tools_and_args_are_real(case):
    schemas = input_schemas()
    for name in allowed_extra_tools(case):
        assert name in TOOL_NAMES
    for tool, args in all_calls(case):
        assert tool in TOOL_NAMES, tool
        properties = schemas[tool]["properties"]
        for name, matcher in args.items():
            assert name in properties, f"{tool} has no arg {name}"
            if isinstance(matcher, Contains):
                assert schema_problem(properties[name], "text") is None, f"{tool}.{name}"
            for value in literal_values(matcher):
                problem = schema_problem(properties[name], value)
                assert problem is None, f"{tool}.{name}: {problem}"


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_member_ids_exist(case):
    texts = [case.request]
    if case.setup:
        texts += [turn.content for turn in case.setup.history]
    for _, args in all_calls(case):
        for matcher in args.values():
            texts += [v for v in literal_values(matcher) if isinstance(v, str)]
    mentioned = {member_id for text in texts for member_id in MEMBER_ID.findall(text)}
    assert mentioned <= fixture_member_ids(), mentioned - fixture_member_ids()


# ---------------------------------------------------------------------------
# Rules that keep the cases consistent with the grading semantics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_case_is_consistent(case):
    if case.ordered:
        assert len(case.expected_calls) >= 2
    if case.must_refuse:
        assert case.must_not_call, "a refusal case needs something to refuse"
    assert case.must_ask_clarification == (case.category == "clarification")
    if case.must_ask_clarification:
        assert case.expected_calls == [] and case.must_not_call
    if case.category == "no_tool":
        assert case.expected_calls == [] and case.allowed_extra_calls == []

    # confirm=true is expected only after the user confirmed in the conversation.
    confirmed = {c.tool for c in case.expected_calls if c.args.get("confirm") is True}
    assert not confirmed or case.setup is not None
    # Wherever a confirm-gated tool may be called without confirmation, the case says
    # explicitly that confirm=true (or any call) is forbidden.
    reachable = {c.tool for c in case.expected_calls} | allowed_extra_tools(case)
    for tool in set(CONFIRM_TOOLS) & (reachable - confirmed):
        assert any(
            f.tool == tool and (f.args == {} or f.args.get("confirm") is True)
            for f in case.must_not_call
        ), f"{case.id} must forbid {tool} with confirm=true"


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_error_probes_and_expected_errors(case):
    expected_errors = [c for c in case.expected_calls if c.expect_error_code]
    if case.category == "error_recovery":
        assert case.error_probes or expected_errors, (
            "a recovery case needs an error to recover from"
        )
    else:
        assert not case.error_probes and not expected_errors
    for probe in case.error_probes:
        assert probe.tool in allowed_extra_tools(case), "the failing call must be allowed"


# ---------------------------------------------------------------------------
# Golden-path replay: every case is achievable with the real tools
# ---------------------------------------------------------------------------


def fill(name: str, matcher):
    """A concrete arg value that satisfies the matcher, or OMIT to leave the arg out."""
    if isinstance(matcher, AbsentOr):
        return OMIT
    if isinstance(matcher, OneOf):
        return matcher.one_of[0]
    if isinstance(matcher, AnyValue):
        return PLAUSIBLE[name]
    if isinstance(matcher, Contains):
        if name == "topic":
            return f"shoutout for {matcher.contains}"
        if name == "reason":
            return f"Posting {matcher.contains} links"
        return matcher.contains
    return matcher


def error_code(result) -> str | None:
    if not result.is_error:
        return None
    return json.loads(result.content[0].text)["error"]["code"]


def provenance_terms(call) -> list[str]:
    """Member IDs and $contains texts in a call. Each must come from somewhere the agent saw."""
    terms = []
    for matcher in call.args.values():
        if isinstance(matcher, Contains):
            terms.append(matcher.contains)
        for value in literal_values(matcher):
            if isinstance(value, str):
                terms += MEMBER_ID.findall(value)
    return terms


def replay(case: EvalCase) -> tuple[list[tuple[str, str | None, str | None]], list[str]]:
    """Run the probes, then the expected calls, on one fresh server.

    Returns (outcomes, untraceable). outcomes holds (call, expected error code, actual error
    code) for each call. untraceable lists member IDs and $contains texts in an expected call
    that appear nowhere in the request, the history or an earlier result: a chain's later call
    must be buildable from what came before it.
    """
    seen = [case.request] + [turn.content for turn in (case.setup.history if case.setup else [])]
    untraceable: list[str] = []

    async def run():
        outcomes = []
        async with Client(create_server()) as client:
            for probe in case.error_probes:
                result = await client.call_tool(probe.tool, dict(probe.args))
                outcomes.append((f"probe {probe.tool}", probe.error_code, error_code(result)))
            for call in case.expected_calls:
                known = " ".join(seen).casefold()
                untraceable.extend(t for t in provenance_terms(call) if t.casefold() not in known)
                args = {name: fill(name, m) for name, m in call.args.items()}
                args = {name: value for name, value in args.items() if value is not OMIT}
                result = await client.call_tool(call.tool, args)
                seen.append(result.content[0].text)
                outcomes.append(
                    (f"{call.tool}({args})", call.expect_error_code, error_code(result))
                )
        return outcomes

    return asyncio.run(run()), untraceable


REPLAYABLE = [case for case in CASES if case.expected_calls or case.error_probes]


@pytest.mark.parametrize("case", REPLAYABLE, ids=lambda case: case.id)
def test_golden_path_replay(case):
    outcomes, untraceable = replay(case)
    for call, expected_code, actual_code in outcomes:
        assert actual_code == expected_code, f"{call}: expected {expected_code}, got {actual_code}"
    assert untraceable == [], f"these come from no earlier message or result: {untraceable}"


# ---------------------------------------------------------------------------
# The human-readable view stays in sync
# ---------------------------------------------------------------------------


def test_cases_md_is_up_to_date():
    path = REPO_ROOT / "evals" / "CASES.md"
    assert path.read_text(encoding="utf-8") == render_markdown(CASES), (
        "evals/CASES.md is stale. Run: uv run python scripts/render_cases.py"
    )
