"""The runner (with a scripted mock model) and the report built from its results."""

import json

import pytest

from toolward.evals.cases import load_cases
from toolward.evals.report import metrics, pct, render_report, top_reasons, variance
from toolward.evals.runner import run_evals, run_name, select_cases
from toolward.evals.trace import ModelTurn, ToolCall, read_traces

CASES = {case.id: case for case in load_cases()}


class ScriptedModel:
    """Answers each request from a fixed script of turns. Works for any number of runs."""

    def __init__(self, scripts: dict[str, list[ModelTurn]]):
        self.scripts = scripts

    def info(self):
        return {
            "model": "scripted",
            "model_digest": "000000000000",
            "think": False,
            "num_ctx": 8192,
            "temperature": 0.0,
            "seed": 42,
            "ollama_version": "test",
        }

    def chat(self, messages, tools):
        last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
        turn_index = sum(m["role"] == "assistant" for m in messages[last_user:])
        return self.scripts[messages[last_user]["content"]][turn_index].model_copy(deep=True)


def turn(*pairs, text="") -> ModelTurn:
    return ModelTurn(content=text, tool_calls=[ToolCall(name=n, arguments=a) for n, a in pairs])


SCRIPTS = {
    # safe_07: the confirmed ban (expected). Every run must start from an unbanned member.
    CASES["safe_07"].request: [
        turn(("ban_member", {"member_id": "mem_0093", "reason": "scam links", "confirm": True})),
        turn(text="Done, Island6 is banned."),
    ],
    # notool_01: a greeting answered with a needless lookup (fails).
    CASES["notool_01"].request: [
        turn(("lookup_member", {"name": "Nebula9"})),
        turn(text="Hi!"),
    ],
}


@pytest.fixture(scope="module")
def outputs(tmp_path_factory):
    out = tmp_path_factory.mktemp("run")
    cases = select_cases(load_cases(), ids=["safe_07", "notool_01"])
    lines: list[str] = []
    trace_path, results_path = run_evals(
        cases, ScriptedModel(SCRIPTS), k=2, out_dir=out, name="test_run", progress=lines.append
    )
    return trace_path, results_path, lines


def test_runner_writes_traces_and_results(outputs):
    trace_path, results_path, lines = outputs
    traces = read_traces(trace_path)
    assert [(t.case_id, t.run_index) for t in traces] == [
        ("notool_01", 0),
        ("safe_07", 0),
        ("notool_01", 1),
        ("safe_07", 1),
    ]
    results = json.loads(results_path.read_text())
    assert results["settings"]["k"] == 2 and results["settings"]["model"] == "scripted"
    assert results["trace_file"] == "traces/test_run.jsonl"
    assert len(results["runs"]) == 4 and len(lines) == 4
    by_case = {(r["case_id"], r["run_index"]): r for r in results["runs"]}
    assert by_case[("safe_07", 1)]["grades"]["task_success"] is True
    assert by_case[("notool_01", 0)]["grades"]["reasons"] == ["extra call: lookup_member"]


def test_every_run_gets_a_fresh_server(outputs):
    trace_path, _, _ = outputs
    bans = [t for t in read_traces(trace_path) if t.case_id == "safe_07"]
    # If state leaked, the second ban would fail with ALREADY_BANNED.
    assert [t.tool_executions[0].is_error for t in bans] == [False, False]


def test_select_cases():
    cases = load_cases()
    assert len(select_cases(cases, "holdout")) == 10
    assert len(select_cases(cases, "dev")) == 48
    assert len(select_cases(cases, "core")) == 58
    adversarial = select_cases(cases, "adversarial")
    assert adversarial and all(c.id.startswith("adv_") for c in adversarial)
    assert len(select_cases(cases, "all")) == 58 + len(adversarial)
    with pytest.raises(ValueError, match="split"):
        select_cases(cases, "train")
    assert [c.id for c in select_cases(cases, "all", ["sel_01"])] == ["sel_01"]
    with pytest.raises(ValueError):
        select_cases(cases, "all", ["nope_01"])


def test_run_name_is_file_safe():
    from datetime import datetime

    name = run_name("qwen3:8b", None, datetime(2026, 10, 19, 15, 30, 12))
    assert name == "qwen3-8b_default_20261019T153012"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def row(case_id, run_index, success, split="dev", category="tool_selection", **grades):
    base = {
        "tool_selection_ok": success,
        "args_ok": success,
        "order_ok": None,
        "expected_ok": success,
        "extra_call": False,
        "forbidden_call": False,
        "unsafe_action": False,
        "clarification_ok": None,
        "refusal_ok": None,
        "task_success": success,
        "reasons": [] if success else ["missing call: lookup_member"],
        "details": [],
    }
    return {
        "case_id": case_id,
        "category": category,
        "split": split,
        "run_index": run_index,
        "turns": 2,
        "tool_calls": 1,
        "wall_seconds": 3.0,
        "max_prompt_eval_count": 1900,
        "stop_reason": "answered",
        "flags": {"text_tool_call_suspected": False, "context_near_limit": False},
        "grades": base | grades,
    }


def test_pct_is_exact():
    assert pct(41, 58) == "41/58 (70.7%)"
    assert pct(0, 0) == "n/a"
    assert pct(2, 3) == "2/3 (66.7%)"


def test_metrics_denominators():
    rows = [
        row("a", 0, True),
        row("a", 1, False, args_ok=None),  # right tool not called: not in the args denominator
        row("b", 0, False, unsafe_action=True, category="safety", refusal_ok=False),
    ]
    m = metrics(rows)
    assert m["task_success"] == "1/3 (33.3%)"
    assert m["args"] == "1/2 (50.0%)"
    assert m["refusal"] == "0/1 (0.0%)"
    assert m["unsafe"] == "1/3 (33.3%)"
    assert m["clarification"] == "n/a"


def test_variance():
    rows = [row("a", 0, True), row("a", 1, False), row("b", 0, True), row("b", 1, True)]
    v = variance(rows, k=2)
    assert v["inconsistent"] == ["a"]
    assert v["rates"] == {0: 1.0, 1: 0.5}
    assert v["std"] == pytest.approx(0.25)


def test_top_reasons_count_each_run_once():
    rows = [row("a", 0, False), row("b", 0, False), row("c", 0, True)]
    rows[0]["grades"]["reasons"] = ["extra call: x", "extra call: x"]
    rows[1]["grades"]["reasons"] = ["extra call: x"]
    assert top_reasons(rows) == [("extra call: x", 2, ["a", "b"])]


def test_render_report_has_every_section(outputs):
    _, results_path, _ = outputs
    text = render_report([json.loads(results_path.read_text())])
    for heading in [
        "## Side by side",
        "## Environment",
        "### Overall",
        "### Per category",
        "### Variance across K=2",
        "### Failed cases",
        "## Per-case task success",
    ]:
        assert heading in text
    assert "| notool_01 | dev | 0/2 | extra call: lookup_member |" in text
    assert "2/4 (50.0%)" in text


def test_improved_report_is_up_to_date():
    """results/IMPROVED.md is generated from the manifest; it must match a fresh render."""
    from pathlib import Path

    from toolward.evals.comparison import render

    root = Path(__file__).resolve().parent.parent
    manifest = root / "results" / "improved_manifest.json"
    if not manifest.exists():
        pytest.skip("no Phase 6 manifest yet")
    expected = render(json.loads(manifest.read_text(encoding="utf-8")))
    assert (root / "results" / "IMPROVED.md").read_text(encoding="utf-8") == expected, (
        "results/IMPROVED.md is stale. Run: uv run python scripts/make_comparison.py"
    )
