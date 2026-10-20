"""The agent loop, run offline with MockModelClient against a real in-process server."""

import asyncio
import json
from types import SimpleNamespace

from ollama import ChatResponse, Message

from toolward.agent.bridge import connect
from toolward.agent.loop import AgentConfig, looks_like_text_tool_call, run_agent
from toolward.agent.models import MockModelClient, OllamaClient
from toolward.agent.prompts import SYSTEM_PROMPT_V1
from toolward.evals.cases import load_cases
from toolward.evals.runner import run_case
from toolward.evals.trace import THINKING_LIMIT, ModelTurn, ToolCall, Trace, conversation
from toolward.server import TOOL_NAMES


def recorded(*turns: ModelTurn, **fields) -> Trace:
    """A recorded trace holding just the model turns the mock should replay."""
    return Trace(
        model="mock",
        model_digest="000000000000",
        think=False,
        num_ctx=8192,
        temperature=0.0,
        seed=42,
        prompt_version="V1",
        description_version="V1",
        max_turns=6,
        messages=[],
        turns=list(turns),
        **fields,
    )


def calls(*pairs) -> ModelTurn:
    return ModelTurn(tool_calls=[ToolCall(name=name, arguments=args) for name, args in pairs])


def answer(text: str, **fields) -> ModelTurn:
    return ModelTurn(content=text, **fields)


def run(trace: Trace, request="Does Island6 have open flags?", history=(), max_turns=6):
    mock = MockModelClient(trace)

    async def go():
        async with connect("inprocess") as session:
            return await run_agent(
                request, list(history), mock, session, AgentConfig(max_turns=max_turns)
            )

    return asyncio.run(go()), mock


CHAIN = recorded(
    calls(("lookup_member", {"name": "Island6"})),
    calls(("get_automod_log", {"member_id": "mem_0093", "status": "open"})),
    answer("Island6 (mem_0093) has 3 open AutoMod events."),
)


def test_chain_runs_against_the_real_server():
    trace, mock = run(CHAIN)
    assert mock.finished
    assert trace.stop_reason == "answered"
    assert trace.final_text == "Island6 (mem_0093) has 3 open AutoMod events."
    assert [e.name for e in trace.tool_executions] == ["lookup_member", "get_automod_log"]
    assert [e.turn for e in trace.tool_executions] == [0, 1]
    assert not any(e.is_error for e in trace.tool_executions)
    assert json.loads(trace.tool_executions[0].result_text)["member_id"] == "mem_0093"
    log = json.loads(trace.tool_executions[1].result_text)
    assert {event["member_id"] for event in log["events"]} == {"mem_0093"}


def test_trace_records_settings_and_starting_messages():
    trace, _ = run(CHAIN)
    assert trace.model == "mock" and trace.think is False and trace.num_ctx == 8192
    assert trace.prompt_version == "V1" and trace.description_version == "V1"
    assert trace.max_turns == 6 and len(trace.tools_sha) == 12
    assert trace.messages == [
        {"role": "system", "content": SYSTEM_PROMPT_V1},
        {"role": "user", "content": "Does Island6 have open flags?"},
    ]
    assert trace.flags == {"text_tool_call_suspected": False, "context_near_limit": False}


def test_conversation_is_rebuilt_in_order():
    trace, _ = run(CHAIN)
    roles = [m["role"] for m in conversation(trace)]
    assert roles == ["system", "user", "assistant", "tool", "assistant", "tool", "assistant"]
    tool_msg = conversation(trace)[3]
    assert tool_msg["tool_name"] == "lookup_member"
    assert tool_msg["content"] == trace.tool_executions[0].result_text


def test_history_goes_before_the_request():
    history = [
        {"role": "user", "content": "What level is Nebula9?"},
        {"role": "assistant", "content": "Level 31."},
    ]
    trace, _ = run(recorded(answer("Prestige 3.")), request="what prestige?", history=history)
    assert [m["role"] for m in trace.messages] == ["system", "user", "assistant", "user"]
    assert trace.messages[1:3] == history


def test_raw_args_are_recorded_before_coercion():
    trace, _ = run(recorded(calls(("get_leaderboard", {"limit": "3"})), answer("ok")))
    execution = trace.tool_executions[0]
    assert execution.args == {"limit": "3"}  # still a string; the server coerces its own copy
    assert not execution.is_error
    assert len(json.loads(execution.result_text)["entries"]) == 3


def test_several_calls_in_one_turn():
    turn = calls(
        ("get_community_stats", {"window": "last_7d"}),
        ("get_community_stats", {"window": "previous_7d"}),
    )
    trace, _ = run(recorded(turn, answer("Compared.")))
    assert [e.args["window"] for e in trace.tool_executions] == ["last_7d", "previous_7d"]
    assert [e.turn for e in trace.tool_executions] == [0, 0]


def test_tool_errors_are_recorded_with_their_code():
    trace, _ = run(recorded(calls(("lookup_member", {"name": "quietfern"})), answer("Which one?")))
    execution = trace.tool_executions[0]
    assert execution.is_error and execution.error_code == "AMBIGUOUS_NAME"


def test_validation_errors_and_unknown_tools_have_no_code():
    turn = calls(("get_leaderboard", {"limit": 99}), ("kick_member", {"member_id": "mem_0001"}))
    trace, _ = run(recorded(turn, answer("Sorry.")))
    assert [(e.is_error, e.error_code) for e in trace.tool_executions] == [
        (True, None),
        (True, None),
    ]


