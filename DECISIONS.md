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

## Gate 1: Octavious recon (2026-10-19)

**Source.** Daniel chose `octavious-oss`, the public sanitized release, over the private repo. The private repo has a `.env` file and a `backups/` folder; neither was opened. Recon was read-only and recorded schema shapes only. The report scan found no IDs, emails or URLs.

**Findings that change the draft tool list:**
- XP is stored only as an all-time total. A weekly or monthly XP leaderboard can't be computed. Hourly activity stats (messages, voice, reactions per member) are kept for 400 days.
- There are no warnings, no moderation queue and no ban command. Moderation data is an AutoMod event log (no status or severity) plus free-text staff notes.
- There is no role hierarchy or staff role assignment. The only automatic roles are 24 colour roles with unlock rules.
- Levels go from 0 to 50 using a fixed XP table, then prestige resets the level.

**Approved by Daniel on 2026-10-19 (all seven):**
1. `get_leaderboard` gets a `metric` parameter (xp, messages, voice_minutes, reactions). XP is all-time only; asking for weekly XP returns an `UNSUPPORTED_WINDOW` error with a hint.
2. Rename `get_moderation_queue` to `get_automod_log`. Severity is derived from the AutoMod action, and a review `status` is added as a labelled toolward extension.
3. `lookup_member` returns `staff_note_count` and `automod_events_90d` instead of `warning_count`.
4. Keep `ban_member` as a labelled extension (member ID only, no names; a reason and `confirm=true` are required).
5. Keep `assign_role` with an invented, generic staff hierarchy plus the bot's colour unlock rules. The acting staff identity is server config, not a tool argument.
6. Ties use competition ranking (1, 2, 2, 4), with tied members listed by member ID. An active member is one with any activity in the window.
7. Fixtures include a null `joined_at` for members who joined before the bot. They don't reproduce the bot's duplicate-row-on-rejoin bug.

## Gate 2: Synthetic data (2026-10-19)

**Built.** A seeded generator (`src/toolward/data/`), `fixtures/community.json` (1.42 MB), `fixtures/EDGE_CASES.md`, a privacy scan (`src/toolward/privacy.py`, `scripts/scan_for_secrets.py`), a pre-commit hook script (not installed) and 71 tests. Tests, ruff and the scan all pass. A planted 19-digit number was caught.

**Made without asking (follows the hard rules):** synthetic IDs use prefixes (`mem_0001`) instead of Discord-style 17-20 digit numbers, so the privacy scan never needs an exception for long numbers.

**Fixtures.** 140 members (incl. bot), 45 days of hourly stats from 2026-08-17 to a fixed "now" of 2026-10-01 with a 6-hour outage on 2026-09-27, 61 AutoMod events, 22 staff notes, 2 banned members.

**Approved by Daniel on 2026-10-19 (all five):**
1. Keep `mem_0115`, whose display name is a prompt-injection string, in the fixtures from the start, so the fixtures stay the same between the baseline and Phase 6 and the before/after comparison stays fair.
2. `lookup_member` matches `name` against username or display name, ignoring case. If more than one member matches, it returns `AMBIGUOUS_NAME` with the candidates.
3. For messages, voice and reactions, `all_time` means "since stats began (2026-08-17)", and the tool output says so.
4. `assign_role` refuses prestige colours, because the bot manages them automatically.
5. Install the pre-commit hook locally with a symlink in `.git/hooks`.
