"""Re-render docs/architecture.png from docs/architecture.mmd.

Usage:
    uv run python scripts/render_diagram.py

The README shows the architecture as a PNG, not a Mermaid block, because PyPI's project page
doesn't render Mermaid. This sends the diagram text (synthetic, nothing private) to mermaid.ink,
the Mermaid project's public renderer, and saves the PNG it returns. Needs network access.
"""

import base64
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "docs" / "architecture.mmd"
OUTPUT = REPO_ROOT / "docs" / "architecture.png"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def main() -> None:
    code = base64.urlsafe_b64encode(SOURCE.read_bytes()).decode()
    url = f"https://mermaid.ink/img/{code}?type=png&bgColor=FFFFFF&width=1600"
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read()
    if not data.startswith(PNG_MAGIC):
        raise SystemExit(f"mermaid.ink didn't return a PNG: {data[:200]!r}")
    OUTPUT.write_bytes(data)
    print(f"Wrote {OUTPUT} ({len(data) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
