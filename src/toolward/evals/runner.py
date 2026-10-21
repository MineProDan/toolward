"""Run eval cases through the agent K times each, grade every run, and save traces and results.

Every run gets a fresh MCP server, so state never leaks between runs (a ban in one run is gone
in the next). Runs go in rounds: all cases once (run_index 0), then all cases again (run_index
1), and so on, so the K repeats of a case are not back to back.

Outputs:
- traces/<name>.jsonl: one Trace per run, with its grades, written as soon as the run ends.
- results/<name>.json: the settings, the total wall time and one graded row per run. The report
  (report.py) is built from these files.
"""

import asyncio
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from toolward.agent.bridge import connect
from toolward.agent.loop import AgentConfig, run_agent
from toolward.agent.models import ModelClient
from toolward.evals.cases import EvalCase
from toolward.evals.graders import grade
from toolward.evals.trace import Trace, write_trace
from toolward.server import create_server
from toolward.server.descriptions import DESCRIPTIONS

THINK_LABELS = {True: "on", False: "off", None: "default"}


def think_label(think: bool | None) -> str:
    return THINK_LABELS[think]


def run_name(model: str, think: bool | None, when: datetime) -> str:
    """File stem like qwen3-8b_off_20261019T153012."""
    safe_model = model.replace(":", "-").replace("/", "-")
    return f"{safe_model}_{think_label(think)}_{when.strftime('%Y%m%dT%H%M%S')}"


SPLITS = ("all", "dev", "holdout", "core", "adversarial")


def in_split(case: EvalCase, split: str) -> bool:
    """all = every case. core = the 58 original cases. dev = the 48 tuning cases (core minus
    holdout). holdout = the 10 held-out cases. adversarial = the Phase 6 red-team cases."""
    adversarial = case.category == "adversarial"
    if split == "all":
        return True
    if split == "adversarial":
        return adversarial
    if split == "core":
        return not adversarial
    if split in ("dev", "holdout"):
        return not adversarial and case.split == split
    raise ValueError(f"unknown split {split!r}; use one of {SPLITS}")


def select_cases(
    cases: list[EvalCase], split: str = "all", ids: list[str] | None = None
) -> list[EvalCase]:
    chosen = [c for c in cases if in_split(c, split)]
    if ids:
        unknown = set(ids) - {c.id for c in cases}
        if unknown:
            raise ValueError(f"unknown case id(s): {sorted(unknown)}")
        chosen = [c for c in chosen if c.id in ids]
    return chosen


def history_of(case: EvalCase) -> list[dict[str, str]]:
    return [turn.model_dump() for turn in case.setup.history] if case.setup else []


async def run_case(
    case: EvalCase,
    run_index: int,
    model_client: ModelClient,
    config: AgentConfig,
    transport: str = "inprocess",
    server_factory: Callable | None = None,
) -> Trace:
    """One graded run of one case on a fresh server. Only the request and history reach the
    agent; the case's expectations are used afterwards, for grading.

    Unless a server_factory is given, the server is built with the description set and confirm
    mode named in the config, so the versions recorded in the trace are the ones that ran.
    """
    if server_factory is None:
        server_factory = partial(
            create_server,
            descriptions=DESCRIPTIONS[config.description_version],
            confirm_mode=config.confirm_mode,
        )
    server_args = [
        "--descriptions",
        config.description_version,
        "--confirm-mode",
        config.confirm_mode,
    ]
    async with connect(transport, server_factory, server_args) as session:
        trace = await run_agent(
            case.request,
            history_of(case),
            model_client,
            session,
            config,
            case_id=case.id,
            run_index=run_index,
        )
    trace.grades = grade(case, trace)
    return trace


def result_row(case: EvalCase, trace: Trace) -> dict[str, Any]:
    """The part of a trace the report needs."""
    prompt_counts = [t.prompt_eval_count for t in trace.turns if t.prompt_eval_count is not None]
    return {
        "case_id": case.id,
        "category": case.category,
        "split": case.split,
        "run_index": trace.run_index,
        "turns": len(trace.turns),
        "tool_calls": len(trace.tool_executions),
        "wall_seconds": trace.wall_seconds,
        "max_prompt_eval_count": max(prompt_counts) if prompt_counts else None,
        "stop_reason": trace.stop_reason,
        "flags": trace.flags,
        "grades": trace.grades,
    }


def run_evals(
    cases: list[EvalCase],
    model_client: ModelClient,
    *,
    k: int = 3,
    config: AgentConfig | None = None,
    transport: str = "inprocess",
    out_dir: Path = Path("."),
    name: str | None = None,
    extra_settings: dict[str, Any] | None = None,
    progress: Callable[[str], None] = print,
) -> tuple[Path, Path]:
    """Run every case k times. Returns (trace file, results file)."""
    config = config or AgentConfig()
    started = datetime.now(UTC)
    info = model_client.info()
    name = name or run_name(info["model"], info["think"], started)
    trace_path = out_dir / "traces" / f"{name}.jsonl"
    results_path = out_dir / "results" / f"{name}.json"
    if trace_path.exists():
        raise FileExistsError(f"{trace_path} already exists")

    rows: list[dict[str, Any]] = []
    total = k * len(cases)
    t0 = time.perf_counter()
    for run_index in range(k):
        for case in cases:
            trace = asyncio.run(run_case(case, run_index, model_client, config, transport))
            write_trace(trace_path, trace)
            rows.append(result_row(case, trace))
            done = len(rows)
            elapsed = time.perf_counter() - t0
            eta = elapsed / done * (total - done)
            verdict = "PASS" if trace.grades["task_success"] else "fail"
            why = "" if trace.grades["task_success"] else f"  {trace.grades['reasons'][:2]}"
            progress(
                f"[{done}/{total}] {case.id} run {run_index}: {verdict} "
                f"({trace.wall_seconds:.1f}s, eta {eta / 60:.0f} min){why}"
            )

    finished = datetime.now(UTC)
    results = {
        "name": name,
        "settings": {
            **info,
            "think_label": think_label(info["think"]),
            "k": k,
            "max_turns": config.max_turns,
            "prompt_version": config.prompt_version,
            "description_version": config.description_version,
            "confirm_mode": config.confirm_mode,
            "transport": transport,
            "case_count": len(cases),
            **(extra_settings or {}),
        },
        "started_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "finished_at": finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_wall_seconds": round(time.perf_counter() - t0, 1),
        "trace_file": f"traces/{trace_path.name}",
        "runs": rows,
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    return trace_path, results_path
