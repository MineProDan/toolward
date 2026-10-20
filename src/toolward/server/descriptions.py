"""Tool and parameter descriptions, versioned so the experiment can compare them.

DESCRIPTIONS_V1 is the baseline: written to be clear and specific, without tuning against
observed model failures. Phase 6 adds DESCRIPTIONS_V2 next to it and passes it to
create_server(descriptions=...), so both versions stay runnable and the score change can be
measured.

Shape: {tool_name: {"description": str, "params": {param_name: str}}}
"""

DESCRIPTIONS_V1: dict[str, dict] = {
    "lookup_member": {
        "description": (
            "Look up one community member's profile: level, prestige, XP, XP needed for the "
            "next level, XP rank, roles, join date, whether they are in the server or banned, "
            "staff note count and AutoMod events in the last 90 days. Give exactly one of "
            "member_id or name. A name matches a username or display name exactly, ignoring "
            "case; if several members share it, the error lists their IDs as candidates. "
            "Read-only."
        ),
        "params": {
            "member_id": "The member's ID, like mem_0042. Leave empty when using name.",
            "name": (
                "The member's username or display name (case is ignored). "
                "Leave empty when using member_id."
            ),
        },
    },
    "get_leaderboard": {
        "description": (
            "Rank members by XP or by activity. XP is an all-time total only, so metric='xp' "
            "works only with window='all_time'. Activity metrics (messages, voice_minutes, "
            "reactions) work for week (last 7 days), month (last 30 days) or all_time (since "
            "activity stats began). Ties share a rank (1, 2, 2, 4), and everyone tied at the "
            "last rank is included even if that passes the limit. The bot, members who left "
            "and banned members are left out. Read-only."
        ),
        "params": {
            "metric": "What to rank by: xp, messages, voice_minutes or reactions.",
            "window": (
                "Time window: all_time, week (last 7 days) or month (last 30 days). "
                "XP supports all_time only."
            ),
            "limit": "How many top places to return, 1-25.",
        },
    },
    "get_automod_log": {
        "description": (
            "List AutoMod events (messages the bot blocked, alerts, timeouts), newest first. "
            "Filter by review status, action, member and time. Each event has a severity "
            "derived from its action (timeout = high, block_message and block_interaction = "
            "medium, send_alert = low). The review status (open, reviewed, dismissed) is a "
            "toolward extension. Read-only."
        ),
        "params": {
            "status": "Review status to show: open (not reviewed yet), reviewed, dismissed or any.",
            "action": (
                "Only events with this AutoMod action: block_message, send_alert, timeout, "
                "block_interaction or any."
            ),
            "member_id": "Only events for this member ID, like mem_0042. Leave empty for everyone.",
            "since_hours": "Only events from the last this many hours (1-8760). 168 = one week.",
            "limit": "Maximum number of events to return, 1-50.",
        },
    },
    "draft_announcement": {
        "description": (
            "Write a draft announcement for staff to review. It never posts or sends anything. "
            "Returns the draft text, its length and how many current members are in the "
            "chosen audience."
        ),
        "params": {
            "topic": "What the announcement is about, in a few words (3-200 characters).",
            "audience": (
                "Who it is for: everyone, new_members (joined in the last 7 days), prestiged "
                "(prestige 1 or higher), boosters or staff."
            ),
            "tone": "Writing style: hype, friendly, formal or serious.",
            "max_chars": "Maximum length of the draft in characters, 100-2000.",
        },
    },
    "ban_member": {
        "description": (
            "Ban a member from the server. Destructive. This is a toolward extension; the "
            "original bot has no ban command. Takes a member ID only, so look the member up "
            "first if you only have a name. With confirm=false (the default) it returns a "
            "preview and changes nothing; with confirm=true it bans the member and writes to "
            "the moderation log. Staff, the bot, your own account and already-banned members "
            "can't be banned."
        ),
        "params": {
            "member_id": "ID of the member to ban, like mem_0042.",
            "reason": "Why the member is being banned (5-512 characters). Saved in the log.",
            "confirm": (
                "false = preview only, nothing changes. true = really ban. Set true only after "
                "the user has confirmed the ban."
            ),
        },
    },
    "get_community_stats": {
        "description": (
            "Get server activity totals for a time window: messages, replies, reactions, voice "
            "minutes, commands, joins, leaves, active members, busiest hour, top channels and "
            "commands, and the latest member count snapshot. Windows end at the current time "
            "(last_*) or just before the matching last_* window starts (previous_*). The "
            "result says how many hours have data, since the bot may have been offline. "
            "Read-only."
        ),
        "params": {
            "window": (
                "Time window: last_24h, last_7d, last_30d, previous_7d (the 7 days before "
                "last_7d) or previous_30d (the 30 days before last_30d)."
            ),
        },
    },
    "assign_role": {
        "description": (
            "Give a member a role. Changes server state. You can only assign roles below your "
            "own highest role; roles the bot manages (prestige colours, Member) and colours "
            "the member hasn't unlocked are refused. A picked colour replaces the member's "
            "previous picked colour. With confirm=false (the default) it returns a preview and "
            "changes nothing; with confirm=true it assigns the role and writes to the "
            "moderation log."
        ),
        "params": {
            "member_id": "ID of the member, like mem_0042.",
            "role_name": "Name of the role to give, like 'Event Pings' (case is ignored).",
            "confirm": (
                "false = preview only, nothing changes. true = really assign. Set true only "
                "after the user has confirmed."
            ),
        },
    },
}
