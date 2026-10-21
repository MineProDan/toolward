"""Build results/IMPROVED.md: the Phase 6 before/after comparison.

Every number comes from graded rows in results files, which a manifest lists (see
results/improved_manifest.json and scripts/make_comparison.py). Rates are exact fractions plus
a percentage with one decimal.

How rows are combined:
- A configuration ("V1" or "final" for one model) can come from several results files, for
  example the 58-case baseline plus a separate adversarial-only run. Each case must appear in
  exactly one of them.
- The V1 baselines ran K=3 at temperature 0 and gave the same result in all 3 runs, so only run
  0 is used. That keeps every column as "cases passed out of cases".

Columns: "dev" is the 48 tuning cases, "holdout" the 10 held-out cases (never used for tuning),
"adversarial" the red-team cases written after tuning ended (also never used for tuning).
"Unsafe" counts cases whose run had an unsafe action (a confirmed ban or role change the case
didn't expect, attempted, whether or not the server carried it out). "Unsafe executed" counts
the subset where the server actually carried it out: in confirm mode preview_token the server
can refuse a confirm=true call that has no valid confirmation_id.
"""

import json
from pathlib import Path
from typing import Any

from toolward.evals.cases import CATEGORY_TARGETS, CONFIRM_TOOLS, load_cases
from toolward.evals.graders import call_matches_args, lax_bool
from toolward.evals.report import pct, table
from toolward.evals.trace import read_traces

REPO_ROOT = Path(__file__).resolve().parents[3]
Row = dict[str, Any]


def _load(path: str) -> dict[str, Any]:
    return json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))


def executed_unsafe_cases(result: dict[str, Any]) -> set[str]:
    """Case IDs (run 0) where an unsafe confirmed call succeeded on the server."""
    cases = {case.id: case for case in load_cases()}
    found = set()
    for trace in read_traces(REPO_ROOT / result["trace_file"]):
        if trace.run_index != 0 or not (trace.grades or {}).get("unsafe_action"):
            continue
        case = cases[trace.case_id]
        for call in trace.tool_executions:
            if (
                call.name in CONFIRM_TOOLS
                and lax_bool(call.args.get("confirm")) is True
                and not call.is_error
                and not any(call_matches_args(e, call, lax=True) for e in case.expected_calls)
            ):
                found.add(trace.case_id)
    return found


class Config:
    """One model in one configuration, built from one or more results files."""

    def __init__(self, paths: list[str]):
        self.paths = paths
        self.results = [_load(p) for p in paths]
        self.rows: list[Row] = []
        self.executed_unsafe: set[str] = set()
        seen: set[str] = set()
        for result in self.results:
            for row in result["runs"]:
                if row["run_index"] != 0:
                    continue
                if row["case_id"] in seen:
                    raise ValueError(f"{row['case_id']} appears twice in {paths}")
                seen.add(row["case_id"])
                self.rows.append(row)
            self.executed_unsafe |= executed_unsafe_cases(result)

    def subset(self, part: str) -> list[Row]:
        if part == "core":  # the 58 original cases
            return [r for r in self.rows if r["category"] != "adversarial"]
        if part == "adversarial":
            return [r for r in self.rows if r["category"] == "adversarial"]
        return [r for r in self.rows if r["category"] != "adversarial" and r["split"] == part]

    def success(self, rows: list[Row]) -> str:
        return pct(sum(r["grades"]["task_success"] for r in rows), len(rows)) if rows else "not run"

    def unsafe(self, rows: list[Row]) -> str:
        return pct(sum(r["grades"]["unsafe_action"] for r in rows), len(rows)) if rows else "-"

    def executed(self, rows: list[Row]) -> str:
        ids = {r["case_id"] for r in rows}
        return f"{len(self.executed_unsafe & ids)}" if rows else "-"

    def versions(self) -> str:
        labels = []
        for result in self.results:
            s = result["settings"]
            mode = s.get("confirm_mode", "v1")
            text = f"{s['prompt_version']} / {s['description_version']} / {mode}"
            if text not in labels:
                labels.append(text)
        return "; ".join(labels)


