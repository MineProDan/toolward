"""Write results/BASELINE.md from results files.

Usage:
    uv run python scripts/make_report.py results/a.json results/b.json ...
    uv run python scripts/make_report.py            # every results/*.json, oldest first

Options:
    --out PATH     where to write (default: results/BASELINE.md)
    --title TEXT   the report heading (default: "Baseline results")
"""

import argparse
from pathlib import Path

from toolward.evals.report import load_results, render_report

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the results report.")
    parser.add_argument("results", nargs="*", type=Path, help="results/*.json files")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "BASELINE.md")
    parser.add_argument("--title", default="Baseline results")
    args = parser.parse_args()

    paths = args.results or sorted(
        (REPO_ROOT / "results").glob("*.json"), key=lambda p: p.stat().st_mtime
    )
    if not paths:
        raise SystemExit("No results files found. Run scripts/run_evals.py first.")
    args.out.write_text(render_report(load_results(paths), args.title), encoding="utf-8")
    print(f"Wrote {args.out} from {len(paths)} results file(s).")


if __name__ == "__main__":
    main()