def test_turn_limit():
    trace, mock = run(CHAIN, max_turns=2)
    assert trace.stop_reason == "max_turns"
    assert len(trace.turns) == 2 and len(trace.tool_executions) == 2
    assert trace.final_text == ""
    assert not mock.finished


def test_reply_that_hits_the_token_cap_ends_the_run():
    capped = recorded(answer("still thinking...", done_reason="length"), answer("never reached"))
    trace, mock = run(capped)
    assert trace.stop_reason == "length_limit"
    assert len(trace.turns) == 1 and trace.final_text == ""
    assert not mock.finished


def test_model_failure_ends_the_run_as_error():
    trace, _ = run(recorded())  # nothing to replay, so the first chat() raises
    assert trace.stop_reason == "error"
    assert "ReplayMismatch" in trace.error


def test_text_tool_call_is_flagged_and_not_executed():
    text = '{"name": "ban_member", "parameters": {"member_id": "mem_0093", "confirm": true}}'
    trace, _ = run(recorded(answer(text)))
    assert trace.flags["text_tool_call_suspected"] is True
    assert trace.tool_executions == []
    assert trace.final_text == text


def test_context_near_limit_flag():
    trace, _ = run(recorded(answer("hi", prompt_eval_count=7700)))
    assert trace.flags["context_near_limit"] is True
    trace, _ = run(recorded(answer("hi", prompt_eval_count=7679)))
    assert trace.flags["context_near_limit"] is False


def test_text_tool_call_detector():
    names = TOOL_NAMES
    assert looks_like_text_tool_call('{"name": "lookup_member", "parameters": {}}', names)
    assert looks_like_text_tool_call('```json\n{"name":"get_leaderboard"}\n```', names)
    assert looks_like_text_tool_call('<|python_tag|>lookup_member.call(name="x")', names)
    assert looks_like_text_tool_call('lookup_member(name="Nebula9")', names)
    assert looks_like_text_tool_call("<tool_call>\n{...}\n</tool_call>", names)
    assert not looks_like_text_tool_call("Hello! How can I help?", names)
    assert not looks_like_text_tool_call("I can look members up with lookup_member.", names)
    assert not looks_like_text_tool_call('The member is called "name".', names)


def test_agent_never_sees_case_metadata():
    case = next(c for c in load_cases() if c.id == "safe_07")
    turns = [answer("I need to check first. Which member?")]
    trace = asyncio.run(run_case(case, 0, MockModelClient(recorded(*turns)), AgentConfig()))
    sent = json.dumps(trace.messages)
    assert case.notes not in sent and "expected_calls" not in sent and "safety" not in sent
    assert [m["content"] for m in trace.messages[1:]] == [
        *(t.content for t in case.setup.history),
        case.request,
    ]
    assert trace.case_id == "safe_07" and trace.grades is not None


# ---------------------------------------------------------------------------
# OllamaClient, with the HTTP call replaced (no Ollama needed)
# ---------------------------------------------------------------------------


def fake_ollama(client: OllamaClient, response: ChatResponse) -> list[dict]:
    sent: list[dict] = []

    def chat(**kwargs):
        sent.append(kwargs)
        return response

    client._client = SimpleNamespace(chat=chat)
    return sent


def tool_response(thinking=None) -> ChatResponse:
    call = Message.ToolCall(
        function=Message.ToolCall.Function(name="lookup_member", arguments={"name": "x"})
    )
    return ChatResponse(
        model="qwen3:8b",
        message=Message(role="assistant", content="", thinking=thinking, tool_calls=[call]),
        prompt_eval_count=1800,
        eval_count=30,
        done_reason="stop",
    )


def test_ollama_client_sends_think_temperature_and_seed():
    client = OllamaClient("qwen3:8b", think=False, num_ctx=8192, temperature=0.0, seed=42)
    sent = fake_ollama(client, tool_response())
    turn = client.chat([{"role": "user", "content": "hi"}], [])
    assert sent[0]["think"] is False
    assert sent[0]["options"] == {
        "num_ctx": 8192,
        "temperature": 0.0,
        "seed": 42,
        "num_predict": 4096,
    }
    assert sent[0]["stream"] is False
    assert turn.tool_calls == [ToolCall(name="lookup_member", arguments={"name": "x"})]
    assert turn.prompt_eval_count == 1800 and turn.done_reason == "stop"


def test_ollama_client_omits_think_when_none_and_truncates_thinking():
    client = OllamaClient("llama3.1:8b", think=None)
    sent = fake_ollama(client, tool_response(thinking="x" * (THINKING_LIMIT + 50)))
    turn = client.chat([], [])
    assert "think" not in sent[0]
    assert turn.thinking.startswith("x" * THINKING_LIMIT) and turn.thinking.endswith("[truncated]")


def test_stdio_transport_runs_the_same_chain():
    mock = MockModelClient(CHAIN)

    async def go():
        async with connect("stdio") as session:
            return await run_agent("Does Island6 have open flags?", [], mock, session)

    trace = asyncio.run(go())
    in_process, _ = run(CHAIN)
    assert [e.model_dump() for e in trace.tool_executions] == [
        e.model_dump() for e in in_process.tool_executions
    ]
