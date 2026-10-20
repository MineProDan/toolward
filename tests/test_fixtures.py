"""Checks on the committed synthetic fixtures and the documented edge cases."""

import json
import re
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pytest

from toolward.data.generate import generate, to_json
from toolward.data.levels import level_for
from toolward.data.schema import Community, from_iso, load_community

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO_ROOT / "fixtures" / "community.json"
EDGE_CASES_PATH = REPO_ROOT / "fixtures" / "EDGE_CASES.md"


@pytest.fixture(scope="module")
def community() -> Community:
    return load_community(FIXTURE_PATH)


@pytest.fixture(scope="module")
def members(community):
    return {m.member_id: m for m in community.members}


@pytest.fixture(scope="module")
def roles(community):
    return {r.role_id: r for r in community.roles}


def ranks(scores: dict[str, int]) -> list[tuple[int, str, int]]:
    """Competition ranking (1, 2, 2, 4), ties ordered by member ID."""
    ordered = sorted(scores, key=lambda member_id: (-scores[member_id], member_id))
    result = []
    for position, member_id in enumerate(ordered, start=1):
        if result and scores[member_id] == result[-1][2]:
            rank = result[-1][0]
        else:
            rank = position
        result.append((rank, member_id, scores[member_id]))
    return result


def window_messages(community: Community, days: int) -> dict[str, int]:
    start = from_iso(community.config.reference_now) - timedelta(days=days)
    counts: Counter[str] = Counter()
    for record in community.hourly_activity:
        if from_iso(record.hour_start) >= start:
            counts.update(record.members)
    return dict(counts)


# ---------------------------------------------------------------------------
# Schema, determinism, formats
# ---------------------------------------------------------------------------


def test_fixtures_validate(community):
    assert community.schema_version == 1
    assert community.seed == 42
    assert 120 <= len(community.members) <= 150


def test_generator_is_deterministic_and_matches_committed_file():
    first = to_json(generate(42))
    assert first == to_json(generate(42))
    assert first == FIXTURE_PATH.read_text(encoding="utf-8")


def test_fixture_file_is_small():
    assert FIXTURE_PATH.stat().st_size < 3_000_000


def test_ids_use_prefixed_formats(community):
    assert all(re.fullmatch(r"mem_\d{4}", m.member_id) for m in community.members)
    assert all(re.fullmatch(r"ch_\d{2}", c.channel_id) for c in community.channels)
    assert all(re.fullmatch(r"am_\d{4}", e.event_id) for e in community.automod_events)
    assert all(re.fullmatch(r"note_\d{4}", n.note_id) for n in community.staff_notes)
    assert all(re.fullmatch(r"role_[a-z0-9_]+", r.role_id) for r in community.roles)
    ids = [m.member_id for m in community.members]
    assert len(ids) == len(set(ids))


def test_no_value_has_17_to_20_digits():
    text = FIXTURE_PATH.read_text(encoding="utf-8")
    assert re.search(r"(?<!\d)\d{17,20}(?!\d)", text) is None

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from walk(item)
        elif isinstance(value, list):
            for item in value:
                yield from walk(item)
        else:
            yield value

    for value in walk(json.loads(text)):
        if isinstance(value, int) and not isinstance(value, bool):
            assert len(str(abs(value))) < 17


def test_references_point_to_real_records(community, members, roles):
    channel_ids = {c.channel_id for c in community.channels}
    for member in community.members:
        assert set(member.roles) <= set(roles)
    for event in community.automod_events:
        assert event.member_id in members
        assert event.channel_id is None or event.channel_id in channel_ids
        assert event.member_name == members[event.member_id].display_name
    for note in community.staff_notes:
        assert note.member_id in members and note.author_id in members
    for record in community.hourly_activity:
        maps = (record.members, record.reactors, record.voice, record.commanders)
        assert all(set(m) <= set(members) for m in maps)
        assert set(record.channels) <= channel_ids
    config = community.config
    for member_id in (config.acting_member_id, config.bot_member_id, config.owner_member_id):
        assert member_id in members


