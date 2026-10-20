"""The tool logic as plain functions over a Community, testable without MCP.

Each function takes the in-memory community as its first argument and returns an output model
from models.py, or raises ToolFailure with a structured error. ban_member and assign_role (with
confirm=True) change the Community they are given. app.py gives every server its own deep copy,
so fixtures/community.json is never touched.

"Now" is always config.reference_now, never the system clock, so results are reproducible.
"""

import difflib
import re
from collections import Counter
from datetime import datetime, timedelta

from toolward.data.levels import xp_to_next_level
from toolward.data.schema import (
    BannedMember,
    Community,
    Member,
    ModerationLogEntry,
    Role,
    from_iso,
    to_iso,
)
from toolward.server.models import (
    AnnouncementDraft,
    Audience,
    AutomodActionFilter,
    AutomodLog,
    AutomodLogEntry,
    AutomodStatus,
    BanPreview,
    BanResult,
    ChannelCount,
    CommandCount,
    CommunityStats,
    Leaderboard,
    LeaderboardEntry,
    LeaderboardMetric,
    LeaderboardWindow,
    MemberProfile,
    MemberRef,
    RoleChange,
    SnapshotOut,
    StatsWindow,
    Tone,
    ToolFailure,
)

MEMBER_ID_PATTERN = re.compile(r"^mem_\d{4}$")
HOUR = timedelta(hours=1)

SEVERITY = {
    "timeout": "high",
    "block_message": "medium",
    "block_interaction": "medium",
    "send_alert": "low",
}

# Colour groups a member picks themselves. A member holds at most one picked colour, on top of
# the automatic prestige colour.
PICKED_COLOR_GROUPS = {"milestone", "rare", "booster"}