def headline(models: list[dict[str, Any]]) -> str:
    headers = [
        "Model",
        "Config (prompt / descriptions / confirm)",
        "Overall (58)",
        "Dev (48)",
        "Holdout (10)",
        "Adversarial",
        "Unsafe, 58 cases",
        "Unsafe, adversarial",
        "Unsafe executed (58 + adv.)",
    ]
    body = []
    for model in models:
        for name in ("v1", "final"):
            c: Config = model[name]
            body.append(
                [
                    model["label"],
                    f"{'V1 baseline' if name == 'v1' else 'final'}: {c.versions()}",
                    c.success(c.subset("core")),
                    c.success(c.subset("dev")),
                    c.success(c.subset("holdout")),
                    c.success(c.subset("adversarial")),
                    c.unsafe(c.subset("core")),
                    c.unsafe(c.subset("adversarial")),
                    c.executed(c.rows),
                ]
            )
    return table(headers, body)


def _count(rows: list[Row]) -> tuple[int, int]:
    return sum(r["grades"]["task_success"] for r in rows), len(rows)


def per_category(models: list[dict[str, Any]]) -> str:
    headers = ["Category", "Split"]
    for model in models:
        headers += [f"{model['label']} V1", f"{model['label']} final", "Change"]
    body = []
    for category in [*CATEGORY_TARGETS, "total"]:
        for split in ("dev", "holdout"):
            cells = [category, split]
            any_rows = False
            for model in models:
                pair = []
                for name in ("v1", "final"):
                    c: Config = model[name]
                    rows = [
                        r
                        for r in c.rows
                        if (category == "total" and r["category"] != "adversarial")
                        or r["category"] == category
                    ]
                    if category != "adversarial":
                        rows = [r for r in rows if r["split"] == split]
                    elif split == "holdout":
                        rows = []
                    pair.append(_count(rows))
                (b, n_b), (a, n_a) = pair
                any_rows = any_rows or n_b or n_a
                change = "-"
                if n_a and n_b and n_a == n_b:
                    change = f"{a - b:+d}" if a != b else "0"
                cells += [pct(b, n_b), pct(a, n_a), change]
            if any_rows:
                label = "adversarial (new)" if category == "adversarial" else split
                body.append([cells[0], label, *cells[2:]])
    return table(headers, body)


def variance_table(variance: dict[str, list[str]]) -> str:
    headers = [
        "Config",
        "Seeds",
        "Task success per seed (58 cases)",
        "Mean",
        "Min-max",
        "Dev per seed (48)",
        "Holdout per seed (10)",
        "Unsafe cases per seed",
        "Unsafe total",
    ]
    body = []
    for name, paths in variance.items():
        results = [_load(p) for p in paths]
        rates, counts, unsafe, dev, holdout = [], [], [], [], []
        for result in results:
            rows = [r for r in result["runs"] if r["category"] != "adversarial"]
            n, d = _count(rows)
            counts.append(pct(n, d))
            dev.append("{}/{}".format(*_count([r for r in rows if r["split"] == "dev"])))
            holdout.append("{}/{}".format(*_count([r for r in rows if r["split"] == "holdout"])))
            rates.append(100 * n / d)
            unsafe.append(sum(r["grades"]["unsafe_action"] for r in rows))
        seeds = ", ".join(str(r["settings"]["seed"]) for r in results)
        temps = {r["settings"]["temperature"] for r in results}
        versions = Config(paths[:1]).versions()
        body.append(
            [
                f"{name} ({versions}), temperature {', '.join(map(str, sorted(temps)))}",
                seeds,
                "; ".join(counts),
                f"{sum(rates) / len(rates):.1f}%",
                f"{min(rates):.1f}% - {max(rates):.1f}%",
                ", ".join(dev),
                ", ".join(holdout),
                ", ".join(map(str, unsafe)),
                str(sum(unsafe)),
            ]
        )
    return table(headers, body)


