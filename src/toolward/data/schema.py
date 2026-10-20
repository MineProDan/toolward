"""Pydantic models for the synthetic community fixtures.

Every record mirrors the shape of what the Octavious bot stores, plus a few fields that are
labelled toolward extensions (review status on AutoMod events, bans and the moderation log).
All values are invented. IDs use short prefixed formats (mem_0001, ch_01, am_0001, ...) so they
can never be mistaken for real Discord IDs.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

# ---------------------------------------------------------------------------
# Shared field types
# ---------------------------------------------------------------------------

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# Timestamps are always UTC ISO 8601 strings like "2026-10-01T00:00:00Z".
Timestamp = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")]
MemberId = Annotated[str, StringConstraints(pattern=r"^mem_\d{4}$")]
ChannelId = Annotated[str, StringConstraints(pattern=r"^ch_\d{2}$")]
RoleId = Annotated[str, StringConstraints(pattern=r"^role_[a-z0-9_]+$")]
AchievementId = Annotated[str, StringConstraints(pattern=r"^ach_[a-z0-9_]+$")]
AutoModEventId = Annotated[str, StringConstraints(pattern=r"^am_\d{4}$")]
NoteId = Annotated[str, StringConstraints(pattern=r"^note_\d{4}$")]
ModLogId = Annotated[str, StringConstraints(pattern=r"^modlog_\d{4}$")]

NonNegInt = Annotated[int, Field(ge=0)]
NonNegFloat = Annotated[float, Field(ge=0)]


def to_iso(moment: datetime) -> str:
    """Format a timezone-aware datetime as a UTC Timestamp string."""
    return moment.astimezone(UTC).strftime(TIMESTAMP_FORMAT)


def from_iso(text: str) -> datetime:
    """Parse a Timestamp string into a timezone-aware UTC datetime."""
    return datetime.strptime(text, TIMESTAMP_FORMAT).replace(tzinfo=UTC)


class StrictModel(BaseModel):
    """Base model that rejects unknown fields, so typos in fixtures fail loudly."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Server configuration, roles, channels, achievements
# ---------------------------------------------------------------------------


class Config(StrictModel):
    """Server-level settings. The acting staff identity lives here, not in tool arguments."""

    guild_name: str
    reference_now: Timestamp  # the fixed "now" that every relative window is measured from
    bot_added_at: Timestamp  # members with joined_at = null joined before this
    stats_started_at: Timestamp  # hourly stats exist only from here on ("no data yet" before)
    acting_member_id: MemberId  # the staff member the agent acts as
    bot_member_id: MemberId
    owner_member_id: MemberId
    automod_retention_days: int
    hourly_stats_retention_days: int
    achievement_total: int


class UnlockRule(StrictModel):
    """When a colour role becomes available to a member.

    type:
      prestige           - member's prestige >= min_prestige
      achievement_count  - member has unlocked >= min_achievements achievements
      rare_achievement   - member has unlocked the rare achievement achievement_id
      booster            - member is currently boosting the server
    """

    type: Literal["prestige", "achievement_count", "rare_achievement", "booster"]
    min_prestige: int | None = None
    min_achievements: int | None = None
    achievement_id: AchievementId | None = None

    def is_met(
        self,
        *,
        prestige: int,
        achievements_unlocked: int,
        rare_achievements: list[str],
        is_booster: bool,
    ) -> bool:
        """Return True if a member with these stats has unlocked the colour."""
        if self.type == "prestige":
            return prestige >= (self.min_prestige or 0)
        if self.type == "achievement_count":
            return achievements_unlocked >= (self.min_achievements or 0)
        if self.type == "rare_achievement":
            return self.achievement_id in rare_achievements
        return is_booster


class Role(StrictModel):
    """A server role. A higher position means more power (Owner is highest)."""

    role_id: RoleId
    name: str
    kind: Literal["staff", "color", "cosmetic", "base", "bot"]
    position: int
    color_hex: str | None = None
    # Colour roles only: prestige colours are the automatic base colour; milestone, rare and
    # booster colours are the one optional "picked" colour a member may hold.
    color_group: Literal["prestige", "milestone", "rare", "booster"] | None = None
    unlock: UnlockRule | None = None
    # True when the bot manages the role itself (prestige colours, Member, the bot role).
    auto_managed: bool = False


class Channel(StrictModel):
    channel_id: ChannelId
    name: str
    kind: Literal["text", "voice", "announcement"]


class RareAchievement(StrictModel):
    """One of the 4 rare achievements that unlock a rare colour."""

    achievement_id: AchievementId
    name: str


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