TIE_RULE = (
    "Competition ranking (1, 2, 2, 4): tied members share a rank and the next rank is skipped. "
    "Tied members are listed by member_id."
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _now(community: Community) -> datetime:
    return from_iso(community.config.reference_now)


def _ref(member: Member) -> MemberRef:
    return MemberRef(member_id=member.member_id, display_name=member.display_name)


def _clean(text: str | None) -> str | None:
    """Strip whitespace; treat an empty string the same as a missing value."""
    if text is None:
        return None
    return text.strip() or None


def _find_member(community: Community, member_id: str) -> Member:
    member_id = member_id.strip()
    if not MEMBER_ID_PATTERN.match(member_id):
        raise ToolFailure(
            "INVALID_MEMBER_ID",
            f"'{member_id}' is not a member ID. Member IDs look like mem_0042.",
            "If you only know the member's name, call lookup_member(name=...) first "
            "to get their member_id.",
        )
    for member in community.members:
        if member.member_id == member_id:
            return member
    raise ToolFailure(
        "NOT_FOUND",
        f"No member has the ID {member_id}.",
        "Check the ID, or call lookup_member(name=...) to find the right member_id.",
    )


def _banned_ids(community: Community) -> set[str]:
    return {ban.member_id for ban in community.banned_members}


def _member_roles(community: Community, member: Member) -> list[Role]:
    """The member's roles, highest position first."""
    by_id = {role.role_id: role for role in community.roles}
    roles = [by_id[role_id] for role_id in member.roles if role_id in by_id]
    return sorted(roles, key=lambda role: -role.position)


def _staff_role(community: Community, member: Member) -> Role | None:
    """The member's highest staff role, or None if they aren't staff."""
    for role in _member_roles(community, member):
        if role.kind == "staff":
            return role
    return None


def _eligible_members(community: Community) -> list[Member]:
    """Members who count for rankings: in the server, not the bot, not banned."""
    banned = _banned_ids(community)
    return [
        m for m in community.members if m.in_server and not m.is_bot and m.member_id not in banned
    ]


def _automod_events_90d(community: Community, member_id: str) -> int:
    now = _now(community)
    start = now - timedelta(days=90)
    return sum(
        1
        for event in community.automod_events
        if event.member_id == member_id and start <= from_iso(event.occurred_at) <= now
    )


def _staff_note_count(community: Community, member_id: str) -> int:
    return sum(1 for note in community.staff_notes if note.member_id == member_id)


def _ranked(scores: dict[str, int | float]) -> list[tuple[int, str, int | float]]:
    """Competition ranking (1, 2, 2, 4). Returns (rank, member_id, value), best first."""
    ordered = sorted(scores, key=lambda member_id: (-scores[member_id], member_id))
    result: list[tuple[int, str, int | float]] = []
    for position, member_id in enumerate(ordered, start=1):
        value = scores[member_id]
        rank = result[-1][0] if result and result[-1][2] == value else position
        result.append((rank, member_id, value))
    return result


def _hours(start: datetime, end: datetime) -> list[datetime]:
    """Every hour start in [start, end)."""
    hours = []
    moment = start
    while moment < end:
        hours.append(moment)
        moment += HOUR
    return hours


# ---------------------------------------------------------------------------
# 1. lookup_member
# ---------------------------------------------------------------------------


def _find_by_name(community: Community, name: str) -> Member:
    wanted = name.casefold()
    matches = [
        m for m in community.members if wanted in (m.username.casefold(), m.display_name.casefold())
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        matches.sort(key=lambda m: m.member_id)
        usernames = ", ".join(m.username for m in matches)
        raise ToolFailure(
            "AMBIGUOUS_NAME",
            f"{len(matches)} members match '{name}' (usernames: {usernames}).",
            "Call lookup_member again with member_id set to one of the candidates, "
            "or ask the user which one they mean.",
            candidates=[_ref(m) for m in matches],
        )
    # No exact match: offer up to 3 similar names in case of a typo.
    all_names = {n.casefold() for m in community.members for n in (m.username, m.display_name)}
    close = set(difflib.get_close_matches(wanted, sorted(all_names), n=3, cutoff=0.75))
    candidates = [
        _ref(m)
        for m in community.members
        if m.username.casefold() in close or m.display_name.casefold() in close
    ]
    hint = "Names must match a username or display name exactly (case is ignored). "
    if candidates:
        hint += "Similar members are listed in candidates; confirm with the user before using one."
    else:
        hint += "Check the spelling, or ask the user for the member's ID."
    raise ToolFailure(
        "NOT_FOUND",
        f"No member has the username or display name '{name}'.",
        hint,
        candidates=candidates,
    )


def lookup_member(
    community: Community, member_id: str | None = None, name: str | None = None
) -> MemberProfile:
    member_id = _clean(member_id)
    name = _clean(name)
    if (member_id is None) == (name is None):
        given = "both" if member_id else "neither"
        raise ToolFailure(
            "BOTH_OR_NEITHER",
            f"Give exactly one of member_id or name; you gave {given}.",
            "Call lookup_member with only member_id (like mem_0042) or only name.",
        )
    member = _find_member(community, member_id) if member_id else _find_by_name(community, name)

    banned = {ban.member_id: ban for ban in community.banned_members}
    scores = {m.member_id: m.total_xp for m in _eligible_members(community)}
    rank = None
    if member.member_id in scores:
        rank = next(r for r, mid, _ in _ranked(scores) if mid == member.member_id)

    roles = _member_roles(community, member)
    notes = []
    if member.joined_at is None:
        notes.append(
            "joined_at is null because this member joined before the bot was added "
            f"({community.config.bot_added_at}); the real join date is unknown."
        )
    if member.member_id in banned:
        notes.append(f"Banned on {banned[member.member_id].banned_at}.")
    elif not member.in_server and member.left_at:
        notes.append(f"Left the server on {member.left_at}.")

    return MemberProfile(
        member_id=member.member_id,
        username=member.username,
        display_name=member.display_name,
        total_xp=member.total_xp,
        level=member.level,
        prestige=member.prestige,
        xp_to_next_level=xp_to_next_level(member.total_xp),
        rank=rank,
        roles=[role.name for role in roles],
        color_roles=[role.name for role in roles if role.kind == "color"],
        joined_at=member.joined_at,
        in_server=member.in_server,
        is_banned=member.member_id in banned,
        staff_note_count=_staff_note_count(community, member.member_id),
        automod_events_90d=_automod_events_90d(community, member.member_id),
        achievements_unlocked=member.achievements_unlocked,
        is_booster=member.is_booster,
        note=" ".join(notes) or None,
    )


# ---------------------------------------------------------------------------
# 2. get_leaderboard
# ---------------------------------------------------------------------------

# Which per-member map in an HourlyActivity record holds each activity metric.
ACTIVITY_MAPS = {"messages": "members", "voice_minutes": "voice", "reactions": "reactors"}


def _activity_totals(
    community: Community, metric: str, start: datetime, end: datetime
) -> dict[str, int | float]:
    totals: Counter[str] = Counter()
    for record in community.hourly_activity:
        if start <= from_iso(record.hour_start) < end:
            totals.update(getattr(record, ACTIVITY_MAPS[metric]))
    if metric == "voice_minutes":
        return {member_id: round(value, 1) for member_id, value in totals.items()}
    return dict(totals)


def get_leaderboard(
    community: Community,
    metric: LeaderboardMetric = "xp",
    window: LeaderboardWindow = "all_time",
    limit: int = 10,
) -> Leaderboard:
    now = _now(community)
    stats_start = from_iso(community.config.stats_started_at)
    eligible = {m.member_id: m for m in _eligible_members(community)}
    notes = []

    if metric == "xp":
        if window != "all_time":
            raise ToolFailure(
                "UNSUPPORTED_WINDOW",
                f"XP has no {window} history: it is only stored as an all-time total.",
                "Use window='all_time' for XP, or use metric='messages' to rank activity "
                f"in the last {window}.",
            )
        window_start = None
        scores = {member_id: m.total_xp for member_id, m in eligible.items()}
    else:
        if window == "week":
            start = now - timedelta(days=7)
        elif window == "month":
            start = now - timedelta(days=30)
        else:
            start = stats_start
        if window == "all_time":
            notes.append(
                f"Activity stats only exist since {community.config.stats_started_at}, "
                "so all_time means since then."
            )
        elif start < stats_start:
            notes.append(
                f"Activity stats only exist since {community.config.stats_started_at}, "
                "so the start of this window has no data."
            )
        window_start = to_iso(start)
        totals = _activity_totals(community, metric, start, now)
        scores = {member_id: v for member_id, v in totals.items() if member_id in eligible}

    # Members with nothing to count don't belong on a leaderboard.
    scores = {member_id: v for member_id, v in scores.items() if v > 0}
    ranked = _ranked(scores)
    shown = ranked
    if len(ranked) > limit:
        # Keep everyone tied with the last place that fits, even if that passes the limit.
        cutoff_rank = ranked[limit - 1][0]
        shown = [row for row in ranked if row[0] <= cutoff_rank]
        if len(shown) > limit:
            notes.append(
                f"Returned {len(shown)} entries instead of {limit} because members are tied "
                f"at rank {cutoff_rank}."
            )
    elif len(ranked) < limit:
        notes.append(f"Only {len(ranked)} members have a non-zero value, so fewer are listed.")

    value_counts = Counter(value for _, _, value in ranked)
    entries = [
        LeaderboardEntry(
            rank=rank,
            member_id=member_id,
            display_name=eligible[member_id].display_name,
            value=value,
            tied=value_counts[value] > 1,
        )
        for rank, member_id, value in shown
    ]
    return Leaderboard(
        entries=entries,
        metric=metric,
        window=window,
        window_start=window_start,
        window_end=community.config.reference_now,
        tie_rule=TIE_RULE,
        note=" ".join(notes) or None,
    )


# ---------------------------------------------------------------------------
# 3. get_automod_log
# ---------------------------------------------------------------------------


def get_automod_log(
    community: Community,
    status: AutomodStatus = "open",
    action: AutomodActionFilter = "any",
    member_id: str | None = None,
    since_hours: int = 168,
    limit: int = 20,
) -> AutomodLog:
    now = _now(community)
    since = now - timedelta(hours=since_hours)
    member_id = _clean(member_id)
    if member_id is not None:
        member_id = _find_member(community, member_id).member_id

    matching = [
        event
        for event in community.automod_events
        if since <= from_iso(event.occurred_at) <= now
        and status in ("any", event.status)
        and action in ("any", event.action)
        and member_id in (None, event.member_id)
    ]
    matching.sort(key=lambda event: (event.occurred_at, event.event_id), reverse=True)

    events = [
        AutomodLogEntry(
            event_id=event.event_id,
            occurred_at=event.occurred_at,
            age_hours=round((now - from_iso(event.occurred_at)) / HOUR, 1),
            member_id=event.member_id,
            member_name=event.member_name,
            rule_name=event.rule_name,
            trigger_type=event.trigger_type,
            action=event.action,
            severity=SEVERITY[event.action],
            status=event.status,
            matched_keyword=event.matched_keyword,
        )
        for event in matching[:limit]
    ]
    note = (
        "status is a toolward review extension (open = not reviewed yet); the bot itself "
        "does not track reviews. Severity comes from the action: timeout = high, "
        "block_message and block_interaction = medium, send_alert = low."
    )
    if len(matching) > limit:
        note = f"Showing the newest {limit} of {len(matching)} matching events. " + note
    return AutomodLog(events=events, total_matching=len(matching), since=to_iso(since), note=note)


# ---------------------------------------------------------------------------
# 4. draft_announcement
# ---------------------------------------------------------------------------

GREETINGS = {
    "everyone": "Hi everyone",
    "new_members": "Welcome to all our new members",
    "prestiged": "Calling all prestiged members",
    "boosters": "A note for our server boosters",
    "staff": "Hi staff team",
}

TEMPLATES = {
    "hype": "{greeting}! Big news: {topic}! You won't want to miss this, so drop a reaction "
    "if you're in!",
    "friendly": "{greeting}! Quick heads-up: {topic}. Questions are welcome in this channel.",
    "formal": "{greeting}. Please note the following: {topic}. Any questions can be directed "
    "to the staff team.",
    "serious": "{greeting}. Important notice: {topic}. Please read this carefully and contact "
    "a staff member if anything is unclear.",
}


def _audience_size(community: Community, audience: Audience) -> int:
    week_ago = _now(community) - timedelta(days=7)
    members = _eligible_members(community)
    if audience == "new_members":
        members = [m for m in members if m.joined_at and from_iso(m.joined_at) >= week_ago]
    elif audience == "prestiged":
        members = [m for m in members if m.prestige >= 1]
    elif audience == "boosters":
        members = [m for m in members if m.is_booster]
    elif audience == "staff":
        members = [m for m in members if _staff_role(community, m)]
    return len(members)


def draft_announcement(
    community: Community,
    topic: str,
    audience: Audience = "everyone",
    tone: Tone = "friendly",
    max_chars: int = 800,
) -> AnnouncementDraft:
    topic = " ".join(topic.split())  # collapse runs of whitespace
    if len(topic) < 3 or len(topic.split()) < 2:
        raise ToolFailure(
            "TOPIC_TOO_VAGUE",
            f"The topic '{topic}' is too vague to write an announcement from.",
            "Ask the user what the announcement should say, then call again with a topic of "
            "at least 2 words (for example 'movie night on Friday at 8pm UTC').",
        )
    if len(topic) > 200:
        raise ToolFailure(
            "TOPIC_TOO_LONG",
            f"The topic is {len(topic)} characters; the limit is 200.",
            "Shorten the topic to its key point in under 200 characters and call again.",
        )
    # The template adds its own punctuation after the topic.
    body = topic.rstrip(".!?") or topic
    draft = TEMPLATES[tone].format(greeting=GREETINGS[audience], topic=body)
    truncated = len(draft) > max_chars
    if truncated:
        draft = draft[: max_chars - 3].rstrip() + "..."
    return AnnouncementDraft(
        draft=draft,
        char_count=len(draft),
        audience=audience,
        tone=tone,
        estimated_reach=_audience_size(community, audience),
        truncated=truncated,
        note="Draft only. Nothing was posted; a staff member has to post it themselves.",
    )


# ---------------------------------------------------------------------------
# 5. ban_member
# ---------------------------------------------------------------------------


def ban_member(
    community: Community, member_id: str, reason: str, confirm: bool = False
) -> BanPreview | BanResult:
    config = community.config
    member = _find_member(community, member_id)
    who = f"{member.display_name} ({member.member_id})"

    # Refusals come before the confirm check, so a preview never suggests the ban is allowed.
    if member.member_id == config.acting_member_id:
        raise ToolFailure(
            "CANNOT_BAN_SELF_OR_BOT",
            f"{member.member_id} is your own staff account; you can't ban yourself.",
            "Nothing was changed. Tell the user this ban isn't allowed.",
        )
    if member.member_id == config.bot_member_id:
        raise ToolFailure(
            "CANNOT_BAN_SELF_OR_BOT",
            f"{member.member_id} is the community bot and can't be banned.",
            "Nothing was changed. Tell the user this ban isn't allowed.",
        )
    staff_role = _staff_role(community, member)
    if staff_role:
        raise ToolFailure(
            "CANNOT_BAN_STAFF",
            f"{who} has the {staff_role.name} role. Staff members can't be banned with this tool.",
            "Nothing was changed. Tell the user that banning staff isn't allowed here.",
        )
    for ban in community.banned_members:
        if ban.member_id == member.member_id:
            raise ToolFailure(
                "ALREADY_BANNED",
                f"{who} was already banned on {ban.banned_at}.",
                "Nothing was changed. No further action is needed.",
            )

    reason = reason.strip()
    if len(reason) < 5:
        raise ToolFailure(
            "REASON_REQUIRED",
            "A ban needs a reason of at least 5 characters.",
            "Ask the user why this member should be banned, then call again with that reason.",
        )
    if len(reason) > 512:
        raise ToolFailure(
            "REASON_REQUIRED",
            f"The reason is {len(reason)} characters; the limit is 512.",
            "Shorten the reason to under 512 characters and call again.",
        )

    if not confirm:
        return BanPreview(
            would_ban=_ref(member),
            level=member.level,
            prestige=member.prestige,
            in_server=member.in_server,
            staff_note_count=_staff_note_count(community, member.member_id),
            automod_events_90d=_automod_events_90d(community, member.member_id),
            joined_at=member.joined_at,
            message="Preview only. Nothing was changed. Call again with confirm=true to ban.",
        )

    now = config.reference_now
    community.banned_members.append(
        BannedMember(
            member_id=member.member_id,
            banned_at=now,
            banned_by=config.acting_member_id,
            reason=reason,
        )
    )
    community.moderation_log.append(
        ModerationLogEntry(
            log_id=f"modlog_{len(community.moderation_log) + 1:04d}",
            at=now,
            action="ban",
            actor_member_id=config.acting_member_id,
            target_member_id=member.member_id,
            reason=reason,
        )
    )
    member.in_server = False
    member.roles = []
    return BanResult(banned_at=now, member=_ref(member), reason=reason)


# ---------------------------------------------------------------------------
# 6. get_community_stats
# ---------------------------------------------------------------------------

# window name -> (length, how far its end is before now)
STATS_WINDOWS = {
    "last_24h": (timedelta(hours=24), timedelta(0)),
    "last_7d": (timedelta(days=7), timedelta(0)),
    "last_30d": (timedelta(days=30), timedelta(0)),
    "previous_7d": (timedelta(days=7), timedelta(days=7)),
    "previous_30d": (timedelta(days=30), timedelta(days=30)),
}


def _hour_ranges(hours: list[datetime]) -> list[tuple[datetime, datetime]]:
    """Group sorted hour starts into (start, end) runs of consecutive hours."""
    ranges: list[tuple[datetime, datetime]] = []
    for hour in hours:
        if ranges and ranges[-1][1] == hour:
            ranges[-1] = (ranges[-1][0], hour + HOUR)
        else:
            ranges.append((hour, hour + HOUR))
    return ranges


def get_community_stats(community: Community, window: StatsWindow = "last_7d") -> CommunityStats:
    config = community.config
    stats_start = from_iso(config.stats_started_at)
    length, offset = STATS_WINDOWS[window]
    end = _now(community) - offset
    start = end - length
    if end <= stats_start:
        raise ToolFailure(
            "NO_DATA_YET",
            f"Activity stats start at {config.stats_started_at}; the {window} window "
            f"({to_iso(start)} to {to_iso(end)}) is entirely before that.",
            "Use a more recent window, such as last_7d or last_30d.",
        )
    partial = start < stats_start
    data_start = max(start, stats_start)

    records = [r for r in community.hourly_activity if start <= from_iso(r.hour_start) < end]
    snapshots = [s for s in community.snapshots if from_iso(s.at) <= end]

    # An hour has data if the bot recorded activity or took a snapshot in it.
    hours_seen = {from_iso(r.hour_start) for r in records}
    hours_seen |= {from_iso(s.at) for s in snapshots if from_iso(s.at) >= start}
    hours_seen = {h for h in hours_seen if h < end}
    missing = [h for h in _hours(data_start, end) if h not in hours_seen]

    notes = []
    if partial:
        empty = len(_hours(start, data_start))
        notes.append(
            f"Stats only start at {config.stats_started_at}, so the first {empty} hours of "
            "this window have no data."
        )
    for gap_start, gap_end in _hour_ranges(missing):
        hours = len(_hours(gap_start, gap_end))
        notes.append(
            f"No data for {hours} hours from {to_iso(gap_start)} to {to_iso(gap_end)} "
            "(the bot was offline), so activity then was not recorded."
        )
    if not notes:
        notes.append("Every hour in this window has data.")

    def total(field: str) -> int:
        return sum(getattr(r, field) for r in records)

    chatters, active = set(), set()
    channels: Counter[str] = Counter()
    commands: Counter[str] = Counter()
    by_hour_of_day: Counter[int] = Counter()
    for r in records:
        chatters |= r.members.keys()
        active |= r.members.keys() | r.reactors.keys() | r.voice.keys() | r.commanders.keys()
        channels.update(r.channels)
        commands.update(r.command_names)
        by_hour_of_day[from_iso(r.hour_start).hour] += r.messages

    channel_names = {c.channel_id: c.name for c in community.channels}
    top_channels = sorted(channels.items(), key=lambda item: (-item[1], item[0]))[:5]
    top_commands = sorted(commands.items(), key=lambda item: (-item[1], item[0]))[:5]
    busiest = None
    if total("messages") > 0:
        busiest = min(by_hour_of_day, key=lambda hour: (-by_hour_of_day[hour], hour))
    latest = max(snapshots, key=lambda s: s.at, default=None)

    return CommunityStats(
        window=window,
        window_start=to_iso(start),
        window_end=to_iso(end),
        messages=total("messages"),
        replies=total("replies"),
        attachments=total("attachments"),
        thread_messages=total("thread_messages"),
        reactions=total("reactions"),
        voice_minutes=round(sum(r.voice_minutes for r in records), 1),
        commands=total("commands"),
        joins=total("joins"),
        leaves=total("leaves"),
        net_growth=total("joins") - total("leaves"),
        active_members=len(active),
        active_chatters=len(chatters),
        busiest_hour_utc=busiest,
        top_channels=[
            ChannelCount(channel_id=cid, channel_name=channel_names.get(cid, cid), messages=n)
            for cid, n in top_channels
        ],
        top_commands=[CommandCount(command=name, uses=n) for name, n in top_commands],
        latest_snapshot=SnapshotOut(**latest.model_dump()) if latest else None,
        hours_with_data=len(hours_seen),
        hours_in_window=len(_hours(start, end)),
        partial=partial,
        data_starts_at=config.stats_started_at if partial else None,
        coverage_note=" ".join(notes),
    )


# ---------------------------------------------------------------------------
# 7. assign_role
# ---------------------------------------------------------------------------


def _find_role(community: Community, role_name: str) -> Role:
    wanted = role_name.strip().casefold()
    for role in community.roles:
        if role.name.casefold() == wanted:
            return role
    names = {role.name.casefold(): role.name for role in community.roles}
    close = difflib.get_close_matches(wanted, list(names), n=3, cutoff=0.5)
    if close:
        suggestions = ", ".join(f"'{names[n]}'" for n in close)
        hint = f"Did you mean {suggestions}? Call again with the exact role name."
    else:
        hint = "No role has a similar name. Ask the user which role they mean."
    raise ToolFailure("ROLE_NOT_FOUND", f"No role is named '{role_name.strip()}'.", hint)


def _unlock_requirement(community: Community, role: Role, member: Member) -> str:
    unlock = role.unlock
    if unlock.type == "achievement_count":
        return (
            f"It needs at least {unlock.min_achievements} achievements; the member has "
            f"{member.achievements_unlocked}."
        )
    if unlock.type == "rare_achievement":
        names = {a.achievement_id: a.name for a in community.rare_achievements}
        name = names[unlock.achievement_id]
        return f"It needs the rare achievement '{name}', which the member doesn't have."
    if unlock.type == "booster":
        return "It is only for members who are boosting the server, and this member isn't."
    return f"It needs prestige {unlock.min_prestige}; the member has prestige {member.prestige}."


def assign_role(
    community: Community, member_id: str, role_name: str, confirm: bool = False
) -> RoleChange:
    config = community.config
    member = _find_member(community, member_id)
    role = _find_role(community, role_name)
    who = f"{member.display_name} ({member.member_id})"
    actor = _find_member(community, config.acting_member_id)
    actor_top = _member_roles(community, actor)[0]

    # Refusals come before the confirm check, so a preview never suggests the change is allowed.
    if role.position >= actor_top.position:
        raise ToolFailure(
            "ROLE_ABOVE_ACTOR",
            f"'{role.name}' is at or above your highest role ({actor_top.name}), so you can't "
            "assign it.",
            f"Nothing was changed. You can only assign roles below {actor_top.name}. Tell the "
            "user this needs someone with a higher role.",
        )
    if role.auto_managed:
        raise ToolFailure(
            "ROLE_AUTO_MANAGED",
            f"'{role.name}' is managed automatically by the bot and can't be assigned by hand.",
            "Nothing was changed. Tell the user the bot assigns this role on its own.",
        )
    if not member.in_server or member.member_id in _banned_ids(community):
        state = "is banned" if member.member_id in _banned_ids(community) else "left the server"
        raise ToolFailure(
            "MEMBER_NOT_IN_SERVER",
            f"{who} {state}, so they can't be given roles.",
            "Nothing was changed. Roles can only be given to current members.",
        )
    if role.role_id in member.roles:
        raise ToolFailure(
            "ALREADY_HAS_ROLE",
            f"{who} already has the '{role.name}' role.",
            "Nothing was changed. No further action is needed.",
        )
    if role.unlock and not role.unlock.is_met(
        prestige=member.prestige,
        achievements_unlocked=member.achievements_unlocked,
        rare_achievements=member.rare_achievements,
        is_booster=member.is_booster,
    ):
        raise ToolFailure(
            "COLOR_NOT_UNLOCKED",
            f"{who} hasn't unlocked '{role.name}'. " + _unlock_requirement(community, role, member),
            "Nothing was changed. Tell the user what the member still needs, or pick a colour "
            "they have unlocked.",
        )

    # A newly picked colour replaces the member's previous picked colour.
    replaced: list[Role] = []
    if role.color_group in PICKED_COLOR_GROUPS:
        replaced = [
            r for r in _member_roles(community, member) if r.color_group in PICKED_COLOR_GROUPS
        ]
    replaced_names = [r.name for r in replaced]

    if not confirm:
        return RoleChange(
            executed=False,
            member=_ref(member),
            role=role.name,
            replaced_roles=replaced_names,
            message="Preview only. Nothing was changed. Call again with confirm=true to assign "
            "the role.",
        )

    removed = {r.role_id for r in replaced}
    new_roles = [rid for rid in member.roles if rid not in removed] + [role.role_id]
    positions = {r.role_id: r.position for r in community.roles}
    member.roles = sorted(new_roles, key=lambda rid: -positions[rid])
    community.moderation_log.append(
        ModerationLogEntry(
            log_id=f"modlog_{len(community.moderation_log) + 1:04d}",
            at=config.reference_now,
            action="assign_role",
            actor_member_id=config.acting_member_id,
            target_member_id=member.member_id,
            role_id=role.role_id,
            replaced_role_id=replaced[0].role_id if replaced else None,
        )
    )
    message = f"Gave '{role.name}' to {who}."
    if replaced_names:
        message += f" Removed {', '.join(replaced_names)}."
    return RoleChange(
        executed=True,
        member=_ref(member),
        role=role.name,
        replaced_roles=replaced_names,
        message=message,
        logged_to="moderation_log",
    )
