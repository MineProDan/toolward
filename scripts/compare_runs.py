"""Compare two results files case by case, for the Phase 6 changelog.

Usage:
    uv run python scripts/compare_runs.py results/before.json results/after.json

Prints a Markdown block: task success before -> after (exact fractions), unsafe-action runs
before -> after, per-category task success, and the cases that newly pass or newly fail. Only
cases present in both files are compared, so a dev-only run compares against dev rows only.
With k > 1 a case counts as passing only if every run passed.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

from toolward.evals.cases import CATEGORY_TARGETS
from toolward.evals.report import pct


def case_results(path: Path) -> tuple[dict[str, bool], dict[str, bool], dict[str, str]]:
    """(passed, unsafe, category) per case ID."""
    rows = json.loads(path.read_text(encoding="utf-8"))["runs"]
    passed: dict[str, bool] = defaultdict(lambda: True)
    unsafe: dict[str, bool] = defaultdict(bool)
    category: dict[str, str] = {}
    for row in rows:
        cid = row["case_id"]
        passed[cid] = passed[cid] and row["grades"]["task_success"]
        unsafe[cid] = unsafe[cid] or row["grades"]["unsafe_action"]
        category[cid] = row["category"]
    return dict(passed), dict(unsafe), category


def compare(before_path: Path, after_path: Path) -> str:
    before, before_unsafe, category = case_results(before_path)
    after, after_unsafe, _ = case_results(after_path)
    ids = sorted(set(before) & set(after))
    n = len(ids)
    lines = [
        f"- Task success: {pct(sum(before[c] for c in ids), n)} -> "
        f"{pct(sum(after[c] for c in ids), n)}",
        f"- Unsafe-action cases: {sum(before_unsafe[c] for c in ids)} -> "
        f"{sum(after_unsafe[c] for c in ids)}"
        + (
            f" (after: {', '.join(c for c in ids if after_unsafe[c])})"
            if any(after_unsafe[c] for c in ids)
            else ""
        ),
    ]
    per_category = []
    for cat in CATEGORY_TARGETS:
        in_cat = [c for c in ids if category[c] == cat]
        if not in_cat:
            continue
        b = sum(before[c] for c in in_cat)
        a = sum(after[c] for c in in_cat)
        delta = f"{a - b:+d}" if a != b else "0"
        per_category.append(f"{cat} {b}/{len(in_cat)} -> {a}/{len(in_cat)} ({delta})")
    lines.append("- Per category: " + "; ".join(per_category))
    newly_pass = [c for c in ids if after[c] and not before[c]]
    newly_fail = [c for c in ids if before[c] and not after[c]]
    lines.append(f"- Newly passing: {', '.join(newly_pass) or 'none'}")
    lines.append(f"- Newly failing: {', '.join(newly_fail) or 'none'}")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    print(compare(Path(sys.argv[1]), Path(sys.argv[2])))
