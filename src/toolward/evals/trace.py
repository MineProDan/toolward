"""The trace of one agent run, and reading/writing traces as JSON Lines.

A trace file (traces/*.jsonl) holds one Trace per line. A trace records everything needed to
grade the run and to replay it offline with MockModelClient:

- the run settings (model, digest, think, num_ctx, temperature, seed, versions),
- the messages the agent started with (system prompt, history, request),
- every model turn (text, thinking, tool calls with the raw arguments, timings),
- every tool execution (name, raw args, result text, is_error, error code),
- the final text, why the run stopped, flags, and the grades.

The full conversation is not stored a second time: conversation() rebuilds it from the
starting messages, the turns and the tool executions.
"""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

THINKING_LIMIT = 4000  # characters of thinking kept per turn
CONTEXT_MARGIN = 512  # context_near_limit when prompt_eval_count >= num_ctx - this


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any]  # exactly as the model produced them


class ModelTurn(BaseModel):
    """One response from the model."""

    content: str = ""
    thinking: str | None = None
    tool_calls: list[ToolCall] = []
    prompt_eval_count: int | None = None
    prompt_eval_duration: int | None = None  # nanoseconds, as Ollama reports them
    eval_count: int | None = None
    eval_duration: int | None = None
    total_duration: int | None = None
    load_duration: int | None = None
    done_reason: str | None = None
    wall_seconds: float = 0.0


class ToolExecution(BaseModel):
    turn: int  # index of the model turn that asked for this call
    name: str
    args: dict[str, Any]
    result_text: str
    is_error: bool
    error_code: str | None = None  # from the JSON error body; None if the text isn't JSON


class Trace(BaseModel):
    case_id: str | None = None
    run_index: int = 0
    timestamp: str = ""
    model: str
    model_digest: str | None = None  # first 12 hex characters, as `ollama list` shows it
    think: bool | None = None  # None = not sent (the model's default)
    num_ctx: int | None = None
    temperature: float | None = None
    seed: int | None = None
    num_predict: int | None = None  # per-reply token cap; None = no cap (baselines A and B)
    ollama_version: str | None = None
    prompt_version: str
    description_version: str
    confirm_mode: str = "v1"  # how ban_member/assign_role confirm; traces before Phase 6 are v1
    exposed_tools: list[str] | None = None  # tool names the model was given; None in older traces
    max_turns: int
    tools_sha: str = ""  # short hash of the tool definitions sent to the model
    messages: list[dict[str, Any]]  # starting messages: system prompt, history, request
    turns: list[ModelTurn] = []
    tool_executions: list[ToolExecution] = []
    final_text: str = ""
    stop_reason: Literal["answered", "max_turns", "length_limit", "error"] = "answered"
    error: str | None = None
    flags: dict[str, bool] = {}
    wall_seconds: float = 0.0
    grades: dict[str, Any] | None = None


def conversation(trace: Trace) -> list[dict[str, Any]]:
    """Rebuild the full message list the model saw by the end of the run."""
    messages = [dict(m) for m in trace.messages]
    for index, turn in enumerate(trace.turns):
        messages.append(assistant_message(turn))
        for execution in trace.tool_executions:
            if execution.turn == index:
                messages.append(tool_message(execution))
    return messages


def assistant_message(turn: ModelTurn) -> dict[str, Any]:
    """The assistant message we send back to the model after a turn."""
    message: dict[str, Any] = {"role": "assistant", "content": turn.content}
    if turn.thinking:
        message["thinking"] = turn.thinking
    if turn.tool_calls:
        message["tool_calls"] = [
            {"function": {"name": call.name, "arguments": call.arguments}}
            for call in turn.tool_calls
        ]
    return message


def tool_message(execution: ToolExecution) -> dict[str, Any]:
    return {"role": "tool", "tool_name": execution.name, "content": execution.result_text}


def write_trace(path: Path, trace: Trace) -> None:
    """Append one trace as a line of JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(trace.model_dump_json() + "\n")


def read_traces(path: str | Path) -> list[Trace]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [Trace.model_validate(json.loads(line)) for line in lines if line.strip()]
