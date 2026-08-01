from fractions import Fraction as F

import pytest

from intervalclock import (
    NEVER,
    cell,
    cell_span,
    cron_next_after,
    encode,
    from_cron,
    name,
    parse,
    to_cron,
)


def test_canonical_equivalences():
    canonical = from_cron("*/5 * * * *")
    assert name(canonical) == "ic1:k:0-55/5|*|*|*|*"
    for eq in [
        "0-59/5 * * * *",
        "0,5,10,15,20,25,30,35,40,45,50,55 * * * *",
    ]:
        assert encode(from_cron(eq)) == encode(canonical)


def test_star_equivalences():
    assert encode(from_cron("* * * * *")) == encode(
        from_cron("0-59 0-23 1-31 1-12 0-6")
    )


def test_dow_seven_is_sunday():
    assert from_cron("* * * * 7") == from_cron("* * * * 0")
    assert from_cron("* * * * SUN") == from_cron("* * * * 0")


def test_month_and_dow_names():
    assert from_cron("0 0 * JAN MON") == from_cron("0 0 * 1 1")


def test_vixie_dom_dow_or_split():
    s = from_cron("0 0 1,15 * 1")
    assert len(s.records) == 2
    # one record dom-restricted with full dow, one the reverse
    doms = sorted(r.dom.bit_count() for r in s.records)
    assert doms == [2, 31]


def test_impossible_is_never():
    assert from_cron("0 0 31 2 *") is NEVER
    assert from_cron("0 0 30 2 *") is NEVER
    assert from_cron("0 0 29 2 *") is not NEVER  # leap years exist


def test_roundtrip_text():
    for expr in ["*/5 * * * *", "0 9 * * 2", "30 2 * * *", "0 0 1,15 * 1"]:
        s = from_cron(expr)
        assert parse(name(s)) == s
        assert from_cron(*to_cron(s).split(" + ")[:1]) is not None


def test_next_after_simple():
    s = from_cron("0 9 * * 2")  # Tuesdays 09:00 UTC
    t0 = cell_span(cell("day", 2026, 8, 1)).start  # Saturday
    nxt = cron_next_after(s, t0)
    from intervalclock import civil, Instant

    c = civil(Instant(nxt.start))
    assert c.fields[:5] == (2026, 8, 4, 9, 0)  # Tue Aug 4
    assert nxt.duration == 60


def test_dst_spring_forward_skip():
    s = from_cron("30 2 * * *", zone="America/New_York")
    t0 = cell_span(cell("day", 2026, 3, 7, zone="America/New_York")).start
    first = cron_next_after(s, t0)  # Mar 7 02:30
    second = cron_next_after(s, first.start)  # Mar 8 02:30 skipped → Mar 9
    assert (second.start - first.start) / 3600 == 47


def test_dst_fall_back_fires_once():
    s = from_cron("30 1 * * *", zone="America/New_York")
    t0 = cell_span(cell("day", 2026, 11, 1, zone="America/New_York")).start
    first = cron_next_after(s, t0)
    second = cron_next_after(s, first.start)
    # Fires on the first 01:30 only; next firing is the following day.
    assert (second.start - first.start) / 3600 == 25


def test_leap_second_minute_is_61s():
    s = from_cron("59 23 31 12 *")
    t0 = cell_span(cell("day", 2016, 12, 30)).start
    nxt = cron_next_after(s, t0)
    assert nxt.duration == 61


def test_zone_in_name():
    s = from_cron("0 9 * * 2", zone="America/Chicago")
    assert name(s).endswith("!America/Chicago")
    assert parse(name(s)) == s
