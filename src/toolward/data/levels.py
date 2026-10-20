"""XP and level rules, copied from the bot owner's public level table.

The bot gives 45-75 XP per message with a 60-second cooldown. Levels 0-50 come from a
cumulative XP table. Reaching the level-50 threshold (65,550 XP) adds one prestige and resets
the level to 0, so a member's displayed level is always 0-49.
"""

from bisect import bisect_right

XP_PER_MESSAGE_MIN = 45
XP_PER_MESSAGE_MAX = 75
XP_COOLDOWN_SECONDS = 60

# Cumulative XP needed to reach each level. XP_TABLE[n] is the XP for level n (0-50).
XP_TABLE: tuple[int, ...] = (
    0, 24, 62, 116, 188, 280, 396, 538, 708, 908,  # levels 0-9
    1141, 1410, 1717, 2063, 2453, 2888, 3370, 3903, 4488, 5127,  # 10-19
    5825, 6582, 7401, 8286, 9237, 10258, 11351, 12518, 13763, 15087,  # 20-29
    16492, 17982, 19559, 21225, 22982, 24833, 26781, 28828, 30976, 33228,  # 30-39
    35586, 38053, 40631, 43323, 46131, 49057, 52104, 55274, 58570, 61994,  # 40-49
    65550,  # 50: the prestige threshold
)  # fmt: skip

PRESTIGE_XP = XP_TABLE[50]
MAX_LEVEL = 49


def level_for(total_xp: int) -> tuple[int, int, int]:
    """Return (prestige, level, effective_xp) for an all-time XP total.

    effective_xp is the XP left after removing whole prestiges:
    total_xp - prestige * 65550. The level is read from the table using effective_xp.
    """
    if total_xp < 0:
        raise ValueError("total_xp cannot be negative")
    prestige = total_xp // PRESTIGE_XP
    effective_xp = total_xp - prestige * PRESTIGE_XP
    # bisect_right finds how many thresholds are <= effective_xp; minus one gives the level.
    level = bisect_right(XP_TABLE, effective_xp) - 1
    return prestige, level, effective_xp


def xp_to_next_level(total_xp: int) -> int:
    """XP still needed for the next level. At level 49 the next step is the next prestige."""
    _, level, effective_xp = level_for(total_xp)
    return XP_TABLE[level + 1] - effective_xp
