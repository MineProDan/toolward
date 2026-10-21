"""Write results/IMPROVED.md (the Phase 6 before/after report) from a manifest of results files.

Usage:
    uv run python scripts/make_comparison.py                       # results/improved_manifest.json
    uv run python scripts/make_comparison.py path/to/manifest.json --out path/to/report.md

The manifest says which results files make up each configuration:
    {"models": [{"label": "...", "v1": ["results/a.json", ...], "final": ["results/b.json"]}],
     "variance": {"V1": ["results/s42.json", "results/s43.json", "results/s44.json"],
                  "final": [...]}}
"""

import argparse
import json
from pathlib import Path

from toolward.evals.comparison import render

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Build results/IMPROVED.md.")
    parser.add_argument(
        "manifest", nargs="?", type=Path, default=REPO_ROOT / "results" / "improved_manifest.json"
    )
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "IMPROVED.md")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    args.out.write_text(render(manifest), encoding="utf-8")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
