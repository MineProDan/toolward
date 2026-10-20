"""Build the toolward MCP server.

create_server() wires the plain functions in tools.py to MCP. Each server gets its own deep copy
of the community, so a ban in one server (one eval case) never leaks into another, and the
fixtures file is never written.

How errors reach the model: every tool returns a CallToolResult that we build ourselves. On
success it holds the output as JSON text plus structured_content. On a ToolFailure it holds
{"error": {"code", "message", "hint", "candidates"}} and is_error=True. We don't raise the SDK's
ToolError because the SDK then sends only plain text prefixed with "Error executing tool ...",
which is not valid JSON and has no structured_content. Returning the result directly gives the
model a clean JSON error body and still sets is_error. Argument-validation failures (for
example limit=99) are still caught by the SDK and come back as is_error with Pydantic's text.
"""

import json
from functools import cache
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, Field

from toolward.data.schema import Community, load_community
from toolward.server import tools as logic  # 'tools' is also a create_server argument
from toolward.server.descriptions import DESCRIPTIONS_V1
from toolward.server.models import (
    Audience,
    AutomodActionFilter,
    AutomodLimit,
    AutomodStatus,
    LeaderboardLimit,
    LeaderboardMetric,
    LeaderboardWindow,
    MaxChars,
    SinceHours,
    StatsWindow,
    Tone,
    ToolFailure,
)

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "community.json"

TOOL_NAMES = [
    "lookup_member",
    "get_leaderboard",
    "get_automod_log",
    "draft_announcement",
    "ban_member",
    "get_community_stats",
    "assign_role",
]

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
ANNOTATIONS = {
    "lookup_member": READ_ONLY,
    "get_leaderboard": READ_ONLY,
    "get_automod_log": READ_ONLY,
    "draft_announcement": READ_ONLY,  # returns text only; nothing is posted
    "ban_member": ToolAnnotations(
        read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False
    ),
    "get_community_stats": READ_ONLY,
    "assign_role": ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
    ),
}


@cache
def _load_fixture(path: Path) -> Community:
    """Parse and validate the fixtures once per process; callers deep-copy the result."""
    return load_community(path)


def _respond(run, *args, **kwargs) -> CallToolResult:
    """Call a tool function and turn its result or ToolFailure into a CallToolResult."""
    try:
        output: BaseModel = run(*args, **kwargs)
    except ToolFailure as failure:
        body = {"error": failure.error.model_dump(mode="json")}
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(body, ensure_ascii=False))],
            structured_content=body,
            is_error=True,
        )
    body = output.model_dump(mode="json")
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(body, ensure_ascii=False))],
        structured_content=body,
    )


# Each _make_* function returns the MCP-facing tool for one server. The parameter descriptions
# come from the chosen descriptions dict, so they have to be filled in when the tool is built.
# The functions are async so calls run on the event loop instead of worker threads; the tool
# logic itself is plain synchronous code.


def _make_lookup_member(state: Community, p: dict[str, str]):
    async def lookup_member(
        member_id: Annotated[str | None, Field(description=p["member_id"])] = None,
        name: Annotated[str | None, Field(description=p["name"])] = None,
    ) -> CallToolResult:
        return _respond(logic.lookup_member, state, member_id=member_id, name=name)

    return lookup_member


def _make_get_leaderboard(state: Community, p: dict[str, str]):
    async def get_leaderboard(
        metric: Annotated[LeaderboardMetric, Field(description=p["metric"])] = "xp",
        window: Annotated[LeaderboardWindow, Field(description=p["window"])] = "all_time",
        limit: Annotated[LeaderboardLimit, Field(description=p["limit"])] = 10,
    ) -> CallToolResult:
        return _respond(logic.get_leaderboard, state, metric=metric, window=window, limit=limit)

    return get_leaderboard


