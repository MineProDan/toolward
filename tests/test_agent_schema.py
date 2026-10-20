"""The MCP -> Ollama tool converter."""

import asyncio
import json

from mcp import Client

from toolward.agent.schema import convert_input_schema, convert_property, convert_tools
from toolward.server import TOOL_NAMES, create_server
from toolward.server.descriptions import DESCRIPTIONS_V1


def real_tools() -> list[dict]:
    async def run():
        async with Client(create_server()) as client:
            return convert_tools((await client.list_tools()).tools)

    return asyncio.run(run())


def test_optional_any_of_is_flattened_and_titles_dropped():
    prop = {
        "anyOf": [{"type": "string"}, {"type": "null"}],
        "default": None,
        "description": "An ID.",
        "title": "Member Id",
    }
    assert convert_property(prop) == {"type": "string", "description": "An ID."}


def test_enums_ranges_and_defaults_are_kept():
    prop = {
        "default": 10,
        "description": "How many.",
        "maximum": 25,
        "minimum": 1,
        "title": "Limit",
        "type": "integer",
    }
    assert convert_property(prop) == {
        "default": 10,
        "description": "How many.",
        "maximum": 25,
        "minimum": 1,
        "type": "integer",
    }
    enum = {"enum": ["a", "b"], "type": "string", "default": "a", "title": "X"}
    assert convert_property(enum) == {"enum": ["a", "b"], "type": "string", "default": "a"}


def test_optional_enum_keeps_the_inner_enum():
    prop = {"anyOf": [{"enum": ["x", "y"], "type": "string"}, {"type": "null"}], "default": None}
    assert convert_property(prop) == {"enum": ["x", "y"], "type": "string"}


def test_a_real_union_is_left_as_a_union_without_titles():
    prop = {"anyOf": [{"type": "string", "title": "A"}, {"type": "integer"}], "title": "U"}
    assert convert_property(prop) == {"anyOf": [{"type": "string"}, {"type": "integer"}]}


def test_required_and_object_shape():
    schema = {
        "type": "object",
        "title": "fArguments",
        "properties": {
            "topic": {"type": "string", "title": "Topic"},
            "note": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
        },
        "required": ["topic"],
    }
    assert convert_input_schema(schema) == {
        "type": "object",
        "properties": {"topic": {"type": "string"}, "note": {"type": "string"}},
        "required": ["topic"],
    }
    # No "required" key at all when nothing is required.
    assert "required" not in convert_input_schema({"type": "object", "properties": {}})


def test_all_real_tools_convert_cleanly():
    tools = {t["function"]["name"]: t for t in real_tools()}
    assert sorted(tools) == sorted(TOOL_NAMES)
    for name, tool in tools.items():
        assert tool["type"] == "function"
        assert tool["function"]["description"] == DESCRIPTIONS_V1[name]["description"]
        text = json.dumps(tool)
        assert '"title"' not in text and "anyOf" not in text and "null" not in text
        params = tool["function"]["parameters"]
        assert params["type"] == "object"
        for pname, prop in params["properties"].items():
            assert prop["type"] in ("string", "integer", "boolean")
            assert prop["description"] == DESCRIPTIONS_V1[name]["params"][pname]


def test_real_tool_details():
    tools = {t["function"]["name"]: t["function"]["parameters"] for t in real_tools()}
    assert "required" not in tools["lookup_member"]  # both member_id and name are optional
    assert tools["lookup_member"]["properties"]["member_id"]["type"] == "string"
    assert tools["ban_member"]["required"] == ["member_id", "reason"]
    assert tools["ban_member"]["properties"]["confirm"] == {
        "default": False,
        "description": DESCRIPTIONS_V1["ban_member"]["params"]["confirm"],
        "type": "boolean",
    }
    limit = tools["get_leaderboard"]["properties"]["limit"]
    assert (limit["minimum"], limit["maximum"], limit["default"]) == (1, 25, 10)
    assert tools["get_community_stats"]["properties"]["window"]["enum"][0] == "last_24h"
    assert "member_id" not in tools["get_automod_log"].get("required", [])
