"""The agent loop: model -> tool calls -> results -> model, until the model answers.

The agent only ever sees the system prompt, the earlier conversation (history) and the request.
It never sees case metadata such as expected calls, category or notes.
"""

import asyncio
import copy
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from mcp import Client

from toolward.agent.bridge import call_tool, error_code_of, list_ollama_tools
from toolward.agent.models import ModelClient
from toolward.agent.prompts import SYSTEM_PROMPTS
from toolward.evals.trace import (
    CONTEXT_MARGIN,
    ToolExecution,
    Trace,
    assistant_message,
    tool_message,
)


@dataclass
class AgentConfig:
    max_turns: int = 6  # model calls per run, at most
    prompt_version: str = "V1"
    # The runner builds the server with these two, and both are recorded in every trace.
    description_version: str = "V1"
    confirm_mode: str = "v1"


def tools_sha(tools: list[dict]) -> str:
    """A short hash of the tool definitions, so two traces can be checked for the same tools."""
    text = json.dumps(tools, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def looks_like_text_tool_call(content: str, tool_names: list[str]) -> bool:
    """True when the model wrote a tool call as plain text instead of a real tool call.

    llama3.1 sometimes answers with text like {"name": "lookup_member", "parameters": {...}}.
    Such text is never executed; the run just records the flag.
    """
    text = content.strip().strip("`").strip()
    if re.search(r"<tool_call>|<function[=>]|<\|python_tag\|>|\[TOOL_CALLS\]", text):
        return True
    names = "|".join(re.escape(name) for name in tool_names)
    if not names:
        return False
    if re.search(rf'"name"\s*:\s*"({names})"', text):
        return True
    # A reply that starts with a call written like code: lookup_member(name="x")
    return re.match(rf"(json\s*)?({names})\s*\(", text) is not None


def build_messages(request: str, history: list[dict[str, str]], prompt_version: str) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPTS[prompt_version]}]
    messages += [{"role": turn["role"], "content": turn["content"]} for turn in history]
    messages.append({"role": "user", "content": request})
    return messages


async def run_agent(
    request: str,
    history: list[dict[str, str]],
    model_client: ModelClient,
    mcp_session: Client,
    config: AgentConfig | None = None,
    *,
    case_id: str | None = None,
    run_index: int = 0,
) -> Trace:
    """Run one conversation turn of the agent and return its full trace."""
    config = config or AgentConfig()
    started = time.perf_counter()
    tools = await list_ollama_tools(mcp_session)
    tool_names = [tool["function"]["name"] for tool in tools]
    start_messages = build_messages(request, history, config.prompt_version)

    trace = Trace(
        case_id=case_id,
        run_index=run_index,
        timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **model_client.info(),
        prompt_version=config.prompt_version,
        description_version=config.description_version,
        confirm_mode=config.confirm_mode,
        max_turns=config.max_turns,
        tools_sha=tools_sha(tools),
        messages=copy.deepcopy(start_messages),
        flags={"text_tool_call_suspected": False, "context_near_limit": False},
    )
    messages = list(start_messages)
    trace.stop_reason = "max_turns"

    for turn_index in range(config.max_turns):
        try:
            # The Ollama client is synchronous; run it in a thread so the in-process MCP
            # server's event loop isn't blocked.
            turn = await asyncio.to_thread(model_client.chat, messages, tools)
        except Exception as exc:  # noqa: BLE001 - any model failure ends the run as "error"
            trace.stop_reason = "error"
            trace.error = f"model call failed: {type(exc).__name__}: {exc}"
            break
        trace.turns.append(turn)
        if (
            trace.num_ctx
            and turn.prompt_eval_count is not None
            and turn.prompt_eval_count >= trace.num_ctx - CONTEXT_MARGIN
        ):
            trace.flags["context_near_limit"] = True
        if turn.done_reason == "length":
            # The reply hit num_predict before finishing, so it never answered or called a tool.
            trace.stop_reason = "length_limit"
            break
        messages.append(assistant_message(turn))

        if not turn.tool_calls:
            trace.final_text = turn.content
            trace.stop_reason = "answered"
            if looks_like_text_tool_call(turn.content, tool_names):
                trace.flags["text_tool_call_suspected"] = True
            break

        for call in turn.tool_calls:
            raw_args = copy.deepcopy(call.arguments)  # recorded before anything touches them
            try:
                text, is_error = await call_tool(mcp_session, call.name, dict(call.arguments))
            except Exception as exc:  # noqa: BLE001 - report it to the model like a tool error
                text, is_error = f"Tool call failed: {type(exc).__name__}: {exc}", True
            execution = ToolExecution(
                turn=turn_index,
                name=call.name,
                args=raw_args,
                result_text=text,
                is_error=is_error,
                error_code=error_code_of(text) if is_error else None,
            )
            trace.tool_executions.append(execution)
            messages.append(tool_message(execution))
        trace.final_text = turn.content  # in case the turn limit is hit after this turn

    trace.wall_seconds = round(time.perf_counter() - started, 3)
    return trace