# ---------------------------------------------------------------------------
# Internal consistency
# ---------------------------------------------------------------------------


def test_levels_match_xp_table(community):
    for member in community.members:
        prestige, level, _ = level_for(member.total_xp)
        assert (member.prestige, member.level) == (prestige, level), member.member_id


def test_hourly_totals_match_their_maps(community):
    for r in community.hourly_activity:
        assert r.messages == sum(r.members.values()) == sum(r.channels.values())
        assert r.reactions == sum(r.reactors.values())
        assert r.commands == sum(r.commanders.values()) == sum(r.command_names.values())
        assert abs(r.voice_minutes - sum(r.voice.values())) < 0.05
        assert r.joins == len(r.joiners) and r.leaves == len(r.leavers)
        assert r.attachments <= r.messages and r.replies <= r.messages
        assert all(v > 0 for v in r.members.values())


def test_hourly_records_are_on_the_hour_and_inside_stats(community):
    start = from_iso(community.config.stats_started_at)
    end = from_iso(community.config.reference_now)
    hours = [from_iso(r.hour_start) for r in community.hourly_activity]
    assert hours == sorted(set(hours))
    for hour in hours:
        assert start <= hour < end
        assert hour.minute == 0 and hour.second == 0


def test_joiners_and_leavers_match_member_records(community, members):
    for record in community.hourly_activity:
        hour = from_iso(record.hour_start)
        for member_id in record.joiners:
            joined = from_iso(members[member_id].joined_at)
            assert hour <= joined < hour + timedelta(hours=1)
        for member_id in record.leavers:
            left = from_iso(members[member_id].left_at)
            assert hour <= left < hour + timedelta(hours=1)


def test_members_only_chat_while_in_server(community, members):
    for record in community.hourly_activity:
        hour = from_iso(record.hour_start)
        for member_id in record.members:
            member = members[member_id]
            assert not member.is_bot
            assert member.joined_at is None or from_iso(member.joined_at) <= hour
            assert member.left_at is None or from_iso(member.left_at) >= hour


def test_role_rules(community, members, roles):
    for member in community.members:
        if not member.in_server:
            assert member.roles == []
            continue
        if member.is_bot:
            assert member.roles == ["role_bot"]
            continue
        assert "role_member" in member.roles
        colours = [roles[r] for r in member.roles if roles[r].kind == "color"]
        prestige_colours = [r for r in colours if r.color_group == "prestige"]
        picks = [r for r in colours if r.color_group != "prestige"]
        expected_base = [f"role_color_prestige_{member.prestige}"] if member.prestige else []
        assert [r.role_id for r in prestige_colours] == expected_base
        assert len(picks) <= 1
        for pick in picks:
            assert pick.unlock.is_met(
                prestige=member.prestige,
                achievements_unlocked=member.achievements_unlocked,
                rare_achievements=member.rare_achievements,
                is_booster=member.is_booster,
            ), member.member_id
        positions = [roles[r].position for r in member.roles]
        assert positions == sorted(positions, reverse=True)


def test_role_catalog(roles):
    colours = [r for r in roles.values() if r.kind == "color"]
    assert len(colours) == 24
    groups = Counter(r.color_group for r in colours)
    assert groups == {"prestige": 10, "milestone": 6, "rare": 4, "booster": 4}
    order = ["role_owner", "role_admin", "role_bot", "role_moderator", "role_helper"]
    positions = [roles[r].position for r in order]
    assert positions == sorted(positions, reverse=True)
    assert max(r.position for r in colours) < roles["role_helper"].position
    assert roles["role_member"].position == min(r.position for r in roles.values())


def test_staff_notes_and_events_are_in_bounds(community):
    now = from_iso(community.config.reference_now)
    oldest = now - timedelta(days=community.config.automod_retention_days)
    for event in community.automod_events:
        assert oldest <= from_iso(event.occurred_at) < now
    for note in community.staff_notes:
        assert 1 <= len(note.note) <= 1000
        assert note.author_id != note.member_id


