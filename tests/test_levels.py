import pytest

from toolward.data.levels import MAX_LEVEL, PRESTIGE_XP, XP_TABLE, level_for, xp_to_next_level


def test_table_shape():
    assert len(XP_TABLE) == 51
    assert XP_TABLE[0] == 0
    assert PRESTIGE_XP == 65_550
    assert list(XP_TABLE) == sorted(set(XP_TABLE))  # strictly increasing


@pytest.mark.parametrize(
    ("total_xp", "expected"),
    [
        (0, (0, 0, 0)),
        (23, (0, 0, 23)),
        (24, (0, 1, 24)),
        (1140, (0, 9, 1140)),
        (1141, (0, 10, 1141)),
        (65_549, (0, 49, 65_549)),
        (65_550, (1, 0, 0)),
        (65_550 + 24, (1, 1, 24)),
        (3 * 65_550 + 1141, (3, 10, 1141)),
    ],
)
def test_level_boundaries(total_xp, expected):
    assert level_for(total_xp) == expected


def test_level_never_reaches_50():
    for total_xp in range(65_000, 3 * 65_550, 7):
        _, level, _ = level_for(total_xp)
        assert 0 <= level <= MAX_LEVEL


def test_xp_to_next_level():
    assert xp_to_next_level(0) == 24
    assert xp_to_next_level(24) == 62 - 24
    assert xp_to_next_level(65_549) == 1  # the next step from level 49 is prestige
    assert xp_to_next_level(65_550) == 24


def test_negative_xp_is_rejected():
    with pytest.raises(ValueError):
        level_for(-1)
