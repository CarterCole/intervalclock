"""Durations: the canonical step in time (PROTOCOL.md §2.5)."""

from fractions import Fraction as F

import pytest

import intervalclock as ic
from intervalclock import (
    ALWAYS,
    CalDuration,
    CalSpan,
    Duration,
    NonexistentTime,
    caldur,
    cell,
    cell_span,
    duration,
    from_iso,
    name,
    parse,
)
from intervalclock.encode import ReservedTypeError, decode, encode, from_url, to_url


def day_start(y, mo, d, zone="UTC"):
    return cell_span(cell("day", y, mo, d, zone=zone)).start


# --- canonical forms -------------------------------------------------------


@pytest.mark.parametrize("obj", [
    duration(5),
    duration(F(1, 3)),
    duration(F(-5, 2)),
    duration(0),
    caldur(months=1),
    caldur(months=13, days=-2, seconds=F(1, 3)),
    caldur(days=90),
    caldur(months=1).at(1662854437),
    caldur(months=1, seconds=30).at(F(-7, 3), "America/Chicago"),
])
def test_round_trips(obj):
    n = name(obj)
    assert name(parse(n)) == n
    assert name(decode(encode(obj))) == n
    assert name(from_url(to_url(obj))) == n
    assert parse(n) == obj


def test_canonical_text():
    assert name(duration(F(5, 2))) == "ic1:d:5/2"
    assert name(duration(-3)) == "ic1:d:-3"
    assert name(caldur(months=1)) == "ic1:n:mo=1"
    assert name(caldur(years=1, days=1, minutes=90)) == "ic1:n:mo=12;d=1;s=5400"
    assert name(caldur(months=1).at(1662854437, "America/Chicago")) == (
        "ic1:n:mo=1@1662854437!America/Chicago"
    )


def test_ids_sort_by_step_length():
    assert encode(duration(1)) < encode(duration(60)) < encode(duration(86400))
    assert encode(duration(-1)) < encode(duration(0))


# --- reduction: one name per thing ----------------------------------------


def test_seconds_only_is_physical():
    # A civil second *is* an SI second; every larger unit can vary, so only
    # the seconds tail reduces to the physical type.
    assert caldur(seconds=5) == duration(5)
    assert isinstance(caldur(hours=1), Duration)
    assert caldur(hours=1) == 3600
    assert isinstance(parse("ic1:n:s=5"), Duration)
    assert caldur() == duration(0)


def test_exact_civil_identities_fold():
    assert caldur(years=1) == caldur(months=12)
    assert caldur(weeks=2) == caldur(days=14)
    assert caldur(months=1, minutes=1) == CalDuration(1, 0, duration(60))


def test_non_canonical_nominal_bytes_rejected():
    b = encode(caldur(months=1, days=2))
    broken = b[:9] + bytes([0, 0]) + b[11:]  # months=days=0 → not nominal
    with pytest.raises(ValueError, match="non-canonical"):
        decode(broken)


def test_anchored_exact_step_is_a_span():
    assert duration(3600).at(100) == ic.span(100, 3700)
    assert ic.cal_span(100, duration(3600)) == ic.span(100, 3700)
    with pytest.raises(ValueError, match="span"):
        parse("ic1:n:s=60@100")


def test_reserved_slots_shrank():
    with pytest.raises(ReservedTypeError):
        decode(bytes([0x1D]))


# --- the algebra -----------------------------------------------------------


def test_durations_are_the_numbers_they_are():
    d = duration(F(5, 2))
    assert d == F(5, 2) and float(d) == 2.5
    assert isinstance(d + 1, Duration) and d + 1 == F(7, 2)
    assert isinstance(d * 4, Duration) and d * 4 == 10
    assert isinstance(-d, Duration) and abs(-d) == d
    # dimensionally honest: a ratio of steps is a plain number
    assert type(d / duration(2)) is F and d / duration(2) == F(5, 4)
    assert isinstance(d / 2, Duration)


def test_timeline_algebra():
    a, b = ic.Instant(10), ic.Instant(F(55, 2))
    assert b - a == duration(F(35, 2))
    assert isinstance(b - a, Duration)
    assert ic.between(a, b) == -ic.between(b, a)
    assert a + duration(5) == ic.Instant(15)
    assert duration(5) + a == ic.Instant(15)
    sp = ic.span(0, F(1, 3))
    assert isinstance(sp.duration, Duration) and sp.duration == F(1, 3)
    assert duration(F(1, 3)).at(10) == ic.span(10, F(31, 3))
    assert duration(-2).at(10) == ic.span(8, 10)