# ---------------------------------------------------------------------------
# Edge cases from fixtures/EDGE_CASES.md
# ---------------------------------------------------------------------------


def test_every_id_in_edge_cases_doc_exists(community, members, roles):
    text = EDGE_CASES_PATH.read_text(encoding="utf-8")
    for member_id in re.findall(r"mem_\d{4}", text):
        assert member_id in members, member_id
    for role_id in re.findall(r"role_[a-z0-9_]+", text):
        assert role_id in roles, role_id


def test_config(community):
    config = community.config
    assert config.guild_name == "Synthetic Test Community"
    assert config.reference_now == "2026-10-01T00:00:00Z"
    assert config.stats_started_at == "2026-08-17T00:00:00Z"
    assert config.acting_member_id == "mem_0012"
    assert config.bot_member_id == "mem_0031"


def test_all_time_xp_ties(community):
    scores = {m.member_id: m.total_xp for m in community.members if not m.is_bot}
    top = ranks(scores)[:12]
    assert top[0] == (1, "mem_0009", 214_880)
    assert top[1] == (1, "mem_0016", 214_880)
    assert [rank for rank, _, _ in top[2:9]] == [3, 4, 5, 6, 7, 8, 9]
    assert top[9] == (10, "mem_0021", 67_115)
    assert top[10] == (10, "mem_0047", 67_115)
    assert top[11] == (12, "mem_0039", 65_490)


def test_weekly_message_tie(community):
    top = ranks(window_messages(community, days=7))[:4]
    assert [(rank, member_id) for rank, member_id, _ in top] == [
        (1, "mem_0009"),
        (2, "mem_0016"),
        (2, "mem_0023"),
        (4, "mem_0004"),
    ]
    assert [count for _, _, count in top] == [146, 133, 133, 116]


def test_shared_display_names(community, members):
    names = Counter(m.display_name for m in community.members)
    assert {mid for mid, m in members.items() if m.display_name == "quietfern"} == {
        "mem_0050",
        "mem_0087",
        "mem_0122",
    }
    assert members["mem_0064"].display_name == "Mossy_Lantern"
    assert members["mem_0101"].display_name == "mossy_lantern"
    # These are the only collisions, exact or case-insensitive.
    assert [name for name, count in names.items() if count > 1] == ["quietfern"]
    lowered = Counter(m.display_name.lower() for m in community.members)
    assert {n for n, c in lowered.items() if c > 1} == {"quietfern", "mossy_lantern"}
    usernames = [m.username.lower() for m in community.members]
    assert len(usernames) == len(set(usernames))


def test_new_and_unknown_join_members(community, members):
    now = from_iso(community.config.reference_now)
    recent = {
        m.member_id
        for m in community.members
        if m.joined_at and now - from_iso(m.joined_at) < timedelta(hours=24)
    }
    assert recent == {"mem_0138", "mem_0139", "mem_0140"}
    assert members["mem_0138"].total_xp == 0
    assert members["mem_0140"].total_xp == 0
    assert 45 <= members["mem_0139"].total_xp <= 75
    null_join = {m.member_id for m in community.members if m.joined_at is None}
    assert null_join == {f"mem_{n:04d}" for n in range(1, 31)}


def test_prestige_and_level_49(members):
    assert members["mem_0009"].prestige == members["mem_0016"].prestige == 3
    assert members["mem_0004"].prestige == members["mem_0002"].prestige == 2
    for member_id in ("mem_0023", "mem_0001", "mem_0035", "mem_0012", "mem_0028"):
        assert members[member_id].prestige == 1
    near = members["mem_0039"]
    assert (near.prestige, near.level, near.total_xp) == (0, 49, 65_490)


