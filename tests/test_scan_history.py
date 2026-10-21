"""The history scan's rules (scripts/scan_history.py), tested without touching git.

Planted values are built at runtime (by joining pieces) so this file never trips either scan.
"""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "scan_history.py"
spec = importlib.util.spec_from_file_location("scan_history", SCRIPT)
scan_history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan_history)

COMMIT = "abcdef1234567890"
NOREPLY = "12345+someuser" + "@" + "users.noreply.github.com"


def rules(findings) -> set[str]:
    return {f.rule for f in findings}


def test_blob_uses_the_tree_rules():
    text = "id " + "1" * 18 + "\npath /" + "Users/someone/x\n"
    findings = scan_history.scan_blob(text, COMMIT, "notes.md", [])
    assert rules(findings) == {"long_number", "local_path"}
    assert all(f.path == "abcdef1:notes.md" for f in findings)


def test_assistant_names_and_coauthor_trailers_are_flagged():
    for planted in ("made with " + "Cla" + "ude", "Co-" + "Authored-By: someone"):
        assert "attribution" in rules(scan_history.scan_blob(planted, COMMIT, "a.txt", []))
        message_findings = scan_history.scan_commit_text(planted, [NOREPLY], COMMIT, [])
        assert "attribution" in rules(message_findings)


def test_denylist_applies_to_files_and_messages():
    deny = ["SecretGuild"]
    assert rules(scan_history.scan_blob("hi SecretGuild", COMMIT, "a.md", deny)) == {"denylist"}
    message = scan_history.scan_commit_text("Add SecretGuild data", [NOREPLY], COMMIT, deny)
    assert rules(message) == {"denylist"}


def test_only_the_noreply_author_email_is_allowed():
    assert scan_history.scan_commit_text("Fix a test", [NOREPLY, NOREPLY], COMMIT, []) == []
    personal = "someone" + "@" + "example.org"
    (finding,) = scan_history.scan_commit_text("Fix a test", [personal], COMMIT, [])
    assert finding.rule == "email"
    assert personal not in str(finding)


def test_noreply_email_in_a_file_is_allowed_only_in_pyproject():
    line = 'email = "' + NOREPLY + '"'
    assert scan_history.scan_blob(line, COMMIT, "pyproject.toml", []) == []
    assert rules(scan_history.scan_blob(line, COMMIT, "README.md", [])) == {"email"}
