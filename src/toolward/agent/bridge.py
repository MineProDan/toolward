"""The MCP side of the agent: connect to the server, list tools, call tools.

Two transports:
- "inprocess": Client(create_server()) talks to a server object in the same process. Fast, and
  each run gets a fresh server, so a ban in one eval run never leaks into the next.
- "stdio": starts `python -m toolward.server` as a subprocess, the way a real MCP host would.
  The subprocess also starts with fresh state.
"""

import json
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from mcp import Client, StdioServerParameters

from toolward.agent.schema import convert_tools
from toolward.server import create_server


@asynccontextmanager
async def connect(
    transport: str = "inprocess", server_factory: Callable = create_server
) -> AsyncIterator[Client]:
    if transport == "inprocess":
        target: Any = server_factory()
    elif transport == "stdio":
        target = StdioServerParameters(command=sys.executable, args=["-m", "toolward.server"])
    else:
        raise ValueError(f"unknown transport {transport!r}; use 'inprocess' or 'stdio'")
    async with Client(target) as client:
        yield client


async def list_ollama_tools(client: Client) -> list[dict]:
    """The server's tools, converted to Ollama's format."""
    return convert_tools((await client.list_tools()).tools)


def error_code_of(text: str) -> str | None:
    """The code in a JSON error body {"error": {"code": ...}}, or None for any other text."""
    try:
        body = json.loads(text)
    except ValueError:
        return None
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        code = body["error"].get("code")
        return code if isinstance(code, str) else None
    return None


async def call_tool(client: Client, name: str, args: dict[str, Any]) -> tuple[str, bool]:
    """Call one tool. Returns (result text, is_error)."""
    result = await client.call_tool(name, args)
    text = "\n".join(part.text for part in result.content if getattr(part, "text", None))
    return text, bool(result.is_error)