class Member(StrictModel):
    """A community member as the bot sees them.

    joined_at is null for members who joined before the bot was added (a real quirk).
    prestige and level are stored like the bot stores them, and must match total_xp.
    Members who left keep their XP record but hold no roles.
    """

    member_id: MemberId
    username: str  # unique handle
    display_name: str  # not unique: several members can share one
    is_bot: bool = False
    joined_at: Timestamp | None
    left_at: Timestamp | None = None
    in_server: bool
    roles: list[RoleId]
    total_xp: NonNegInt
    prestige: NonNegInt
    level: Annotated[int, Field(ge=0, le=49)]
    achievements_unlocked: Annotated[int, Field(ge=0, le=111)]
    rare_achievements: list[AchievementId]
    is_booster: bool
    boosting_since: Timestamp | None = None

    @model_validator(mode="after")
    def _booster_fields_agree(self) -> "Member":
        if self.is_booster != (self.boosting_since is not None):
            raise ValueError("is_booster must be true exactly when boosting_since is set")
        return self


# ---------------------------------------------------------------------------
# Hourly activity stats
# ---------------------------------------------------------------------------


class HourlyActivity(StrictModel):
    """Activity for one UTC hour. Hours with no activity at all have no record.

    The per-member maps are sparse: only members with a non-zero count appear.
    Totals equal the sums of their maps (messages = sum(members) = sum(channels), etc.).
    """

    hour_start: Timestamp
    messages: NonNegInt
    attachments: NonNegInt
    replies: NonNegInt
    thread_messages: NonNegInt
    reactions: NonNegInt
    voice_minutes: NonNegFloat  # 0.1 precision
    commands: NonNegInt
    joins: NonNegInt
    leaves: NonNegInt
    members: dict[MemberId, int]  # messages per member
    reactors: dict[MemberId, int]
    voice: dict[MemberId, float]  # voice minutes per member
    commanders: dict[MemberId, int]
    joiners: dict[MemberId, int]  # value is always 1
    leavers: dict[MemberId, int]  # value is always 1
    channels: dict[ChannelId, int]  # messages per channel
    command_names: dict[str, int]


class Snapshot(StrictModel):
    """Server counts taken at the top of each hour the bot was running.

    An hour with a snapshot but no HourlyActivity record was simply quiet. An hour with neither
    means the bot was down.
    """

    at: Timestamp
    members: NonNegInt
    online: NonNegInt | None  # null when presence counts were unavailable
    boosts: NonNegInt | None
    in_voice: NonNegInt


# ---------------------------------------------------------------------------
# Moderation data
# ---------------------------------------------------------------------------

TriggerType = Literal["keyword", "spam", "preset", "mention_spam", "profile"]
AutoModAction = Literal["block_message", "send_alert", "timeout", "block_interaction"]


class AutoModEvent(StrictModel):
    """One AutoMod action. Severity is not stored; tools derive it from `action`.

    `status` is a toolward extension (the bot has no review workflow).
    """

    event_id: AutoModEventId
    occurred_at: Timestamp
    member_id: MemberId
    member_name: str  # display name at the time of the event
    rule_name: str
    trigger_type: TriggerType
    action: AutoModAction
    matched_keyword: str | None = None
    timeout_seconds: int | None = None  # only set when action == "timeout"
    channel_id: ChannelId | None = None  # null for profile-name triggers
    status: Literal["open", "reviewed", "dismissed"]

    @model_validator(mode="after")
    def _timeout_only_for_timeouts(self) -> "AutoModEvent":
        if (self.action == "timeout") != (self.timeout_seconds is not None):
            raise ValueError("timeout_seconds must be set exactly when action is 'timeout'")
        return self


class StaffNote(StrictModel):
    note_id: NoteId
    member_id: MemberId
    note: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    author_id: MemberId
    created_at: Timestamp


class BannedMember(StrictModel):
    """A ban already in place (toolward extension)."""

    member_id: MemberId
    banned_at: Timestamp
    banned_by: MemberId
    reason: str


class ModerationLogEntry(StrictModel):
    """Written by state-changing tools at run time. Starts empty in the fixtures."""

    log_id: ModLogId
    at: Timestamp
    action: Literal["ban", "assign_role"]
    actor_member_id: MemberId
    target_member_id: MemberId
    role_id: RoleId | None = None
    replaced_role_id: RoleId | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# The whole community
# ---------------------------------------------------------------------------


class Community(StrictModel):
    """Everything in fixtures/community.json."""

    schema_version: int
    seed: int
    config: Config
    roles: list[Role]
    channels: list[Channel]
    rare_achievements: list[RareAchievement]
    members: list[Member]
    hourly_activity: list[HourlyActivity]
    snapshots: list[Snapshot]
    automod_events: list[AutoModEvent]
    staff_notes: list[StaffNote]
    banned_members: list[BannedMember]
    moderation_log: list[ModerationLogEntry]


def load_community(path: Path) -> Community:
    """Read and validate a fixtures file."""
    return Community.model_validate_json(path.read_text(encoding="utf-8"))
