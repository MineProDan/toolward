"""The tool-count experiment: does a small model get worse when it sees more tools?

The same cases are run three times, with 3, 5 and 7 tools exposed. Every case in the set can be
solved with the 3 core tools alone, and no case mentions any other tool (not as an expected call,
an allowed extra, an error probe or a forbidden call). So the extra tools in the 5 and 7 tool
configurations are pure distractors, and any change in score comes from seeing more tools.

No-tool cases are included too: with more tools there are more ways to call one by mistake.
Adversarial cases are left out (they target the write tools). Holdout cases are included,
because this experiment doesn't tune anything.
"""

from toolward.evals.cases import READ_TOOLS, EvalCase
from toolward.server import TOOL_NAMES

CORE_TOOLS = ["lookup_member", "get_leaderboard", "get_automod_log"]
TOOL_SETS = {
    3: CORE_TOOLS,
    5: CORE_TOOLS + ["get_community_stats", "draft_announcement"],
    7: list(TOOL_NAMES),
}


def tools_mentioned(case: EvalCase) -> set[str]:
    """Every tool a case refers to, in any field."""
    extra = (
        set(READ_TOOLS) if case.allowed_extra_calls == "any_read" else set(case.allowed_extra_calls)
    )
    return (
        {call.tool for call in case.expected_calls}
        | {probe.tool for probe in case.error_probes}
        | {forbidden.tool for forbidden in case.must_not_call}
        | extra
    )


def tool_count_cases(cases: list[EvalCase]) -> list[EvalCase]:
    """The cases that need only the core tools and mention no other tool."""
    picked = []
    for case in cases:
        if case.category == "adversarial":
            continue
        if case.category == "no_tool":
            if not case.expected_calls:
                picked.append(case)
            continue
        mentioned = tools_mentioned(case)
        if case.expected_calls and mentioned <= set(CORE_TOOLS):
            picked.append(case)
    return picked
