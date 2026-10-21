"""Rewrite the generated results block in README.md from the committed results files.

Usage:
    uv run python scripts/update_readme_results.py           # rewrite the block
    uv run python scripts/update_readme_results.py --check   # exit 1 if the block is stale

The block sits between <!-- results:start --> and <!-- results:end -->. See
toolward.evals.readme for which results files it reads. tests/test_readme.py runs the same
check, so CI fails when the README and the recorded results disagree.
"""

import argparse
import sys
from pathlib import Path

from toolward.evals.readme import render_section, replace_section

README = Path(__file__).resolve().parent.parent / "README.md"


def main() -> int:
    parser = argparse.ArgumentParser(description="Update the README results block.")
    parser.add_argument("--check", action="store_true", help="only check, don't write")
    args = parser.parse_args()

    current = README.read_text(encoding="utf-8")
    updated = replace_section(current, render_section())
    if args.check:
        if updated != current:
            print(
                "README results block is stale. Run: uv run python scripts/update_readme_results.py"
            )
            return 1
        print("README results block is up to date.")
        return 0
    README.write_text(updated, encoding="utf-8")
    print(f"Wrote the results block in {README}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
