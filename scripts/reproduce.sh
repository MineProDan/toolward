#!/usr/bin/env bash
# Rerun the final configurations end to end and compare them with the committed results.
#
# Usage:
#   scripts/reproduce.sh [OUT_DIR]        # default OUT_DIR: reproduce_runs (git-ignored)
#
# Needs Ollama running locally with qwen3:8b and llama3.1:8b pulled:
#   ollama pull qwen3:8b && ollama pull llama3.1:8b
#
# Run time: the recorded wall times of these runs add up to about 65 minutes on a 16 GB
# MacBook Air. Close other apps first: each model takes about 6 GB of memory.
#
# What it runs (all with the final configuration: prompt V1, descriptions V4, confirm mode v1):
#   1. qwen3:8b (think off) and llama3.1:8b on all 68 cases, temperature 0, seed 42
#   2. qwen3:8b on the 58 core cases at temperature 0.6, seeds 42, 43 and 44
#   3. the tool-count experiment: qwen3:8b with 3, 5 and 7 tools exposed
# The outputs go to OUT_DIR/traces and OUT_DIR/results with the same file names as the
# committed runs, so nothing in traces/ or results/ is overwritten. Each run is then compared
# with its committed twin, case by case (scripts/compare_runs.py).

set -euo pipefail

cd "$(dirname "$0")/.."
OUT="${1:-reproduce_runs}"
HOST="${OLLAMA_HOST:-http://localhost:11434}"

if ! curl -sf "$HOST/api/version" > /dev/null; then
    echo "Ollama is not reachable at $HOST. Start the Ollama app (or 'ollama serve') first." >&2
    exit 1
fi
for model in qwen3:8b llama3.1:8b; do
    if ! ollama list | awk '{print $1}' | grep -qx "$model"; then
        echo "Model $model is not pulled. Run: ollama pull $model" >&2
        exit 1
    fi
done

run() {
    local name="$1"
    shift
    echo "== $name"
    uv run python scripts/run_evals.py --k 1 --descriptions-version V4 \
        --out "$OUT" --name "$name" "$@"
}

CASES=$(uv run python -c "from toolward.evals.cases import load_cases; \
from toolward.evals.experiments import tool_count_cases; \
print(','.join(c.id for c in tool_count_cases(load_cases())))")

run p6_final_qwen3_off_all --model qwen3:8b --think off --split all
run p6_final_llama3.1_default_all --model llama3.1:8b --think default --split all
for seed in 42 43 44; do
    run "p6_var_qwen3_off_final_t06_s$seed" --model qwen3:8b --think off --split core \
        --temperature 0.6 --seed "$seed"
done
run tc_qwen3_off_tools3 --model qwen3:8b --think off --cases "$CASES" \
    --tools lookup_member,get_leaderboard,get_automod_log
run tc_qwen3_off_tools5 --model qwen3:8b --think off --cases "$CASES" \
    --tools lookup_member,get_leaderboard,get_automod_log,get_community_stats,draft_announcement
run tc_qwen3_off_tools7 --model qwen3:8b --think off --cases "$CASES"

echo
echo "== Comparison with the committed results (before = committed, after = this rerun)"
for new in "$OUT"/results/*.json; do
    name="$(basename "$new")"
    echo
    echo "### $name"
    uv run python scripts/compare_runs.py "results/$name" "$new"
done
