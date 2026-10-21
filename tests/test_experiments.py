from toolward.evals.cases import load_cases
from toolward.evals.experiments import CORE_TOOLS, TOOL_SETS, tool_count_cases, tools_mentioned
from toolward.server import TOOL_NAMES

CASES = load_cases()
PICKED = tool_count_cases(CASES)


def test_tool_sets_grow_from_the_core():
    assert TOOL_SETS[3] == CORE_TOOLS
    assert set(TOOL_SETS[3]) < set(TOOL_SETS[5]) < set(TOOL_SETS[7]) == set(TOOL_NAMES)


def test_picked_cases_only_use_core_tools():
    for case in PICKED:
        if case.category != "no_tool":
            assert tools_mentioned(case) <= set(CORE_TOOLS), case.id
        assert case.category != "adversarial"


def test_the_case_set_is_stable():
    # The experiment's results are tied to this exact set; a case edit shouldn't change it silently.
    assert len(PICKED) == 26
    assert sum(case.category == "no_tool" for case in PICKED) == 6
    assert sum(case.split == "holdout" for case in PICKED) == 7