def test_rate():
    assert duration(F(1, 3)).hz == 3
    with pytest.raises(ValueError):
        duration(0).hz


# --- the grid: a step is a coordinate system -------------------------------


def test_grid_slots_and_snapping():
    g = duration(300).grid()
    assert g.index(1000) == 3
    assert g.slot(3) == ic.span(900, 1200)
    assert g.slot_at(1000) == ic.span(900, 1200)
    assert g.floor(1000) == 900 and g.ceil(1000) == 1200
    assert g.floor(900) == 900 and g.ceil(900) == 900
    assert g.snap(1000) == 900 and g.snap(1100) == 1200
    assert [s.start for s in g.slots(ic.span(1000, 1600))] == [900, 1200, 1500]


def test_grid_is_anchored_by_phase():
    g = duration(60).grid(phi=7)
    assert g.floor(100) == 67
    assert duration(60).grid(phi=67).phi == 7  # phi lives in [0, step)


def test_grid_classes_partition_time():
    g = duration(F(1, 3)).grid()
    cls = g.classes(3)
    assert len(cls) == 3
    assert name(cls[2]) == "ic1:c:w=1/3;m=3;phi=2/3"
    merged = cls[0]
    for c in cls[1:]:
        merged = ic.union(merged, c)
    assert merged is ALWAYS or merged == ALWAYS


# --- the civil lens: nominal steps are not lengths -------------------------


def test_a_day_is_not_86400_seconds():
    leap = caldur(days=1).seconds_at(day_start(2016, 12, 31))
    assert leap == 86401  # 2016-12-31 carried an inserted leap second
    assert caldur(days=1).seconds_at(day_start(2016, 12, 30)) == 86400
    chi = "America/Chicago"
    spring = caldur(days=1).seconds_at(day_start(2026, 3, 8, chi), chi)
    fall = caldur(days=1).seconds_at(day_start(2026, 11, 1, chi), chi)
    assert spring == 82800 and fall == 90000  # 23 h and 25 h


def test_a_month_is_not_a_length():
    sep11 = ic.tai_from_unix(1662854400)  # 2022-09-11T00:00:00Z
    assert caldur(months=1).seconds_at(sep11) == 30 * 86400
    jan11 = ic.tai_from_unix(1641859200)  # 2022-01-11
    assert caldur(months=1).seconds_at(jan11) == 31 * 86400


def test_month_arithmetic_clamps_day_of_month():
    jan31 = day_start(2023, 1, 31)
    assert caldur(months=1).resolve(jan31) == ic.Instant(day_start(2023, 2, 28))
    jan31_leapyear = day_start(2024, 1, 31)
    assert caldur(months=1).resolve(jan31_leapyear).t == day_start(2024, 2, 29)
    assert caldur(months=-1).resolve(day_start(2023, 3, 31)).t == day_start(2023, 2, 28)


def test_the_seconds_tail_is_exact_physical_time():
    # An hour of TAI starting 23:00 on a leap-second day ends *inside* the
    # inserted second, not at midnight — the honest answer, and the reason
    # hours/minutes/seconds are physical here and not civil units.
    t = day_start(2016, 12, 31) + 82800  # 2016-12-31T23:00 UTC
    assert ic.civil(duration(3600).at(t).end).text() == "2016-12-31T23:59:60"
    assert caldur(days=1).seconds_at(t) == 86401  # the civil day spans it


def test_nonexistent_local_times_raise():
    chi = "America/Chicago"
    before = day_start(2026, 3, 7, chi) + 2 * 3600 + 1800  # 02:30 local
    with pytest.raises(NonexistentTime):
        caldur(days=1).resolve(before, chi)


def test_anchored_nominal_step_resolves_through_the_lens():
    sep11 = ic.tai_from_unix(1662854400)
    cs = caldur(months=1).at(sep11)
    assert isinstance(cs, CalSpan)
    assert cs.duration == 30 * 86400
    assert cs.span() == ic.span(sep11.t, sep11.t + 30 * 86400)
    assert cs.end().t == sep11.t + 30 * 86400
    # the name stays symbolic: no leap table or tzdata baked in
    assert name(cs) == "ic1:n:mo=1@1662854437"


