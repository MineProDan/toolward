"""Privacy scan tests.

Planted values are built at runtime (by joining pieces) so this file never trips the scan.
"""

import random
import string
from pathlib import Path

import pytest

from toolward.privacy import load_denylist, scan_repo, scan_text

REPO_ROOT = Path(__file__).resolve().parent.parent


def rules_found(text: str, path: str = "planted.txt", denylist=()) -> set[str]:
    return {finding.rule for finding in scan_text(text, path, denylist)}


def random_string(alphabet: str, length: int, seed: int) -> str:
    rng = random.Random(seed)
    return "".join(rng.choice(alphabet) for _ in range(length))


def test_whole_repo_is_clean():
    findings = scan_repo(REPO_ROOT)
    assert findings == [], "\n".join(str(f) for f in findings)


@pytest.mark.parametrize("digits", [17, 18, 19, 20])
def test_long_numbers_are_flagged(digits):
    planted = "member " + "1" + "2" * (digits - 1) + " joined"
    assert "long_number" in rules_found(planted)


@pytest.mark.parametrize("digits", [13, 16, 21])
def test_other_number_lengths_are_not_flagged(digits):
    assert "long_number" not in rules_found("x " + "9" * digits + " y")


def test_email_is_flagged():
    planted = "contact: someone" + "@" + "example.org"
    assert "email" in rules_found(planted)


def test_noreply_email_is_allowed_only_in_pyproject():
    planted = 'email = "12345+someuser' + "@" + 'users.noreply.github.com"'
    assert "email" not in rules_found(planted, "pyproject.toml")
    assert "email" in rules_found(planted, "README.md")


def test_discord_token_shape_is_flagged():
    planted = "A" * 24 + "." + "B" * 6 + "." + "C" * 27
    assert "discord_token" in rules_found(planted)


@pytest.mark.parametrize(
    ("planted", "rule"),
    [
        ("ghp" + "_" + "a1B2" * 9, "github_token"),
        ("github" + "_pat_" + "x9" * 15, "github_token"),
        ("sk" + "-" + "abc123XYZ" * 3, "openai_key"),
        ("AK" + "IA" + "ABCDEFGHIJKLMNOP", "aws_access_key"),
        ("xox" + "b-" + "1234567890-abcdef", "slack_token"),
        ("-----BEGIN " + "RSA PRIVATE" + " KEY-----", "private_key"),
        ("-----BEGIN " + "PRIVATE" + " KEY-----", "private_key"),
    ],
)
def test_token_shapes_are_flagged(planted, rule):
    assert rule in rules_found("value = " + planted)


def test_high_entropy_base64_is_flagged():
    alphabet = string.ascii_letters + string.digits + "+/"
    planted = random_string(alphabet, 48, seed=1)
    assert "high_entropy" in rules_found("secret = " + planted)


def test_high_entropy_hex_is_flagged():
    planted = random_string("0123456789abcdef", 40, seed=2)
    assert "high_entropy" in rules_found("digest " + planted)


def test_long_ordinary_identifiers_are_not_flagged():
    text = "def test_every_documented_edge_case_exists_in_the_committed_fixtures():"
    assert rules_found(text) == set()


def test_findings_do_not_print_the_secret():
    planted = "ghp" + "_" + "a1B2" * 9
    (finding,) = scan_text(planted, "planted.txt")
    assert planted not in str(finding)


def test_denylist_matches_case_insensitively(tmp_path):
    denylist_file = tmp_path / "privacy_denylist.txt"
    denylist_file.write_text("# real names go here\n\nSecretGuild\nrealuser42\n", encoding="utf-8")
    entries = load_denylist(denylist_file)
    assert entries == ["SecretGuild", "realuser42"]

    assert "denylist" in rules_found("welcome to secretguild!", denylist=entries)
    assert "denylist" in rules_found("by REALUSER42", denylist=entries)
    # Whole words only: an entry inside a longer word is not a match.
    assert "denylist" not in rules_found("notrealuser42x", denylist=entries)


def test_denylist_entry_is_not_printed(tmp_path):
    (finding,) = scan_text("hello SecretGuild", "a.txt", ["SecretGuild"])
    assert "SecretGuild" not in str(finding)
    assert finding.detail == "entry #1"


def test_missing_denylist_is_fine(tmp_path):
    assert load_denylist(tmp_path / "does_not_exist.txt") == []


def test_scan_repo_uses_the_denylist_file(tmp_path):
    (tmp_path / "notes.md").write_text("Planning with SecretGuild staff.\n", encoding="utf-8")
    (tmp_path / "privacy_denylist.txt").write_text("SecretGuild\n", encoding="utf-8")
    findings = scan_repo(tmp_path)
    # The denylist file itself is never scanned; the note is.
    assert [(f.path, f.rule) for f in findings] == [("notes.md", "denylist")]


def test_scan_repo_skips_uv_lock_and_binary_files(tmp_path):
    (tmp_path / "uv.lock").write_text("hash = " + "1" * 18 + "\n", encoding="utf-8")
    (tmp_path / "image.bin").write_bytes(b"\0\1\2" + b"1" * 18)
    assert scan_repo(tmp_path) == []
