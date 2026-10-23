"""Build the README's results section from the committed results files.

The README has a block between RESULTS_START and RESULTS_END. Everything inside it is written
by scripts/update_readme_results.py from the same inputs as the reports:

- results/improved_manifest.json (as for results/IMPROVED.md): the before/after table and the
  temperature-0.6 variance check.
- BASELINE_RESULTS (as for results/BASELINE.md): the V1 baselines, including thinking on.
- results/tc_qwen3_off_tools{3,5,7}.json and their traces (as for results/TOOL_COUNT.md).

tests/test_readme.py fails if the block in README.md differs from a fresh render. That is how
"README numbers match recorded results exactly" is enforced: nobody types these numbers.
"""

import json
from pathlib import Path
from typing import Any

from toolward.evals.comparison import Config
from toolward.evals.experiments import CORE_TOOLS, TOOL_SETS
from toolward.evals.report import pct, table
from toolward.evals.trace import read_traces

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_START = "<!-- results:start -->"
RESULTS_END = "<!-- results:end -->"
# Absolute links, so they also work on the PyPI project page (which has no repo files).
REPO_BLOB = "https://github.com/MineProDan/toolward/blob/main/"

MANIFEST = "results/improved_manifest.json"
# The three Phase 5 baselines, in the column order of results/BASELINE.md.
BASELINE_RESULTS = [
    "results/qwen3-8b_off_20261020T041011.json",
    "results/llama3.1-8b_default_20261020T043610.json",
    "results/qwen3-8b_on_20261020T083859.json",
]
TOOL_COUNT_RESULTS = {n: f"results/tc_qwen3_off_tools{n}.json" for n in TOOL_SETS}

Row = dict[str, Any]


def _load(path: str) -> dict[str, Any]:
    return json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))


def _success(rows: list[Row]) -> tuple[int, int]:
    return sum(r["grades"]["task_success"] for r in rows), len(rows)


def _think(settings: dict[str, Any]) -> str:
    return {True: "on", False: "off", None: "n/a"}[settings["think"]]


def before_after(models: list[dict[str, Any]]) -> tuple[str, str]:
    """The before/after table, plus the headline sentence for the primary model."""
    headers = [
        "Model",
        "Config",
        "Overall (58)",
        "Dev (48)",
        "Holdout (10)",
        "Adversarial (10)",
        "Unsafe attempted (58)",
        "Unsafe attempted (adv.)",
        "Unsafe executed (58 + adv.)",
    ]
    body = []
    for model in models:
        for name in ("v1", "final"):
            c: Config = model[name]
            body.append(
                [
                    model["label"],
                    f"{'V1' if name == 'v1' else 'final'} ({c.versions()})",
                    c.success(c.subset("core")),
                    c.success(c.subset("dev")),
                    c.success(c.subset("holdout")),
                    c.success(c.subset("adversarial")),
                    c.unsafe(c.subset("core")),
                    c.unsafe(c.subset("adversarial")),
                    c.executed(c.rows),
                ]
            )
    primary = models[0]
    (b, n_b), (a, n_a) = (_success(primary[k].subset("dev")) for k in ("v1", "final"))
    (hb, hn_b), (ha, hn_a) = (_success(primary[k].subset("holdout")) for k in ("v1", "final"))
    delta = 100 * a / n_a - 100 * b / n_b
    headline = (
        f"{primary['label']}, dev (tuning) cases: {pct(b, n_b)} -> {pct(a, n_a)}, "
        f"{delta:+.1f} points. Holdout: {pct(hb, hn_b)} -> {pct(ha, hn_a)}."
    )
    return table(headers, body), headline


def variance(paths_by_config: dict[str, list[str]]) -> str:
    headers = [
        "Config",
        "Seeds",
        "Task success per seed (58)",
        "Mean",
        "Range",
        "Holdout per seed (10)",
        "Unsafe cases per seed",
    ]
    body = []
    for name, paths in paths_by_config.items():
        results = [_load(p) for p in paths]
        counts, rates, holdout, unsafe = [], [], [], []
        for result in results:
            rows = [r for r in result["runs"] if r["category"] != "adversarial"]
            n, d = _success(rows)
            counts.append(f"{n}/{d}")
            rates.append(100 * n / d)
            holdout.append("{}/{}".format(*_success([r for r in rows if r["split"] == "holdout"])))
            unsafe.append(str(sum(r["grades"]["unsafe_action"] for r in rows)))
        temps = sorted({r["settings"]["temperature"] for r in results})
        body.append(
            [
                f"{name} ({Config(paths[:1]).versions()}), temperature "
                + ", ".join(map(str, temps)),
                ", ".join(str(r["settings"]["seed"]) for r in results),
                ", ".join(counts),
                f"{sum(rates) / len(rates):.1f}%",
                f"{min(rates):.1f}% - {max(rates):.1f}%",
                ", ".join(holdout),
                ", ".join(unsafe),
            ]
        )
    return table(headers, body)


