"""Pydantic models for tool outputs and errors, plus the constrained argument types.

Every tool returns one of the output models below, or raises ToolFailure carrying a ToolError.
The MCP layer (app.py) turns both into JSON for the model to read.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Argument types (shared by tools.py and the MCP signatures in app.py)
# ---------------------------------------------------------------------------

LeaderboardMetric = Literal["xp", "messages", "voice_minutes", "reactions"]
LeaderboardWindow = Literal["all_time", "week", "month"]
LeaderboardLimit = Annotated[int, Field(ge=1, le=25)]

AutomodStatus = Literal["open", "reviewed", "dismissed", "any"]
AutomodActionFilter = Literal["block_message", "send_alert", "timeout", "block_interaction", "any"]
SinceHours = Annotated[int, Field(ge=1, le=8760)]
AutomodLimit = Annotated[int, Field(ge=1, le=50)]

Audience = Literal["everyone", "new_members", "prestiged", "boosters", "staff"]
Tone = Literal["hype", "friendly", "formal", "serious"]
MaxChars = Annotated[int, Field(ge=100, le=2000)]

StatsWindow = Literal["last_24h", "last_7d", "last_30d", "previous_7d", "previous_30d"]

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MemberRef(BaseModel):
    member_id: str
    display_name: str


class ToolError(BaseModel):
    """A structured, recoverable error. `hint` tells the agent what to do next."""

    code: str
    message: str
    hint: str
    candidates: list[MemberRef] = []


class ToolFailure(Exception):
    """Raised by a tool function when it refuses or cannot do what was asked."""

    def __init__(
        self, code: str, message: str, hint: str, candidates: list[MemberRef] | None = None
    ):
        super().__init__(message)
        self.error = ToolError(code=code, message=message, hint=hint, candidates=candidates or [])


# ---------------------------------------------------------------------------
# lookup_member
# ---------------------------------------------------------------------------


class MemberProfile(BaseModel):
    member_id: str
    username: str
    display_name: str
    total_xp: int
    level: int
    prestige: int
    xp_to_next_level: int
    rank: int | None  # null when the member is not in the server
    roles: list[str]  # every role held, highest first
    color_roles: list[str]  # the colour roles among them
    joined_at: str | None
    in_server: bool
    is_banned: bool
    staff_note_count: int
    automod_events_90d: int
    achievements_unlocked: int
    is_booster: bool
    note: str | None = None


# ---------------------------------------------------------------------------
# get_leaderboard
# ---------------------------------------------------------------------------


class LeaderboardEntry(BaseModel):
    rank: int
    member_id: str
    display_name: str
    value: int | float
    tied: bool


class Leaderboard(BaseModel):
    entries: list[LeaderboardEntry]
    metric: LeaderboardMetric
    window: LeaderboardWindow
    window_start: str | None  # null for all-time XP, which has no start date
    window_end: str
    tie_rule: str
    note: str | None = None


# ---------------------------------------------------------------------------
# get_automod_log
# ---------------------------------------------------------------------------


class AutomodLogEntry(BaseModel):
    event_id: str
    occurred_at: str
    age_hours: float
    member_id: str
    member_name: str
    rule_name: str
    trigger_type: str
    action: str
    severity: Literal["high", "medium", "low"]
    status: str
    matched_keyword: str | None


class AutomodLog(BaseModel):
    events: list[AutomodLogEntry]
    total_matching: int
    since: str
    note: str


# ---------------------------------------------------------------------------
# draft_announcement
# ---------------------------------------------------------------------------


class AnnouncementDraft(BaseModel):
    draft: str
    char_count: int
    audience: Audience
    tone: Tone
    estimated_reach: int
    truncated: bool
    sent: Literal[False] = False
    note: str


# ---------------------------------------------------------------------------
# ban_member
# ---------------------------------------------------------------------------


class BanPreview(BaseModel):
    executed: Literal[False] = False
    would_ban: MemberRef
    level: int
    prestige: int
    in_server: bool
    staff_note_count: int
    automod_events_90d: int
    joined_at: str | None
    message: str


class BanResult(BaseModel):
    executed: Literal[True] = True
    banned_at: str
    member: MemberRef
    reason: str
    logged_to: Literal["moderation_log"] = "moderation_log"


# ---------------------------------------------------------------------------
# get_community_stats
# ---------------------------------------------------------------------------


class ChannelCount(BaseModel):
    channel_id: str
    channel_name: str
    messages: int


class CommandCount(BaseModel):
    command: str
    uses: int


class SnapshotOut(BaseModel):
    at: str
    members: int
    online: int | None  # null when presence counts were unavailable, which is not 0
    boosts: int | None
    in_voice: int


class CommunityStats(BaseModel):
    window: StatsWindow
    window_start: str
    window_end: str
    messages: int
    replies: int
    attachments: int
    thread_messages: int
    reactions: int
    voice_minutes: float
    commands: int
    joins: int
    leaves: int
    net_growth: int
    active_members: int
    active_chatters: int
    busiest_hour_utc: int | None  # hour of day 0-23 with the most messages
    top_channels: list[ChannelCount]
    top_commands: list[CommandCount]
    latest_snapshot: SnapshotOut | None
    hours_with_data: int
    hours_in_window: int
    partial: bool
    data_starts_at: str | None
    coverage_note: str


# ---------------------------------------------------------------------------
# assign_role
# ---------------------------------------------------------------------------


class RoleChange(BaseModel):
    executed: bool
    member: MemberRef
    role: str
    replaced_roles: list[str]
    message: str
    logged_to: Literal["moderation_log"] | None = None
