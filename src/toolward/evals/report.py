"""Build results/BASELINE.md from one or more results/*.json files (one per configuration).

Every number comes straight from the graded rows in the results files. Rates are written as an
exact fraction plus a percentage with one decimal, like "41/58 (70.7%)".

Metric definitions (per run; a case run K times counts K times):
- Task success: contract step 7 (all expected calls right, nothing extra, forbidden or unsafe,
  and the clarification/refusal condition when the case sets one). Over all runs.
- Tool selection: the expected tools were called and no other tool outside the allowed extras.
  Over all runs, including cases where the right choice is to call nothing.
- Args: expected calls matched on tool and args, over runs where every expected tool was called
  (cases with no expected calls are left out).
- Clarification: clarification_ok over runs of must_ask_clarification cases.
- Refusal: refusal_ok over runs of must_refuse cases.
- Unsafe actions: runs with a confirmed ban_member/assign_role that the case didn't expect.
- Extra-call rate: runs with at least one call not accounted for by the case.
"""

import json
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from toolward.evals.cases import CATEGORY_TARGETS

Row = dict[str, Any]


def load_results(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    return [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]


def pct(n: int, d: int) -> str:
    """'n/d (x.y%)', or 'n/a' when there is nothing to divide by."""
    if d == 0:
        return "n/a"
    return f"{n}/{d} ({100 * n / d:.1f}%)"


def _count(rows: list[Row], key: str) -> tuple[int, int]:
    """(rows where grades[key] is True, rows where it is not None)."""
    graded = [r for r in rows if r["grades"][key] is not None]
    return sum(r["grades"][key] is True for r in graded), len(graded)


def metrics(rows: list[Row]) -> dict[str, str]:
    """The headline metrics for a set of graded runs, formatted for a table."""
    n = len(rows)
    if n == 0:
        return {}
    success, _ = _count(rows, "task_success")
    selection, _ = _count(rows, "tool_selection_ok")
    args_n, args_d = _count(rows, "args_ok")
    clar_n, clar_d = _count(rows, "clarification_ok")
    ref_n, ref_d = _count(rows, "refusal_ok")
    unsafe = sum(r["grades"]["unsafe_action"] for r in rows)
    extra = sum(r["grades"]["extra_call"] for r in rows)
    return {
        "runs": str(n),
        "task_success": pct(success, n),
        "tool_selection": pct(selection, n),
        "args": pct(args_n, args_d),
        "clarification": pct(clar_n, clar_d),
        "refusal": pct(ref_n, ref_d),
        "unsafe": pct(unsafe, n),
        "extra_call": pct(extra, n),
        "mean_turns": f"{statistics.fmean(r['turns'] for r in rows):.2f}",
        "mean_wall": f"{statistics.fmean(r['wall_seconds'] for r in rows):.1f}",
    }


METRIC_HEADERS = [
    ("task_success", "Task success"),
    ("tool_selection", "Tool selection"),
    ("args", "Args"),
    ("clarification", "Clarification"),
    ("refusal", "Refusal"),
    ("unsafe", "Unsafe actions"),
    ("extra_call", "Extra-call rate"),
    ("mean_turns", "Mean turns"),
    ("mean_wall", "Mean wall s"),
]


def table(headers: list[str], body: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines)


def label(result: dict[str, Any]) -> str:
    s = result["settings"]
    return f"{s['model']} think={s['think_label']} k={s['k']}"


def per_case(rows: list[Row]) -> dict[str, list[Row]]:
    grouped: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        grouped[row["case_id"]].append(row)
    return dict(grouped)


def success_count(case_rows: list[Row]) -> int:
    return sum(r["grades"]["task_success"] for r in case_rows)


def main_reason(case_rows: list[Row]) -> str:
    """The reason that appears in the most failed runs of a case."""
    counts = Counter(
        reason
        for r in case_rows
        if not r["grades"]["task_success"]
        for reason in dict.fromkeys(r["grades"]["reasons"])  # once per run
    )
    return counts.most_common(1)[0][0] if counts else ""


def variance(rows: list[Row], k: int) -> dict[str, Any]:
    """Consistency of the K repeats at temperature 0."""
    cases = per_case(rows)
    inconsistent = sorted(cid for cid, rs in cases.items() if 0 < success_count(rs) < len(rs))
    by_index: dict[int, list[Row]] = defaultdict(list)
    for row in rows:
        by_index[row["run_index"]].append(row)
    rates = {index: success_count(rs) / len(rs) for index, rs in sorted(by_index.items()) if rs}
    std = statistics.pstdev(rates.values()) if len(rates) > 1 else None
    return {"inconsistent": inconsistent, "rates": rates, "std": std, "cases": len(cases)}


def top_reasons(rows: list[Row], n: int = 5) -> list[tuple[str, int, list[str]]]:
    """The n most common failure reasons: (reason, failed runs with it, example case ids)."""
    counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        if row["grades"]["task_success"]:
            continue
        for reason in dict.fromkeys(row["grades"]["reasons"]):
            counts[reason] += 1
            if row["case_id"] not in examples[reason]:
                examples[reason].append(row["case_id"])
    return [(reason, c, examples[reason][:3]) for reason, c in counts.most_common(n)]


def _split_rows(rows: list[Row], split: str) -> list[Row]:
    return [r for r in rows if split == "all" or r["split"] == split]


def environment_table(results: list[dict[str, Any]]) -> str:
    fields = [
        ("Model", lambda r, s: f"`{s['model']}`"),
        ("Digest (short)", lambda r, s: f"`{s['model_digest']}`"),
        ("think sent", lambda r, s: {True: "true", False: "false", None: "not sent"}[s["think"]]),
        ("Ollama version", lambda r, s: s["ollama_version"]),
        ("num_ctx", lambda r, s: str(s["num_ctx"])),
        ("temperature", lambda r, s: str(s["temperature"])),
        ("seed", lambda r, s: str(s["seed"])),
        ("num_predict (reply cap)", lambda r, s: str(s.get("num_predict") or "not set")),
        (
            "Prompt / descriptions / confirm mode",
            lambda r, s: (
                f"{s['prompt_version']} / {s['description_version']} / "
                f"{s.get('confirm_mode', 'v1')}"
            ),
        ),
        ("K x cases", lambda r, s: f"{s['k']} x {s['case_count']}"),
        ("max_turns", lambda r, s: str(s["max_turns"])),
        ("Date (UTC)", lambda r, s: r["started_at"]),
        ("Total wall time", lambda r, s: f"{r['total_wall_seconds'] / 60:.1f} min"),
        (
            "Max prompt_eval_count",
            lambda r, s: str(max((x["max_prompt_eval_count"] or 0) for x in r["runs"])),
        ),
        (
            "context_near_limit runs",
            lambda r, s: str(sum(x["flags"].get("context_near_limit", False) for x in r["runs"])),
        ),
        (
            "text_tool_call_suspected runs",
            lambda r, s: str(
                sum(x["flags"].get("text_tool_call_suspected", False) for x in r["runs"])
            ),
        ),
        (
            "Stopped at max_turns / token cap / error",
            lambda r, s: (
                f"{sum(x['stop_reason'] == 'max_turns' for x in r['runs'])} / "
                f"{sum(x['stop_reason'] == 'length_limit' for x in r['runs'])} / "
                f"{sum(x['stop_reason'] == 'error' for x in r['runs'])}"
            ),
        ),
        ("Trace file", lambda r, s: f"`{r['trace_file']}`"),
    ]
    headers = ["Setting"] + [label(r) for r in results]
    body = [[name] + [get(r, r["settings"]) for r in results] for name, get in fields]
    return table(headers, body)


def config_section(result: dict[str, Any]) -> str:
    rows = result["runs"]
    k = result["settings"]["k"]
    parts = [f"## {label(result)}"]

    parts.append("### Overall")
    body = []
    for split in ("dev", "holdout", "all"):
        m = metrics(_split_rows(rows, split))
        if m:
            body.append([split, m["runs"]] + [m[key] for key, _ in METRIC_HEADERS])
    parts.append(table(["Split", "Runs"] + [h for _, h in METRIC_HEADERS], body))

    parts.append("### Per category (dev and holdout together, then task success per split)")
    body = []
    for category in CATEGORY_TARGETS:
        cat_rows = [r for r in rows if r["category"] == category]
        if not cat_rows:
            continue
        m = metrics(cat_rows)
        dev = metrics([r for r in cat_rows if r["split"] == "dev"]).get("task_success", "n/a")
        hold = metrics([r for r in cat_rows if r["split"] == "holdout"]).get("task_success", "n/a")
        body.append([category, m["runs"]] + [m[key] for key, _ in METRIC_HEADERS] + [dev, hold])
    headers = (
        ["Category", "Runs"] + [h for _, h in METRIC_HEADERS] + ["Dev success", "Holdout success"]
    )
    parts.append(table(headers, body))

    v = variance(rows, k)
    parts.append(f"### Variance across K={k}")
    if k > 1:
        rates = ", ".join(f"run {i}: {100 * rate:.1f}%" for i, rate in v["rates"].items())
        parts.append(
            f"- Cases whose task success was not the same in all {k} runs: "
            f"{len(v['inconsistent'])} of {v['cases']}"
            + (f" ({', '.join(v['inconsistent'])})" if v["inconsistent"] else "")
            + "\n"
            f"- Task-success rate per run index: {rates}\n"
            f"- Population std of those rates: {100 * v['std']:.1f} percentage points"
        )
    else:
        parts.append("- K=1, so there is no run-to-run variance to report.")

    parts.append("### Most common failure reasons (failed runs that show each reason)")
    reasons = top_reasons(rows)
    if reasons:
        parts.append(
            table(
                ["Reason", "Failed runs", "Example cases"],
                [[r, str(c), ", ".join(ex)] for r, c, ex in reasons],
            )
        )
    else:
        parts.append("No failures.")

    parts.append("### Failed cases")
    body = []
    for case_id, case_rows in sorted(per_case(rows).items()):
        ok = success_count(case_rows)
        if ok < len(case_rows):
            body.append(
                [case_id, case_rows[0]["split"], f"{ok}/{len(case_rows)}", main_reason(case_rows)]
            )
    parts.append(table(["Case", "Split", "Success", "Main reason"], body) if body else "None.")
    return "\n\n".join(parts)


def side_by_side(results: list[dict[str, Any]]) -> str:
    headers = [
        "Configuration",
        "Task success",
        "Tool selection",
        "Args",
        "Clarification",
        "Refusal",
        "Unsafe actions",
        "Dev task success",
        "Holdout task success",
    ]
    body = []
    for result in results:
        rows = result["runs"]
        m = metrics(rows)
        body.append(
            [
                label(result),
                m["task_success"],
                m["tool_selection"],
                m["args"],
                m["clarification"],
                m["refusal"],
                m["unsafe"],
                metrics(_split_rows(rows, "dev"))["task_success"],
                metrics(_split_rows(rows, "holdout")).get("task_success", "n/a"),
            ]
        )
    return table(headers, body)


def per_case_table(results: list[dict[str, Any]]) -> str:
    grouped = [per_case(r["runs"]) for r in results]
    case_ids = sorted({cid for g in grouped for cid in g}, key=lambda c: (c.split("_")[0], c))
    body = []
    for cid in case_ids:
        first = next(g[cid][0] for g in grouped if cid in g)
        cells = [f"{success_count(g[cid])}/{len(g[cid])}" if cid in g else "-" for g in grouped]
        body.append([cid, first["category"], first["split"]] + cells)
    return table(["Case", "Category", "Split"] + [label(r) for r in results], body)


def render_report(results: list[dict[str, Any]], title: str = "Baseline results") -> str:
    case_counts = " / ".join(sorted({str(r["settings"]["case_count"]) for r in results}))
    parts = [
        f"# {title}",
        "Generated by `uv run python scripts/make_report.py` from the results files listed in "
        "the environment table. Don't edit by hand. All data is synthetic. Rates are exact "
        "fractions over runs (each case runs K times), with percentages to one decimal.",
        "Definitions: **task success** is the full grading contract in "
        "`src/toolward/evals/cases.py`. **Tool selection** means the expected tools were called "
        "and nothing outside the allowed extras. **Args** is measured over runs where every "
        "expected tool was called. **Clarification** and **refusal** are over the runs of cases "
        "that require them. **Unsafe actions** counts runs with a confirmed ban or role change "
        "that the case didn't expect. Dev and holdout are always reported separately; the 10 "
        "holdout cases are never used for tuning.",
        f"## Side by side ({case_counts} cases)",
        side_by_side(results),
        "## Environment",
        environment_table(results),
    ]
    parts += [config_section(r) for r in results]
    parts += ["## Per-case task success (successful runs / K)", per_case_table(results)]
    return "\n\n".join(parts) + "\n"
