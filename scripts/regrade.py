"""Recompute the grades of recorded runs with the current graders.

Usage:
    uv run python scripts/regrade.py results/a.json results/b.json ...

Only the derived `grades` fields change, in the results file and in its trace file. The model's
turns, the tool results and every other recorded value stay exactly as they were. Use this after
an approved change to the grading contract (see DECISIONS.md), then rebuild the report.
"""

import json
import sys
from pathlib import Path

from toolward.evals.cases import load_cases
from toolward.evals.graders import grade
from toolward.evals.trace import read_traces

REPO_ROOT = Path(__file__).resolve().parent.parent


def regrade(results_path: Path) -> None:
    cases = {case.id: case for case in load_cases()}
    results = json.loads(results_path.read_text(encoding="utf-8"))
    trace_path = REPO_ROOT / results["trace_file"]
    traces = read_traces(trace_path)

    changed = 0
    new_grades = {}
    for trace in traces:
        grades = grade(cases[trace.case_id], trace)
        changed += grades != trace.grades
        trace.grades = grades
        new_grades[(trace.case_id, trace.run_index)] = grades
    for row in results["runs"]:
        row["grades"] = new_grades[(row["case_id"], row["run_index"])]

    trace_path.write_text("".join(t.model_dump_json() + "\n" for t in traces), encoding="utf-8")
    results_path.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    print(f"{results_path.name}: {changed} of {len(traces)} runs got new grades")


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        regrade(Path(arg))
