"""Replay recorded real-model traces offline and check that the grades come out the same.

traces/sample/ holds one trace per category per configuration, copied from real runs by
scripts/make_sample_traces.py. Each one is replayed with MockModelClient (the model's turns,
exactly as recorded) against a fresh in-process server. This checks, with no GPU and no Ollama,
that the loop, the server's answers and the graders still behave the way they did in the run.
"""

import asyncio
from pathlib import Path

import pytest

from toolward.agent.loop import AgentConfig
from toolward.agent.models import MockModelClient
from toolward.evals.cases import load_cases
from toolward.evals.runner import run_case
from toolward.evals.trace import read_traces

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "traces" / "sample"
SAMPLES = sorted(SAMPLE_DIR.glob("*.jsonl"))
CASES = {case.id: case for case in load_cases()}
TRACES = [(path.stem, trace) for path in SAMPLES for trace in read_traces(path)]


def test_sample_traces_exist():
    assert len(SAMPLES) >= 1, "traces/sample/ is empty; run scripts/make_sample_traces.py"
    assert len(TRACES) >= 7


@pytest.mark.parametrize(
    ("config", "recorded"), TRACES, ids=[f"{name}-{t.case_id}" for name, t in TRACES]
)
def test_replay_gives_the_recorded_grades(config, recorded):
    case = CASES[recorded.case_id]
    mock = MockModelClient(recorded)
    settings = AgentConfig(
        max_turns=recorded.max_turns,
        prompt_version=recorded.prompt_version,
        description_version=recorded.description_version,
        confirm_mode=recorded.confirm_mode,
    )
    replayed = asyncio.run(run_case(case, recorded.run_index, mock, settings))

    assert mock.finished, "the replay used fewer model turns than the recording"
    assert replayed.messages == recorded.messages  # same system prompt, history and request
    assert replayed.tools_sha == recorded.tools_sha  # same tool definitions
    assert [e.model_dump() for e in replayed.tool_executions] == [
        e.model_dump() for e in recorded.tool_executions
    ]
    assert replayed.final_text == recorded.final_text
    assert replayed.stop_reason == recorded.stop_reason
    assert replayed.flags == recorded.flags
    assert replayed.grades == recorded.grades
