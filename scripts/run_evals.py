"""Run the eval cases against a local Ollama model.

Usage (examples):
    uv run python scripts/run_evals.py --model qwen3:8b --think off
    uv run python scripts/run_evals.py --model llama3.1:8b --think default --k 3
    uv run python scripts/run_evals.py --model qwen3:8b --think on --cases sel_01,arg_03 --k 1

Writes traces/<model>_<think>_<timestamp>.jsonl and results/<same name>.json under --out
(default: the repo root). Build the report afterwards with scripts/make_report.py.

--think: on/off send think=true/false. "default" doesn't send it at all; use it for models
without thinking support such as llama3.1. For qwen3, always choose on or off, because Ollama
turns thinking on by default.
"""

import argparse
import logging
from pathlib import Path

from toolward.agent.loop import AgentConfig
from toolward.agent.models import OllamaClient
from toolward.evals.cases import load_cases
from toolward.evals.runner import run_evals, select_cases

REPO_ROOT = Path(__file__).resolve().parent.parent
THINK = {"on": True, "off": False, "default": None}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run toolward evals with an Ollama model.")
    parser.add_argument("--model", required=True, help="Ollama model tag, like qwen3:8b")
    parser.add_argument("--think", choices=THINK, required=True)
    parser.add_argument("--k", type=int, default=3, help="runs per case (default 3)")
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--num-predict", type=int, default=4096, help="token cap per reply; 0 = no cap"
    )
    parser.add_argument("--split", choices=["all", "dev", "holdout"], default="all")
    parser.add_argument("--cases", help="comma-separated case IDs (default: all in the split)")
    parser.add_argument("--max-turns", type=int, default=6)
    parser.add_argument("--transport", choices=["inprocess", "stdio"], default="inprocess")
    parser.add_argument(
        "--out", type=Path, default=REPO_ROOT, help="folder for traces/ and results/"
    )
    parser.add_argument("--name", help="file stem for the outputs (default: model_think_time)")
    args = parser.parse_args()
    # The HTTP client logs every request at INFO; keep the progress output readable.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    ids = [i.strip() for i in args.cases.split(",")] if args.cases else None
    cases = select_cases(load_cases(), args.split, ids)
    client = OllamaClient(
        args.model,
        think=THINK[args.think],
        num_ctx=args.num_ctx,
        temperature=args.temperature,
        seed=args.seed,
        num_predict=args.num_predict or None,
    )
    print(f"{len(cases)} cases x k={args.k} with {args.model} (think={args.think})")
    trace_path, results_path = run_evals(
        cases,
        client,
        k=args.k,
        config=AgentConfig(max_turns=args.max_turns),
        transport=args.transport,
        out_dir=args.out,
        name=args.name,
        extra_settings={"split": args.split, "case_filter": ids},
        progress=lambda line: print(line, flush=True),
    )
    print(f"Traces:  {trace_path}\nResults: {results_path}")


if __name__ == "__main__":
    main()
