from fractions import Fraction as F

import pytest

from intervalclock import (
    Instant,
    NonexistentTime,
    cell,
    cell_span,
    civil,
    name,
    phase,
    resolution_versions,
)


def test_hour_cell_resolution_golden():
    sp = cell_span(cell("hour", 2026, 8, 1, 14))
    assert name(sp) == "ic1:s:1785592837;1785596437"  # UTC−TAI = −37 s
    assert sp.duration == 3600


def test_iso_week_golden():
    sp = cell_span(cell("isoweek", 2026, 31))
    assert name(sp) == "ic1:s:1785110437;1785715237"
    assert sp.duration == 7 * 86400


def test_leap_second_day_is_86401_seconds():
    assert cell_span(cell("day", 2016, 12, 31)).duration == 86401
    assert cell_span(cell("day", 2016, 12, 30)).duration == 86400


def test_leap_second_cell():
    leap = cell("second", 2016, 12, 31, 23, 59, 60)
    sp = cell_span(leap)
    assert sp.duration == 1
    assert sp.end == cell_span(cell("day", 2016, 12, 31)).end


def test_civil_reads_60_during_leap():
    sp = cell_span(cell("second", 2016, 12, 31, 23, 59, 60))
    c = civil(Instant(sp.start + F(1, 2)))
    assert c.fields[-1] == 60


def test_physical_class_untouched_by_leap():
    # Top-of-minute Φ(1, 60, 0) pulses every 60 TAI s, forever, no lens.
    # The proof of the two-layer split: the civil day boundary drifts 1 s
    # against the physical minute grid across the leap second.
    tom = phase(1, 60)
    d_leap = cell_span(cell("day", 2016, 12, 31))
    assert (d_leap.end - d_leap.start) % 60 == 1  # 86401 ≡ 1 (mod 60)
    # and the physical class itself is untouched: exact pulse count follows
    # from pure arithmetic, no leap table involved
    from intervalclock import occurrences, span

    starts = sum(1 for _ in occurrences(tom, span(d_leap.start, d_leap.end)))
    first = -(-d_leap.start // 60) * 60  # ceil to grid
    expected = (d_leap.end - 1 - first) // 60 + 1
    assert starts == expected == 1440


def test_dst_gap_raises():
    with pytest.raises(NonexistentTime):
        cell_span(cell("minute", 2026, 3, 8, 2, 30, zone="America/New_York"))
    with pytest.raises(NonexistentTime):
        cell_span(cell("hour", 2026, 3, 8, 2, zone="America/New_York"))


def test_dst_day_lengths():
    assert cell_span(cell("day", 2026, 3, 8, zone="America/New_York")).duration == 23 * 3600
    assert cell_span(cell("day", 2026, 11, 1, zone="America/New_York")).duration == 25 * 3600


def test_dst_fold():
    amb = cell("minute", 2026, 11, 1, 1, 30, zone="America/New_York")
    first = cell_span(amb, fold=0)
    second = cell_span(amb, fold=1)
    assert second.start - first.start == 3600


def test_cell_validation():
    with pytest.raises(ValueError):
        cell("day", 2026, 2, 30)
    with pytest.raises(ValueError):
        cell("isoweek", 2026, 54)
    cell("isoweek", 2026, 53)  # 2026 has 53 ISO weeks
    with pytest.raises(ValueError):
        cell("second", 2026, 1, 1, 0, 0, 61)


def test_resolution_versions_stamped():
    v = resolution_versions()
    assert "leap_table" in v and "tzdata" in v
