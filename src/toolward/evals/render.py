"""Render the eval cases as a Markdown page (evals/CASES.md) for people to review.

scripts/render_cases.py writes the file, and a test checks it matches the JSON.
"""

import json
from collections import Counter

from toolward.evals.cases import (
    CATEGORY_TARGETS,
    AbsentOr,
    AnyValue,
    Contains,
    EvalCase,
    ExpectedCall,
    ForbiddenCall,
    OneOf,
)

LEGEND = """\
How to read the call columns:

- `tool(arg="x")`: the arg must equal `"x"`. Enums, `role_name` and `name` ignore case.
- `arg~"x"`: a string containing `x`, ignoring case.
- `arg in [a, b]`: one of the values.
- `arg?=x`: omitted, or equal to `x` (the tool's default).
- `arg=*`: present, with any value.
- `!CODE`: this call is expected to fail with that error code.
- `A → B`: ordered, A must come before B. `A + B`: any order.
- `tool(*)` in "Must not call": any call to that tool.
- "Extra allowed" lists tools the agent may also call; `any_read` means any read-only tool.
"""


COLUMNS = [
    "ID",
    "Split",
    "Phrasing",
    "Request",
    "Expected",
    "Extra allowed",
    "Must not call",
    "Notes",
]


def _value(value) -> str:
    return json.dumps(value)


def _arg(name: str, matcher) -> str:
    if isinstance(matcher, AnyValue):
        return f"{name}=*"
    if isinstance(matcher, Contains):
        return f"{name}~{_value(matcher.contains)}"
    if isinstance(matcher, OneOf):
        return f"{name} in [{', '.join(_value(v) for v in matcher.one_of)}]"
    if isinstance(matcher, AbsentOr):
        return f"{name}?={_value(matcher.absent_or)}"
    return f"{name}={_value(matcher)}"


def short_call(call: ExpectedCall | ForbiddenCall) -> str:
    if isinstance(call, ForbiddenCall) and not call.args:
        return f"{call.tool}(*)"
    text = f"{call.tool}({', '.join(_arg(n, m) for n, m in call.args.items())})"
    if isinstance(call, ExpectedCall) and call.expect_error_code:
        text += f" !{call.expect_error_code}"
    return text


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _request(case: EvalCase) -> str:
    text = f'"{case.request}"'
    if case.setup:
        turns = " / ".join(f"{t.role}: {t.content}" for t in case.setup.history)
        text = f"(after: {turns}) {text}"
    return text


def _expected(case: EvalCase) -> str:
    joiner = " → " if case.ordered else " + "
    text = joiner.join(f"`{short_call(c)}`" for c in case.expected_calls) or "none"
    if case.must_ask_clarification:
        text += "; must ask a question"
    if case.must_refuse:
        text += "; must refuse"
    if case.error_probes:
        probes = ", ".join(
            f"`{p.tool}({', '.join(f'{k}={_value(v)}' for k, v in p.args.items())})"
            f" !{p.error_code}`"
            for p in case.error_probes
        )
        text += f"; natural failing call (not graded): {probes}"
    return text


def _extra(case: EvalCase) -> str:
    if case.allowed_extra_calls == "any_read":
        return "any_read"
    return ", ".join(case.allowed_extra_calls) or "none"


def render_markdown(cases: list[EvalCase]) -> str:
    counts = Counter(case.category for case in cases)
    holdout = sum(case.split == "holdout" for case in cases)
    non_plain = sum(case.phrasing != "plain" for case in cases)
    lines = [
        "# Eval cases",
        "",
        "Generated from `evals/cases/*.json` by `uv run python scripts/render_cases.py`. "
        "Don't edit this file by hand. The grading rules are in the docstring of "
        "`src/toolward/evals/cases.py`.",
        "",
        f"{len(cases)} cases, {holdout} of them held out (never used for tuning), "
        f"{non_plain} phrased casually, with typos or with slang.",
        "",
        "| Category | Cases | Holdout |",
        "|---|---|---|",
    ]
    for category in CATEGORY_TARGETS:
        held = sum(c.split == "holdout" for c in cases if c.category == category)
        lines.append(f"| {category} | {counts[category]} | {held} |")
    lines += ["", LEGEND]
    for category in CATEGORY_TARGETS:
        lines += [
            f"## {category}",
            "",
            "| " + " | ".join(COLUMNS) + " |",
            "|" + "---|" * len(COLUMNS),
        ]
        for case in cases:
            if case.category != category:
                continue
            forbidden = ", ".join(f"`{short_call(c)}`" for c in case.must_not_call) or "none"
            row = [
                case.id,
                case.split,
                case.phrasing,
                _request(case),
                _expected(case),
                _extra(case),
                forbidden,
                case.notes,
            ]
            lines.append("| " + " | ".join(_cell(cell) for cell in row) + " |")
        lines.append("")
    return "\n".join(lines)
