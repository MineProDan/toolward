"""Run the toolward MCP server over stdio: `uv run toolward-server` or `python -m toolward.server`.

Options:
    --fixtures PATH   serve a different fixtures file (default: fixtures/community.json)
    --tools a,b,c     expose only these tools (default: all 7)
"""

import argparse
from pathlib import Path

from toolward.data.schema import load_community
from toolward.server.app import TOOL_NAMES, create_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the toolward MCP server over stdio.")
    parser.add_argument("--fixtures", type=Path, help="path to a community.json fixtures file")
    parser.add_argument("--tools", help=f"comma-separated subset of: {', '.join(TOOL_NAMES)}")
    args = parser.parse_args()

    community = load_community(args.fixtures) if args.fixtures else None
    tools = [name.strip() for name in args.tools.split(",")] if args.tools else None
    create_server(community=community, tools=tools).run()


if __name__ == "__main__":
    main()
