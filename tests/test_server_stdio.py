"""Launch the server as a subprocess and talk to it over stdio, the way the agent will."""

import asyncio
import json
import sys

from mcp import Client, StdioServerParameters


def test_stdio_server_lists_tools_and_answers():
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "toolward.server", "--tools", "lookup_member,get_leaderboard"],
    )

    async def run():
        async with Client(params) as client:
            tools = (await client.list_tools()).tools
            result = await client.call_tool("lookup_member", {"member_id": "mem_0009"})
            return tools, result

    tools, result = asyncio.run(run())
    assert sorted(t.name for t in tools) == ["get_leaderboard", "lookup_member"]
    assert not result.is_error
    assert json.loads(result.content[0].text)["prestige"] == 3


def test_stdio_server_serves_the_chosen_versions():
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "toolward.server",
            "--tools",
            "ban_member",
            "--descriptions",
            "V6",
            "--confirm-mode",
            "preview_token",
        ],
    )

    async def run():
        async with Client(params) as client:
            return (await client.list_tools()).tools

    [tool] = asyncio.run(run())
    assert "confirmation_id" in tool.input_schema["properties"]
    assert "lookup_member(name=...) first" in tool.description  # a V2+ description
