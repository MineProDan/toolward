"""Write fixtures/community.json from the seeded generator.

Usage:
    uv run python scripts/make_fixtures.py          # regenerate the file
    uv run python scripts/make_fixtures.py --check  # exit 1 if the committed file is stale
"""

import argparse
import sys
from pathlib import Path

from toolward.data.generate import DEFAULT_SEED, generate, to_json

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "community.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare against the existing file instead of writing it",
    )
    args = parser.parse_args()

    text = to_json(generate(DEFAULT_SEED))
    if args.check:
        current = FIXTURE_PATH.read_text(encoding="utf-8") if FIXTURE_PATH.exists() else ""
        if current != text:
            print(f"{FIXTURE_PATH.name} is out of date. Run scripts/make_fixtures.py.")
            return 1
        print(f"{FIXTURE_PATH.name} is up to date.")
        return 0

    FIXTURE_PATH.write_text(text, encoding="utf-8")
    print(f"Wrote {FIXTURE_PATH} ({len(text.encode()) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
