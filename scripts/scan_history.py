"""Scan every commit reachable from any ref (the full git history) before publishing.

Usage:
    uv run python scripts/scan_history.py

The working-tree scan (scripts/scan_for_secrets.py) only sees today's files. A value that was
committed once and deleted later is still in the history and would be published by a push. This
script checks every file version in every commit reachable from all refs, plus every commit
message and author/committer line, with:

- the same rules as the tree scan (toolward.privacy): 17-20 digit numbers, emails (only the
  owner's GitHub noreply address is allowed, in pyproject.toml and as the commit author),
  token shapes, high-entropy strings, absolute home-folder paths, and the local, git-ignored
  privacy_denylist.txt;
- one history-only rule, "attribution": an AI assistant's name or a co-author trailer in any
  file version or commit message. It is history-only because an existing commit can't be fixed
  without rewriting history, so it is reported here for a person to judge instead of blocking
  every new commit.

Uncommitted changes aren't in the history yet; run this again after committing.

It only reads (git rev-list, ls-tree, cat-file, log). Exits 1 if anything is found. Output never
shows the full matched text.
"""

import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

from toolward.privacy import (
    ALLOWED_EMAIL,
    DENYLIST_FILENAME,
    EXCLUDED_FILES,
    Finding,
    load_denylist,
    redact,
    scan_text,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Written with [a] and [e] so this file doesn't match its own patterns.
HISTORY_PATTERNS = {
    "attribution": re.compile(r"cl[a]ude|co-author[e]d-by", re.IGNORECASE),
}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout


def history_findings(text: str, where: str) -> list[Finding]:
    found = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for rule, pattern in HISTORY_PATTERNS.items():
            for match in pattern.finditer(line):
                found.append(Finding(where, line_number, rule, redact(match.group(0))))
    return found


def scan_blob(text: str, commit: str, path: str, denylist: Iterable[str]) -> list[Finding]:
    """All rules on one file version. `path` decides the pyproject.toml email allowance."""
    where = f"{commit[:7]}:{path}"
    findings = [Finding(where, f.line, f.rule, f.detail) for f in scan_text(text, path, denylist)]
    return findings + history_findings(text, where)


def scan_commit_text(message: str, people: list[str], commit: str, denylist: Iterable[str]):
    """The commit message, and the author/committer emails (noreply address allowed)."""
    where = f"{commit[:7]}:<commit message>"
    findings = scan_text(message, where, denylist) + history_findings(message, where)
    for email in people:
        if not ALLOWED_EMAIL.match(email):
            findings.append(Finding(f"{commit[:7]}:<author>", 0, "email", redact(email)))
    return findings


def read_blob(sha: str) -> str | None:
    data = subprocess.run(
        ["git", "cat-file", "blob", sha], cwd=REPO_ROOT, capture_output=True, check=True
    ).stdout
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def scan_history() -> tuple[list[Finding], int, int]:
    denylist = load_denylist(REPO_ROOT / DENYLIST_FILENAME)
    commits = git("rev-list", "--all", "--reverse").split()
    findings: list[Finding] = []
    seen_blobs: set[str] = set()
    for commit in commits:
        message = git("log", "-1", "--format=%B", commit)
        people = git("log", "-1", "--format=%ae%n%ce", commit).split()
        findings += scan_commit_text(message, people, commit, denylist)
        for entry in git("ls-tree", "-r", "-z", commit).split("\0"):
            if not entry:
                continue
            meta, path = entry.split("\t", 1)
            _mode, kind, sha = meta.split()
            # Each file version is scanned once, in the first commit that has it.
            if kind != "blob" or sha in seen_blobs or Path(path).name in EXCLUDED_FILES:
                continue
            seen_blobs.add(sha)
            text = read_blob(sha)
            if text is not None:
                findings += scan_blob(text, commit, path, denylist)
    return findings, len(commits), len(seen_blobs)


def main() -> int:
    findings, commits, blobs = scan_history()
    for finding in findings:
        print(finding)
    if not (REPO_ROOT / DENYLIST_FILENAME).exists():
        print(f"Note: {DENYLIST_FILENAME} doesn't exist, so no real names were checked.")
    print(f"Scanned {commits} commit(s) and {blobs} file version(s) reachable from all refs.")
    if findings:
        print(f"History scan failed: {len(findings)} finding(s).")
        return 1
    print("History scan clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