def _make_get_automod_log(state: Community, p: dict[str, str]):
    async def get_automod_log(
        status: Annotated[AutomodStatus, Field(description=p["status"])] = "open",
        action: Annotated[AutomodActionFilter, Field(description=p["action"])] = "any",
        member_id: Annotated[str | None, Field(description=p["member_id"])] = None,
        since_hours: Annotated[SinceHours, Field(description=p["since_hours"])] = 168,
        limit: Annotated[AutomodLimit, Field(description=p["limit"])] = 20,
    ) -> CallToolResult:
        return _respond(
            logic.get_automod_log,
            state,
            status=status,
            action=action,
            member_id=member_id,
            since_hours=since_hours,
            limit=limit,
        )

    return get_automod_log


def _make_draft_announcement(state: Community, p: dict[str, str]):
    async def draft_announcement(
        topic: Annotated[str, Field(description=p["topic"])],
        audience: Annotated[Audience, Field(description=p["audience"])] = "everyone",
        tone: Annotated[Tone, Field(description=p["tone"])] = "friendly",
        max_chars: Annotated[MaxChars, Field(description=p["max_chars"])] = 800,
    ) -> CallToolResult:
        return _respond(
            logic.draft_announcement,
            state,
            topic=topic,
            audience=audience,
            tone=tone,
            max_chars=max_chars,
        )

    return draft_announcement


def _make_ban_member(state: Community, p: dict[str, str]):
    async def ban_member(
        member_id: Annotated[str, Field(description=p["member_id"])],
        reason: Annotated[str, Field(description=p["reason"])],
        confirm: Annotated[bool, Field(description=p["confirm"])] = False,
    ) -> CallToolResult:
        return _respond(
            logic.ban_member, state, member_id=member_id, reason=reason, confirm=confirm
        )

    return ban_member


def _make_get_community_stats(state: Community, p: dict[str, str]):
    async def get_community_stats(
        window: Annotated[StatsWindow, Field(description=p["window"])] = "last_7d",
    ) -> CallToolResult:
        return _respond(logic.get_community_stats, state, window=window)

    return get_community_stats


def _make_assign_role(state: Community, p: dict[str, str]):
    async def assign_role(
        member_id: Annotated[str, Field(description=p["member_id"])],
        role_name: Annotated[str, Field(description=p["role_name"])],
        confirm: Annotated[bool, Field(description=p["confirm"])] = False,
    ) -> CallToolResult:
        return _respond(
            logic.assign_role, state, member_id=member_id, role_name=role_name, confirm=confirm
        )

    return assign_role


MAKERS = {
    "lookup_member": _make_lookup_member,
    "get_leaderboard": _make_get_leaderboard,
    "get_automod_log": _make_get_automod_log,
    "draft_announcement": _make_draft_announcement,
    "ban_member": _make_ban_member,
    "get_community_stats": _make_get_community_stats,
    "assign_role": _make_assign_role,
}


def create_server(
    community: Community | None = None,
    tools: list[str] | None = None,
    descriptions: dict[str, dict] = DESCRIPTIONS_V1,
) -> MCPServer:
    """Build a server with fresh in-memory state.

    community: the data to serve; defaults to fixtures/community.json. It is deep-copied, so
        the caller's object is never changed.
    tools: names of the tools to expose (for the 3/5/7-tool experiment); defaults to all 7.
    descriptions: which description set to use (DESCRIPTIONS_V1 is the baseline).
    """
    selected = TOOL_NAMES if tools is None else tools
    unknown = [name for name in selected if name not in MAKERS]
    if unknown:
        raise ValueError(f"Unknown tool name(s): {unknown}. Choose from {TOOL_NAMES}.")

    source = community if community is not None else _load_fixture(FIXTURE_PATH)
    state = source.model_copy(deep=True)

    server = MCPServer("toolward")
    for name in selected:
        text = descriptions[name]
        server.add_tool(
            MAKERS[name](state, text["params"]),
            name=name,
            description=text["description"],
            annotations=ANNOTATIONS[name],
        )
    return server
