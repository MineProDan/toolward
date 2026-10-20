"""Scan the repo for real IDs, emails, tokens and denylisted names.

Usage:
    uv run python scripts/scan_for_secrets.py

Exits 1 if anything is found. Output shows file:line and the rule, never the full match.
"""

import sys
from pathlib import Path

from toolward.privacy import scan_repo

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    findings = scan_repo(REPO_ROOT)
    for finding in findings:
        print(finding)
    if findings:
        print(f"Privacy scan failed: {len(findings)} finding(s).")
        return 1
    print("Privacy scan clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
