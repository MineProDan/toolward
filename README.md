# toolward

An MCP server with community-operations tools, a tool-calling agent that runs on a local model through Ollama, and a code-graded eval suite that measures how reliably the agent uses those tools.

Work in progress. Results, architecture and setup instructions will be added as each phase lands. All data in this repo is synthetic.

License: MIT.

## Tools

The MCP server (`src/toolward/server/`) exposes 7 tools over a synthetic community in `fixtures/community.json`. The tools model a Discord community bot: XP and levels, AutoMod, colour roles and hourly activity stats. A few parts don't exist in the bot and are marked as **toolward extensions**.

Run it over stdio with `uv run toolward-server` (or `uv run python -m toolward.server`). Options: `--tools lookup_member,get_leaderboard` exposes a subset, and `--fixtures PATH` serves another fixtures file.

How the server behaves:

- **Fixed clock.** "Now" is always `config.reference_now` (`2026-10-01T00:00:00Z`), never the system time, so every run gives the same answers.
- **Fixed identity.** The agent acts as the staff member in `config.acting_member_id` (a Moderator). It is never a tool argument.
- **Sandboxed state.** Every server instance works on its own in-memory copy of the fixtures. `ban_member` and `assign_role` change only that copy. The fixtures file is never written.
- **Previews first.** State-changing tools do nothing unless `confirm=true`. Refusals (staff, roles above the actor, and so on) are checked before the confirm step, so a preview never suggests that a forbidden action would work.
- **Member text is left as is.** Display names and other member-controlled text are returned unchanged, even when they look like instructions. The evals measure how the agent handles that.
- **Descriptions are versioned.** Tool and parameter descriptions live in `src/toolward/server/descriptions.py` as `DESCRIPTIONS_V1`, the baseline for the experiment. `create_server(descriptions=...)` switches versions.

### Errors

A refused or failed call returns `is_error: true` and a JSON body the model can act on:

```json
{"error": {"code": "AMBIGUOUS_NAME",
           "message": "3 members match 'quietfern' (usernames: quiet.fern, quietfern.music, quiet_fern22).",
           "hint": "Call lookup_member again with member_id set to one of the candidates, or ask the user which one they mean.",
           "candidates": [{"member_id": "mem_0050", "display_name": "quietfern"}, "..."]}}
```

