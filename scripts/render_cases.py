"""Write evals/CASES.md, the human-readable view of evals/cases/*.json.

Usage:
    uv run python scripts/render_cases.py

Run it after editing any case. tests/test_eval_cases.py fails if CASES.md is out of date.
"""

from pathlib import Path

from toolward.evals.cases import load_cases
from toolward.evals.render import render_markdown

OUTPUT = Path(__file__).resolve().parent.parent / "evals" / "CASES.md"


def main() -> None:
    cases = load_cases()
    OUTPUT.write_text(render_markdown(cases), encoding="utf-8")
    print(f"Wrote {len(cases)} cases to {OUTPUT}")


if __name__ == "__main__":
    main()