def test_sub_second_anchor_survives():
    t = ic.tai_from_unix(F(1662854400) + F(1, 3))
    assert caldur(days=1).resolve(t).t - t.t == 86400


# --- ISO-8601 sugar --------------------------------------------------------


def test_iso_forms():
    assert from_iso("PT1H30M") == duration(5400)
    assert from_iso("P1M") == caldur(months=1)
    assert from_iso("P1Y2M3DT4H") == caldur(years=1, months=2, days=3, hours=4)
    assert from_iso("P2W") == caldur(days=14)
    assert from_iso("-P1M") == caldur(months=-1)
    assert caldur(months=14, days=3, seconds=F(3, 2)).iso == "P1Y2M3DT1.5S"
    with pytest.raises(ValueError):
        from_iso("1M")


def test_iso_refuses_to_round():
    with pytest.raises(ValueError, match="exact decimal"):
        caldur(months=1, seconds=F(1, 3)).iso


def test_degenerate_nominal_step_is_rejected_at_the_type():
    with pytest.raises(ValueError, match="Duration"):
        CalDuration(0, 0, duration(60))


# --- durations act on time by translation ---------------------------------


def test_instant_plus_duration():
    t = ic.Instant(10)
    assert t + duration(5) == ic.Instant(15)
    assert duration(5) + t == ic.Instant(15)
    assert t - duration(5) == ic.Instant(5)
    assert t - ic.Instant(3) == duration(7)
    # the bug this guards: rat() must strip the Duration back to a scalar,
    # or Instant.t (and w, phi, …) end up holding a Duration
    assert type((t + duration(5)).t) is F


def test_instant_plus_nominal_step_needs_a_lens():
    t = ic.Instant(day_start(2022, 9, 11))
    with pytest.raises(TypeError, match="anchored"):
        t + caldur(months=1)
    assert t.plus(caldur(months=1)).t == day_start(2022, 10, 11)
    assert t.minus(caldur(months=1)).t == day_start(2022, 8, 11)
    chi = "America/Chicago"
    assert t.plus(caldur(days=1), chi).t - t.t == 86400  # no DST that night


def test_month_steps_do_not_always_round_trip():
    # Clamping is not invertible, and the API says so out loud.
    mar31 = ic.Instant(day_start(2023, 3, 31))
    back = mar31.minus(caldur(months=1))
    assert back.t == day_start(2023, 2, 28)
    assert back.plus(caldur(months=1)).t == day_start(2023, 3, 28)


def test_every_five_seconds_shifted_by_a_step():
    every5 = duration(5).phase(2)             # 5 s on, 5 s off, forever
    assert name(every5 + duration(1)) == "ic1:c:w=5;m=2;phi=1"
    # shifting by the period is the identity — that is why φ ∈ [0, P)
    assert every5 + duration(10) == every5
    assert every5 + duration(-10) == every5
    # shifting by k·w walks the siblings of §2.1
    assert every5 + duration(5) == duration(5).phase(2, k=1)
    assert (every5 + duration(5)).state == 1


def test_translation_covers_every_kind_of_set():
    d = duration(F(1, 2))
    assert ic.ALWAYS + d is ic.ALWAYS and ic.NEVER + d is ic.NEVER
    assert ic.span(0, 10) + d == ic.span(F(1, 2), F(21, 2))
    assert ic.span(0, 10) - d == ic.span(F(-1, 2), F(19, 2))
    w = ic.windowed(ic.span(0, 10), ic.phase(1, 3))
    assert w + d == ic.windowed(ic.span(F(1, 2), F(21, 2)), ic.phase(1, 3, phi=F(1, 2)))
    p = ic.pset(1, [(0, F(1, 4)), (F(1, 2), F(1, 8))])
    assert ic.shift(p, d) == ic.pset(1, [(F(1, 2), F(1, 4)), (0, F(1, 8))])
    assert ic.shift(p, d) + d == p                     # translation is a group


def test_eternal_sets_refuse_nominal_steps():
    with pytest.raises(TypeError, match="no fixed length"):
        ic.phase(5, 2) + caldur(months=1)
    with pytest.raises(TypeError, match="duration in seconds"):
        ic.phase(5, 2) + ic.span(0, 1)
    with pytest.raises(TypeError, match="resolve it"):
        ic.shift(ic.cell("day", 2026, 1, 1), duration(5))
