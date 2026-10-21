"""Privacy scan: find things that must never be committed to this public repo.

Rules:
- long_number: a 17-20 digit number (the shape of a real Discord ID)
- email: an email address (only the owner's GitHub noreply address in pyproject.toml is allowed)
- token rules: Discord bot tokens, GitHub tokens, OpenAI-style keys, AWS access keys,
  Slack tokens and PEM private-key headers
- high_entropy: long random-looking base64 or hex strings (40+ characters)
- local_path: an absolute macOS or Windows home-folder path, which leaks a local username
- denylist: any entry from the local, git-ignored privacy_denylist.txt

Findings never include the full matched text, so the scan output is safe to share.
"""

import math
import os
import re
import subprocess
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

DENYLIST_FILENAME = "privacy_denylist.txt"

# Paths that are never scanned: the lock file is full of package hashes, and the denylist
# file holds exactly the identifiers we are looking for.
EXCLUDED_FILES = {"uv.lock", DENYLIST_FILENAME}
EXCLUDED_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}

PATTERNS: dict[str, re.Pattern[str]] = {
    "long_number": re.compile(r"(?<!\d)\d{17,20}(?!\d)"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"),
    "discord_token": re.compile(r"[\w-]{23,28}\.[\w-]{6,7}\.[\w-]{27,}"),
    "github_token": re.compile(r"\b(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    "private_key": re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----"),
    # Written with [r] so this source line doesn't match its own pattern.
    "local_path": re.compile(r"/Use[r]s/|\b[A-Za-z]:\\Use[r]s\\"),
}

BASE64_LIKE = re.compile(r"[A-Za-z0-9+/_-]{40,}={0,2}")
HEX_LIKE = re.compile(r"\b[0-9a-fA-F]{40,}\b")

# The one allowed email: the repo owner's GitHub noreply address, only in pyproject.toml.
ALLOWED_EMAIL = re.compile(r"^\d+\+[A-Za-z0-9-]+@users\.noreply\.github\.com$")
ALLOWED_EMAIL_FILE = "pyproject.toml"


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    detail: str  # a redacted hint, never the full match

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule} ({self.detail})"


def redact(text: str) -> str:
    """Show only the first 3 characters and the length of a match."""
    return f"{text[:3]}... ({len(text)} chars)"


def shannon_entropy(text: str) -> float:
    """Bits per character. Random base64 is about 5-6; English-like identifiers are lower."""
    counts = Counter(text)
    total = len(text)
    return -sum(n / total * math.log2(n / total) for n in counts.values())


def _looks_random(candidate: str) -> bool:
    """A long string with mixed character classes and high entropy, like a key or token."""
    body = candidate.rstrip("=")
    has_upper = any(c.isupper() for c in body)
    has_lower = any(c.islower() for c in body)
    has_digit = any(c.isdigit() for c in body)
    return has_upper and has_lower and has_digit and shannon_entropy(body) >= 4.3


def _looks_random_hex(candidate: str) -> bool:
    has_digit = any(c.isdigit() for c in candidate)
    has_letter = any(c.isalpha() for c in candidate)
    return has_digit and has_letter and shannon_entropy(candidate) >= 3.0


def load_denylist(path: Path) -> list[str]:
    """Read one entry per line, skipping blanks and # comments. Missing file means no entries."""
    if not path.exists():
        return []
    entries = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        entry = raw.strip()
        if entry and not entry.startswith("#"):
            entries.append(entry)
    return entries


def _denylist_patterns(denylist: Iterable[str]) -> list[tuple[int, re.Pattern[str]]]:
    """Case-insensitive whole-word matches, so a short entry doesn't match inside other words."""
    return [
        (number, re.compile(rf"(?<![A-Za-z0-9]){re.escape(entry)}(?![A-Za-z0-9])", re.IGNORECASE))
        for number, entry in enumerate(denylist, start=1)
    ]


def scan_text(text: str, path: str = "<text>", denylist: Iterable[str] = ()) -> list[Finding]:
    """Scan one file's text. `path` is used for reporting and the pyproject.toml allowance."""
    findings = []
    deny = _denylist_patterns(denylist)
    file_name = Path(path).name
    for line_number, line in enumerate(text.splitlines(), start=1):
        for rule, pattern in PATTERNS.items():
            for match in pattern.finditer(line):
                found = match.group(0)
                if (
                    rule == "email"
                    and file_name == ALLOWED_EMAIL_FILE
                    and ALLOWED_EMAIL.match(found)
                ):
                    continue
                findings.append(Finding(path, line_number, rule, redact(found)))
        for match in BASE64_LIKE.finditer(line):
            if _looks_random(match.group(0)):
                findings.append(Finding(path, line_number, "high_entropy", redact(match.group(0))))
        for match in HEX_LIKE.finditer(line):
            if _looks_random_hex(match.group(0)):
                findings.append(Finding(path, line_number, "high_entropy", redact(match.group(0))))
        for number, pattern in deny:
            if pattern.search(line):
                findings.append(Finding(path, line_number, "denylist", f"entry #{number}"))
    return findings


def _is_excluded(relative: Path) -> bool:
    return relative.name in EXCLUDED_FILES or any(part in EXCLUDED_DIRS for part in relative.parts)


def list_repo_files(root: Path) -> list[Path]:
    """Files git tracks plus untracked files that are not ignored (paths relative to root).

    Falls back to walking the folder when git is unavailable.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        paths = [Path(p) for p in result.stdout.split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        paths = []
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
            for name in files:
                paths.append((Path(folder) / name).relative_to(root))
    # Deleted-but-tracked files show up in ls-files; skip anything that no longer exists.
    return sorted(p for p in set(paths) if not _is_excluded(p) and (root / p).is_file())


def read_text_file(path: Path) -> str | None:
    """Return the file's text, or None for binary files."""
    data = path.read_bytes()
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def scan_repo(root: Path, denylist_path: Path | None = None) -> list[Finding]:
    """Scan every in-scope text file under root."""
    denylist = load_denylist(denylist_path or root / DENYLIST_FILENAME)
    findings = []
    for relative in list_repo_files(root):
        text = read_text_file(root / relative)
        if text is not None:
            findings.extend(scan_text(text, relative.as_posix(), denylist))
    return findings
