"""Copy a small sample of recorded traces into traces/sample/ for the offline replay test.

Usage:
    uv run python scripts/make_sample_traces.py traces/a.jsonl traces/b.jsonl ...

For each trace file (one per configuration) it keeps one trace per category: the first case
ID in that category (sorted), run 0, skipping runs that ended in a model error. The sample is
written to traces/sample/<same file name>. tests/test_replay.py replays every sampled trace
with MockModelClient against a fresh server and checks the grades come out the same.
"""

import sys
from pathlib import Path

from toolward.evals.cases import CATEGORY_TARGETS, load_cases
from toolward.evals.trace import read_traces

REPO_ROOT = Path(__file__).resolve().parent.parent


def main(paths: list[str]) -> None:
    category_of = {case.id: case.category for case in load_cases()}
    out_dir = REPO_ROOT / "traces" / "sample"
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in map(Path, paths):
        traces = [t for t in read_traces(path) if t.run_index == 0 and t.stop_reason != "error"]
        picked = []
        for category in CATEGORY_TARGETS:
            in_category = sorted(
                (t for t in traces if category_of.get(t.case_id) == category),
                key=lambda t: t.case_id,
            )
            if in_category:
                picked.append(in_category[0])
        target = out_dir / path.name
        target.write_text("".join(t.model_dump_json() + "\n" for t in picked), encoding="utf-8")
        print(f"{target}: {len(picked)} traces ({', '.join(t.case_id for t in picked)})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    main(sys.argv[1:])
