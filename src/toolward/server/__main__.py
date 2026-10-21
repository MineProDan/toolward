"""Run the toolward MCP server over stdio: `uv run toolward-server` or `python -m toolward.server`.

Options:
    --fixtures PATH          serve a different fixtures file (default: fixtures/community.json)
    --tools a,b,c            expose only these tools (default: all 7)
    --descriptions VERSION   which tool description set to serve (default: V1)
    --confirm-mode MODE      how state-changing tools confirm (default: v1)
"""

import argparse
from pathlib import Path

from toolward.data.schema import load_community
from toolward.server.app import CONFIRM_MODES, TOOL_NAMES, create_server
from toolward.server.descriptions import DESCRIPTIONS


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the toolward MCP server over stdio.")
    parser.add_argument("--fixtures", type=Path, help="path to a community.json fixtures file")
    parser.add_argument("--tools", help=f"comma-separated subset of: {', '.join(TOOL_NAMES)}")
    parser.add_argument("--descriptions", choices=DESCRIPTIONS, default="V1")
    parser.add_argument("--confirm-mode", choices=CONFIRM_MODES, default="v1")
    args = parser.parse_args()

    community = load_community(args.fixtures) if args.fixtures else None
    tools = [name.strip() for name in args.tools.split(",")] if args.tools else None
    create_server(
        community=community,
        tools=tools,
        descriptions=DESCRIPTIONS[args.descriptions],
        confirm_mode=args.confirm_mode,
    ).run()


if __name__ == "__main__":
    main()