def baselines(paths: list[str]) -> tuple[str, str]:
    """The V1 baselines side by side (thinking on included), plus its caveats."""
    headers = [
        "Model",
        "think",
        "K",
        "Task success (runs)",
        "Dev",
        "Holdout",
        "Unsafe runs",
        "Runs that hit the reply cap",
        "Mean wall s per run",
    ]
    body = []
    by_think: dict[str, dict[str, Any]] = {}
    for path in paths:
        result = _load(path)
        s, rows = result["settings"], result["runs"]
        cap = s.get("num_predict")
        capped = sum(r["stop_reason"] == "length_limit" for r in rows)
        wall = sum(r["wall_seconds"] for r in rows) / len(rows)
        body.append(
            [
                s["model"],
                _think(s),
                str(s["k"]),
                pct(*_success(rows)),
                pct(*_success([r for r in rows if r["split"] == "dev"])),
                pct(*_success([r for r in rows if r["split"] == "holdout"])),
                pct(sum(r["grades"]["unsafe_action"] for r in rows), len(rows)),
                f"{capped} (cap {cap})" if cap else "no cap set",
                f"{wall:.1f}",
            ]
        )
        if s["model"].startswith("qwen3"):
            by_think[_think(s)] = {"k": s["k"], "cap": cap, "capped": capped, "wall": wall}
    on, off = by_think["on"], by_think["off"]
    caveat = (
        f"Thinking on ran once per case (k={on['k']}), with V1 prompt and descriptions only; it "
        "was not part of the Phase 6 tuning and has no final-configuration run. A reply cap of "
        f"{on['cap']} tokens was added for it after qwen3 got stuck in an endless thinking loop; "
        f"{on['capped']} runs hit the cap and count as failures. It took {on['wall']:.1f} s per "
        f"run against {off['wall']:.1f} s with thinking off."
    )
    return table(headers, body), caveat


def tool_count(paths: dict[int, str]) -> str:
    cells, settings = [], None
    unneeded = 0
    for n, path in paths.items():
        result = _load(path)
        settings = result["settings"]
        cells.append(f"{pct(*_success(result['runs']))} with {n} tools")
        unneeded += sum(
            e.name not in CORE_TOOLS
            for t in read_traces(REPO_ROOT / result["trace_file"])
            for e in t.tool_executions
        )
    assert settings is not None
    return (
        f"Tool count ({settings['model']} think={_think(settings)}, config "
        f"{settings['prompt_version']} / {settings['description_version']} / "
        f"{settings['confirm_mode']}, temperature {settings['temperature']}, k={settings['k']}, "
        f"{settings['case_count']} cases that need only the {len(CORE_TOOLS)} core tools): task "
        f"success {'; '.join(cells)}. Calls "
        f"to tools the cases didn't need: {unneeded}. Details: "
        f"[results/TOOL_COUNT.md]({REPO_BLOB}results/TOOL_COUNT.md)."
    )


def render_section() -> str:
    """The full results block, markers included."""
    manifest = _load(MANIFEST)
    models = [
        {"label": m["label"], "v1": Config(m["v1"]), "final": Config(m["final"])}
        for m in manifest["models"]
    ]
    main_table, headline = before_after(models)
    base_table, caveat = baselines(BASELINE_RESULTS)
    parts = [
        RESULTS_START,
        "<!-- Generated by `uv run python scripts/update_readme_results.py` from the committed "
        "results files. Don't edit by hand: tests/test_readme.py fails if this block is out of "
        "date. -->",
        "### Before and after (temperature 0, seed 42, k=1)",
        "Config is prompt / descriptions / confirm mode. Each cell is cases passed out of cases "
        f"run. Full report: [results/IMPROVED.md]({REPO_BLOB}results/IMPROVED.md).",
        main_table,
        f"**{headline}**",
        "### Sampled variance check (qwen3:8b think=off, 58 core cases)",
        variance(manifest["variance"]),
        "### V1 baselines, including thinking on (temperature 0)",
        "Fractions are over runs (cases x K). Full report: "
        f"[results/BASELINE.md]({REPO_BLOB}results/BASELINE.md).",
        base_table,
        caveat,
        "### Tool count",
        tool_count(TOOL_COUNT_RESULTS),
        RESULTS_END,
    ]
    return "\n\n".join(parts)


def replace_section(readme: str, section: str) -> str:
    """Swap the block between the markers (markers included) for `section`."""
    start, end = readme.find(RESULTS_START), readme.find(RESULTS_END)
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"README needs {RESULTS_START} and {RESULTS_END}, in that order")
    return readme[:start] + section + readme[end + len(RESULTS_END) :]
