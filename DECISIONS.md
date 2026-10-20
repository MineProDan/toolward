# Decisions

One entry per gate: date, decision, reason. "Proposed" entries are waiting on Daniel.

## Gate 0: Setup and verification (2026-10-19)

**Environment (done).** uv 0.13.3 and Python 3.12.15 were installed through uv, with Daniel's approval. Daniel installed the Ollama app (0.40.6).

**Verified tooling.** `mcp` 2.3.0, `ollama` (Python client) 0.6.3 and `pydantic` 2.14.1.

**Phase 0 smoke test.** 2 tools, 10 prompts, num_ctx 8192, temperature 0, seed 42:

| Model | Think | Correct | Mean tok/s | Mean wall s/prompt | Loaded memory |
|---|---|---|---|---|---|
| qwen3:8b (`500a1f067a9f`) | off | 10/10 | 24.3 | 1.17 | 6.19 GB |
| qwen3:8b | on | 10/10 | 23.0 | 6.23 | 6.19 GB |
| llama3.1:8b (`46e0c10c039e`) | n/a | 10/10 | 25.3 | 1.39 | 5.95 GB |

This test was too easy to tell the models apart. llama3.1 showed soft failures that the strict grader did not count: on a no-tool prompt it wrote a fake tool call as plain text, and its answers after receiving tool results were weak.

**Approved by Daniel on 2026-10-19 (all four):**
1. Primary model: `qwen3:8b`. Comparison model: `llama3.1:8b`. Reason: both exist in the Ollama library with the `tools` tag, run fully on the GPU in about 6 GB, and come from different model families.
2. Set `think=False` explicitly for qwen3 by default, and run thinking-on as a measured ablation in Phase 5. Reason: the accuracy was the same and it was about 5x faster. Ollama turns thinking on by default for qwen3, so it must always be set explicitly.
3. Pin `mcp>=2.3,<3`, and use `mcp.server.mcpserver.MCPServer`. Reason: MCP v2 renamed FastMCP, and most online examples still assume v1.
4. Always pass `temperature` explicitly. Reason: qwen3's Modelfile default is 0.6, not 0.

**Scaffold (2026-10-19).** Created the planned project layout with `uv init --lib` and ran `git init`. Added a `results/` folder for Phase 6's `results/CHANGELOG.md`. The dev tools are pytest and ruff. `privacy_denylist.txt` is git-ignored for the local list of real identifiers. First commit made after Daniel approved it.
