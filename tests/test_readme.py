"""README.md's results block must match a fresh render from the committed results files."""

from pathlib import Path

import pytest

from toolward.evals.readme import RESULTS_END, RESULTS_START, render_section, replace_section

README = Path(__file__).resolve().parent.parent / "README.md"


def test_readme_results_block_is_up_to_date():
    current = README.read_text(encoding="utf-8")
    assert current.count(RESULTS_START) == 1 and current.count(RESULTS_END) == 1
    assert replace_section(current, render_section()) == current, (
        "README results block is stale. Run: uv run python scripts/update_readme_results.py"
    )


def test_replace_section_keeps_the_text_around_the_block():
    text = f"intro\n{RESULTS_START}\nold\n{RESULTS_END}\noutro\n"
    new = f"{RESULTS_START}\nnew\n{RESULTS_END}"
    assert replace_section(text, new) == f"intro\n{new}\noutro\n"


def test_replace_section_needs_both_markers():
    with pytest.raises(ValueError):
        replace_section("no markers here", "x")


def test_block_has_the_required_parts():
    section = render_section()
    for part in (
        "Before and after",
        "Sampled variance check",
        "thinking on",
        "Tool count",
        "results/TOOL_COUNT.md",
        "Unsafe executed",
    ):
        assert part in section, part


# The README is also the PyPI project page, which has no repo files and no Mermaid support.
REPO_RAW = "https://raw.githubusercontent.com/MineProDan/toolward/main/"


def test_readme_works_on_pypi():
    import re

    text = README.read_text(encoding="utf-8")
    assert "```mermaid" not in text, "PyPI can't render Mermaid; use docs/architecture.png"
    targets = re.findall(r"\]\(([^)\s]+)\)", text)
    relative = [t for t in targets if not t.startswith(("http://", "https://", "mailto:"))]
    assert relative == [], f"relative links break on PyPI: {relative}"


def test_architecture_image_exists_and_is_linked():
    image = README.parent / "docs" / "architecture.png"
    assert image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert (README.parent / "docs" / "architecture.mmd").read_text(encoding="utf-8").strip()
    assert f"{REPO_RAW}docs/architecture.png" in README.read_text(encoding="utf-8")