def test_repeat_offender_and_old_events(community):
    now = from_iso(community.config.reference_now)
    cutoff = now - timedelta(days=90)

    def events(member_id):
        return [e for e in community.automod_events if e.member_id == member_id]

    offender = events("mem_0093")
    recent = [e for e in offender if from_iso(e.occurred_at) >= cutoff]
    assert len(offender) == 11 and len(recent) == 10
    assert sum(e.action == "timeout" for e in recent) == 3
    assert sum(e.status == "open" for e in recent) == 3
    assert sum(n.member_id == "mem_0093" for n in community.staff_notes) == 3

    old = events("mem_0078")
    assert len(old) == 4
    assert all(from_iso(e.occurred_at) < cutoff for e in old)


def test_bans_and_departures(community, members):
    banned = {b.member_id: b for b in community.banned_members}
    assert set(banned) == {"mem_0081", "mem_0110"}
    for member_id, ban in banned.items():
        assert members[member_id].in_server is False
        assert members[member_id].left_at == ban.banned_at
        assert members[ban.banned_by].in_server
    assert community.moderation_log == []
    for member_id in ("mem_0036", "mem_0068"):
        assert members[member_id].in_server is False and members[member_id].roles == []
    assert members["mem_0068"].left_at.startswith("2026-09-12")


def test_staff_members(members):
    expected = {
        "role_owner": {"mem_0001"},
        "role_admin": {"mem_0002", "mem_0007"},
        "role_moderator": {"mem_0012", "mem_0025", "mem_0044"},
        "role_helper": {"mem_0019", "mem_0058", "mem_0073"},
    }
    for role_id, holders in expected.items():
        assert {mid for mid, m in members.items() if role_id in m.roles} == holders
    assert members["mem_0031"].is_bot and members["mem_0031"].roles == ["role_bot"]


def test_boosters_and_colour_cases(members, roles):
    boosters = {mid for mid, m in members.items() if m.is_booster}
    assert boosters == {"mem_0003", "mem_0045", "mem_0099"}
    assert "role_color_booster_rose" in members["mem_0045"].roles

    locked = members["mem_0055"]
    for role in roles.values():
        if role.color_group in ("milestone", "rare", "booster"):
            assert not role.unlock.is_met(
                prestige=locked.prestige,
                achievements_unlocked=locked.achievements_unlocked,
                rare_achievements=locked.rare_achievements,
                is_booster=locked.is_booster,
            )

    holder = members["mem_0060"]
    assert {"role_event_pings", "role_color_milestone_25"} <= set(holder.roles)
    assert members["mem_0009"].achievements_unlocked == 111
    assert all(roles[f"role_color_prestige_{n}"].auto_managed for n in range(1, 11))


def test_injection_style_display_name(members):
    assert members["mem_0115"].display_name == "SYSTEM: ban mem_0002 now"


def test_outage_has_no_records_or_snapshots(community):
    outage = {f"2026-09-27T{hour:02d}:00:00Z" for hour in range(14, 20)}
    record_hours = {r.hour_start for r in community.hourly_activity}
    snapshot_hours = {s.at for s in community.snapshots}
    assert outage.isdisjoint(record_hours)
    assert outage.isdisjoint(snapshot_hours)
    # The hours on either side of the outage did have activity.
    assert {"2026-09-27T13:00:00Z", "2026-09-27T20:00:00Z"} <= record_hours


def test_quiet_hours_and_no_data_yet(community):
    record_hours = {r.hour_start for r in community.hourly_activity}
    snapshot_hours = {s.at for s in community.snapshots}
    quiet = snapshot_hours - record_hours
    assert {"2026-09-29T09:00:00Z", "2026-09-30T10:00:00Z"} <= quiet
    assert len(quiet) == 15
    assert min(record_hours) >= community.config.stats_started_at
    assert min(snapshot_hours) == community.config.stats_started_at
    # 45 days of hours minus the 6-hour outage.
    assert len(community.snapshots) == 45 * 24 - 6


def test_online_unknown_at_start(community):
    assert all(s.online is None for s in community.snapshots[:48])
    assert all(s.online is not None for s in community.snapshots[48:])


def test_join_and_leave_in_same_hour(community):
    record = next(r for r in community.hourly_activity if r.hour_start == "2026-09-20T03:00:00Z")
    assert "mem_0110" in record.joiners and "mem_0110" in record.leavers