Codes shared by several tools: `INVALID_MEMBER_ID` (the ID doesn't look like `mem_0042`; the hint says to use `lookup_member(name=...)`) and `NOT_FOUND`. Arguments of the wrong type or out of range (for example `limit=99`) are rejected by the MCP SDK before the tool runs, and also come back with `is_error: true`.

### Summary

| Tool | Risk | Mirrors the bot or extension |
|---|---|---|
| `lookup_member` | read | Mirrors the bot's member profile (XP, level, prestige, roles, achievements) |
| `get_leaderboard` | read | Mirrors the bot's leaderboards and hourly stats |
| `get_automod_log` | read | Mirrors the bot's AutoMod log; the review `status` is an extension |
| `draft_announcement` | write-draft (never sends) | Extension |
| `ban_member` | **destructive** | Extension (the bot has no ban command) |
| `get_community_stats` | read | Mirrors the bot's hourly activity stats and snapshots |
| `assign_role` | write, medium risk | Colour unlock rules mirror the bot; the staff hierarchy check is an extension |

### `lookup_member` (read)

Looks up one member's profile.

- **Parameters:** `member_id` (like `mem_0042`) or `name`. Give exactly one. `name` matches a username or display name exactly, ignoring case.
- **Output:** `member_id`, `username`, `display_name`, `total_xp`, `level`, `prestige`, `xp_to_next_level`, `rank` (XP rank among current members, with ties sharing a rank; `null` for members who aren't in the server and for the bot), `roles` (all role names, highest first), `color_roles`, `joined_at` (`null` for members who joined before the bot was added), `in_server`, `is_banned`, `staff_note_count`, `automod_events_90d`, `achievements_unlocked`, `is_booster`, and a `note` explaining a null join date, a ban or a departure.
- **Errors:** `BOTH_OR_NEITHER`, `AMBIGUOUS_NAME` (with candidates), `NOT_FOUND` (with up to 3 similar names as candidates when there are any), `INVALID_MEMBER_ID`.

### `get_leaderboard` (read)

Ranks members by XP or activity.

- **Parameters:** `metric` (`xp`, `messages`, `voice_minutes`, `reactions`; default `xp`), `window` (`all_time`, `week` = the 7 days before now, `month` = the 30 days before now; default `all_time`), `limit` (1-25, default 10).
- **Output:** `entries` (`rank`, `member_id`, `display_name`, `value`, `tied`), `metric`, `window`, `window_start`, `window_end`, `tie_rule`, `note`.
- **Rules:** competition ranking (1, 2, 2, 4), with tied members listed by member ID. Everyone tied at the last rank is included even past `limit`, and the note says so. The bot, members who left and banned members are excluded, and so are members with a value of 0. For activity metrics `all_time` means since hourly stats began (2026-08-17), and the note says so.
- **Errors:** `UNSUPPORTED_WINDOW` for `xp` with `week` or `month`, because XP is only stored as an all-time total.

### `get_automod_log` (read)

Lists AutoMod events, newest first.

- **Parameters:** `status` (`open`, `reviewed`, `dismissed`, `any`; default `open`), `action` (`block_message`, `send_alert`, `timeout`, `block_interaction`, `any`; default `any`), `member_id` (optional), `since_hours` (1-8760, default 168), `limit` (1-50, default 20).
- **Output:** `events` (`event_id`, `occurred_at`, `age_hours`, `member_id`, `member_name`, `rule_name`, `trigger_type`, `action`, `severity`, `status`, `matched_keyword`), `total_matching`, `since`, `note`.
- **Rules:** severity is derived from the action: `timeout` = high, `block_message` and `block_interaction` = medium, `send_alert` = low. **Extension:** the bot logs AutoMod actions but has no review workflow, so `status` is added by toolward.
- **Errors:** `NOT_FOUND` and `INVALID_MEMBER_ID` for the `member_id` filter.

### `draft_announcement` (write-draft, never sends)

Writes a draft announcement for staff to post themselves. **Extension.** The draft comes from a fixed template per tone (no language model inside the tool), so the same input always gives the same text.

- **Parameters:** `topic` (3-200 characters, at least 2 words), `audience` (`everyone`, `new_members` = joined in the last 7 days, `prestiged`, `boosters`, `staff`; default `everyone`), `tone` (`hype`, `friendly`, `formal`, `serious`; default `friendly`), `max_chars` (100-2000, default 800).
- **Output:** `draft`, `char_count`, `audience`, `tone`, `estimated_reach` (current members in the audience), `truncated`, `sent` (always `false`), `note`.
- **Errors:** `TOPIC_TOO_VAGUE` (under 3 characters or under 2 words), `TOPIC_TOO_LONG` (over 200 characters).

### `ban_member` (destructive)

Bans a member. **Extension:** the bot itself has no ban command.

- **Parameters:** `member_id` (ID only; there is no name parameter), `reason` (5-512 characters), `confirm` (default `false`).
- **Output with `confirm=false`:** a preview that changes nothing: `executed: false`, `would_ban` (`member_id`, `display_name`), `level`, `prestige`, `in_server`, `staff_note_count`, `automod_events_90d`, `joined_at` and a message saying to call again with `confirm=true`.
- **Output with `confirm=true`:** `executed: true`, `banned_at`, `member`, `reason`, `logged_to: "moderation_log"`. The member is added to `banned_members`, loses their roles and leaves the server, and the ban is written to the moderation log with the acting staff member as the actor.
- **Errors:** `CANNOT_BAN_SELF_OR_BOT`, `CANNOT_BAN_STAFF` (any staff role), `ALREADY_BANNED`, `REASON_REQUIRED` (too short or too long), `NOT_FOUND`, `INVALID_MEMBER_ID`. Members who left the server can still be banned.

### `get_community_stats` (read)

Sums the hourly activity records for a window.

- **Parameters:** `window`: `last_24h`, `last_7d` (default), `last_30d`, `previous_7d` (the 7 days before `last_7d`) or `previous_30d` (the 30 days before `last_30d`).
- **Output:** `window_start`, `window_end`, `messages`, `replies`, `attachments`, `thread_messages`, `reactions`, `voice_minutes`, `commands`, `joins`, `leaves`, `net_growth`, `active_members` (anyone who messaged, reacted, used voice or ran a command), `active_chatters` (anyone who messaged), `busiest_hour_utc` (hour of day 0-23 with the most messages, or `null`), `top_channels` and `top_commands` (up to 5 each), `latest_snapshot` (member, online, boost and voice counts at or before the window end; `online` can be `null`, which means unknown, not 0), `hours_with_data`, `hours_in_window`, `partial`, `data_starts_at` and `coverage_note`.
- **Rules:** an hour with a snapshot but no activity record was quiet and counts as zero. An hour with neither means the bot was offline, and `coverage_note` lists those gaps. A window that starts before stats began (2026-08-17) returns the data that exists with `partial: true`.
- **Errors:** `NO_DATA_YET` when the whole window is before stats began.

### `assign_role` (write, medium risk)

Gives a member a role.

- **Parameters:** `member_id`, `role_name` (case is ignored), `confirm` (default `false`).
- **Output:** `executed`, `member`, `role`, `replaced_roles`, `message`, and `logged_to` when executed. With `confirm=false` nothing changes. With `confirm=true` the role is added, any replaced role is removed, and the change is written to the moderation log.
- **Rules:** colour roles mirror the bot. A member has an automatic prestige colour, plus at most one picked colour (milestone, rare or booster) that they must have unlocked; a new picked colour replaces the old one. **Extension:** the acting Moderator can only assign roles below their own highest role, as Discord's role hierarchy requires.
- **Errors:** `ROLE_NOT_FOUND` (with up to 3 similar names in the hint), `ROLE_ABOVE_ACTOR`, `ROLE_AUTO_MANAGED` (prestige colours, `Member`, the bot role), `MEMBER_NOT_IN_SERVER` (left or banned), `ALREADY_HAS_ROLE`, `COLOR_NOT_UNLOCKED` (the message states the requirement), `NOT_FOUND`, `INVALID_MEMBER_ID`.
