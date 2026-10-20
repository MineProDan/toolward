"""Model clients: the real one (Ollama) and a mock that replays a recorded trace.

Both have the same two methods, so the agent loop doesn't care which one it gets:
- chat(messages, tools) -> ModelTurn
- info() -> dict of run settings that go into the trace
"""

import json
import time
import urllib.request
from typing import Any, Protocol

from toolward.evals.trace import THINKING_LIMIT, ModelTurn, ToolCall, Trace

DEFAULT_HOST = "http://localhost:11434"


class ModelClient(Protocol):
    def chat(self, messages: list[dict[str, Any]], tools: list[dict]) -> ModelTurn: ...

    def info(self) -> dict[str, Any]: ...


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


class OllamaClient:
    """Talks to a local Ollama server.

    think: True or False is always sent explicitly (qwen3 turns thinking ON by default).
        None means "don't send it", for models without thinking support such as llama3.1.
    temperature and seed are always sent too, because a Modelfile can set its own defaults
        (qwen3's is 0.6).
    num_predict caps the tokens in one reply (thinking included). Without it, qwen3 with
        thinking on can loop forever on some requests. None means "no cap".
    """

    def __init__(
        self,
        model: str,
        think: bool | None = False,
        num_ctx: int = 8192,
        temperature: float = 0.0,
        seed: int = 42,
        num_predict: int | None = 4096,
        host: str = DEFAULT_HOST,
        keep_alive: str = "15m",
    ):
        import ollama  # imported here so offline tests never need the client to connect

        self.model = model
        self.think = think
        self.num_ctx = num_ctx
        self.temperature = temperature
        self.seed = seed
        self.num_predict = num_predict
        self.host = host
        self.keep_alive = keep_alive
        self._client = ollama.Client(host=host)
        self._info: dict[str, Any] | None = None

    def info(self) -> dict[str, Any]:
        if self._info is None:
            tags = _get_json(f"{self.host}/api/tags")
            digest = next(
                (
                    m["digest"]
                    for m in tags["models"]
                    if m["name"] == self.model or m["model"] == self.model
                ),
                None,
            )
            self._info = {
                "model": self.model,
                # The full sha256 is 64 hex characters, which the privacy scan flags as a
                # possible secret, so we keep the 12-character short form `ollama list` shows.
                "model_digest": digest[:12] if digest else None,
                "think": self.think,
                "num_ctx": self.num_ctx,
                "temperature": self.temperature,
                "seed": self.seed,
                "num_predict": self.num_predict,
                "ollama_version": _get_json(f"{self.host}/api/version").get("version"),
            }
        return self._info

    def chat(self, messages: list[dict[str, Any]], tools: list[dict]) -> ModelTurn:
        options = {"num_ctx": self.num_ctx, "temperature": self.temperature, "seed": self.seed}
        if self.num_predict is not None:
            options["num_predict"] = self.num_predict
        kwargs: dict[str, Any] = {}
        if self.think is not None:
            kwargs["think"] = self.think
        start = time.perf_counter()
        response = self._client.chat(
            model=self.model,
            messages=messages,
            tools=tools,
            stream=False,
            options=options,
            keep_alive=self.keep_alive,
            **kwargs,
        )
        wall = time.perf_counter() - start
        message = response.message
        thinking = message.thinking
        if thinking and len(thinking) > THINKING_LIMIT:
            thinking = thinking[:THINKING_LIMIT] + " [truncated]"
        calls = [
            ToolCall(name=call.function.name, arguments=dict(call.function.arguments or {}))
            for call in (message.tool_calls or [])
        ]
        return ModelTurn(
            content=message.content or "",
            thinking=thinking or None,
            tool_calls=calls,
            prompt_eval_count=response.prompt_eval_count,
            prompt_eval_duration=response.prompt_eval_duration,
            eval_count=response.eval_count,
            eval_duration=response.eval_duration,
            total_duration=response.total_duration,
            load_duration=response.load_duration,
            done_reason=response.done_reason,
            wall_seconds=round(wall, 3),
        )


class ReplayMismatch(Exception):
    """The loop asked the mock for more turns than the recorded trace has."""


class MockModelClient:
    """Replays the model turns of a recorded trace, in order, with no GPU and no network.

    The tool calls in each turn are replayed exactly; the tool results come from whatever MCP
    server the loop is connected to (in tests, a fresh real server), so a replay re-checks that
    the server still answers the same way.
    """

    def __init__(self, trace: Trace):
        self._trace = trace
        self._turns = list(trace.turns)
        self.calls = 0

    def info(self) -> dict[str, Any]:
        t = self._trace
        return {
            "model": t.model,
            "model_digest": t.model_digest,
            "think": t.think,
            "num_ctx": t.num_ctx,
            "temperature": t.temperature,
            "seed": t.seed,
            "num_predict": t.num_predict,
            "ollama_version": t.ollama_version,
        }

    def chat(self, messages: list[dict[str, Any]], tools: list[dict]) -> ModelTurn:
        if self.calls >= len(self._turns):
            raise ReplayMismatch(
                f"trace has {len(self._turns)} turns, the loop asked for turn {self.calls + 1}"
            )
        turn = self._turns[self.calls]
        self.calls += 1
        return turn.model_copy(deep=True)

    @property
    def finished(self) -> bool:
        return self.calls == len(self._turns)