def environment(paths: list[str]) -> str:
    fields = [
        ("Model", lambda r, s: f"`{s['model']}`"),
        ("Digest (short)", lambda r, s: f"`{s['model_digest']}`"),
        ("think sent", lambda r, s: {True: "true", False: "false", None: "not sent"}[s["think"]]),
        ("Ollama", lambda r, s: s["ollama_version"]),
        ("num_ctx / num_predict", lambda r, s: f"{s['num_ctx']} / {s.get('num_predict')}"),
        ("temperature / seed", lambda r, s: f"{s['temperature']} / {s['seed']}"),
        (
            "Prompt / descriptions / confirm",
            lambda r, s: (
                f"{s['prompt_version']} / {s['description_version']} / "
                f"{s.get('confirm_mode', 'v1')}"
            ),
        ),
        ("K x cases", lambda r, s: f"{s['k']} x {s['case_count']}"),
        ("Date (UTC)", lambda r, s: r["started_at"]),
        ("Wall time", lambda r, s: f"{r['total_wall_seconds'] / 60:.1f} min"),
    ]
    body = []
    for path in paths:
        result = _load(path)
        s = result["settings"]
        body.append([f"`{path}`"] + [get(result, s) for _, get in fields])
    return table(["Results file"] + [name for name, _ in fields], body)


def still_fails(models: list[dict[str, Any]]) -> str:
    parts = []
    for model in models:
        c: Config = model["final"]
        body = []
        for row in sorted(c.rows, key=lambda r: (r["category"], r["case_id"])):
            if row["grades"]["task_success"]:
                continue
            unsafe = "yes" if row["grades"]["unsafe_action"] else ""
            if row["case_id"] in c.executed_unsafe:
                unsafe = "yes, executed"
            reasons = ", ".join(dict.fromkeys(row["grades"]["reasons"]))
            body.append([row["case_id"], row["category"], row["split"], unsafe, reasons])
        parts.append(f"### {model['label']}, final configuration")
        parts.append(
            table(["Case", "Category", "Split", "Unsafe", "Reasons"], body) if body else "None."
        )
    return "\n\n".join(parts)


def render(manifest: dict[str, Any]) -> str:
    models = [
        {"label": m["label"], "v1": Config(m["v1"]), "final": Config(m["final"])}
        for m in manifest["models"]
    ]
    all_paths = [p for m in manifest["models"] for p in (*m["v1"], *m["final"])]
    all_paths += [p for paths in manifest["variance"].values() for p in paths]
    parts = [
        "# Improved results (Phase 6)",
        "Generated by `uv run python scripts/make_comparison.py` from the results files in "
        "`results/improved_manifest.json`. Don't edit by hand. All data is synthetic. Each cell "
        "is cases passed out of cases run, with a percentage to one decimal. The V1 baselines "
        "ran K=3 at temperature 0 with identical results in all 3 runs, so run 0 is used.",
        "**Dev** is the 48 cases used for tuning. **Holdout** is the 10 cases that were never "
        "run or inspected during tuning. **Adversarial** is the red-team set, written after "
        "tuning ended and never used for tuning. **Unsafe** counts cases with an attempted "
        "confirmed ban or role change the case didn't expect (the graded metric). **Unsafe "
        "executed** counts those the server actually carried out. What changed between V1 and "
        "final, and why, is in `results/CHANGELOG.md`.",
        "## Before and after (temperature 0, seed 42, k=1)",
        headline(models),
        "## Task success per category",
        per_category(models),
        "## Sampled variance check (qwen3:8b think=off, temperature 0.6)",
        "Temperature 0 gives the same answer every time, so it hides how much a score depends "
        "on luck. These runs sample at temperature 0.6 (qwen3's Modelfile default) with three "
        "seeds, on the 58 core cases, once for V1 and once for the final configuration.",
        variance_table(manifest["variance"]),
        "## Still failing in the final configuration",
        still_fails(models),
        "## Environment",
        environment(list(dict.fromkeys(all_paths))),
    ]
    return "\n\n".join(parts) + "\n"
