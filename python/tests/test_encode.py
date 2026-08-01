from fractions import Fraction as F

import pytest

from intervalclock import (
    ALWAYS,
    NEVER,
    Instant,
    RangeError,
    ReservedTypeError,
    cell,
    decode,
    encode,
    from_cron,
    from_url,
    name,
    parse,
    phase,
    pset,
    span,
    to_url,
    windowed,
)

GOLDEN = [
    (phase(F(1, 3), 3, k=2), "ic1:c:w=1/3;m=3;phi=2/3"),
    (phase(F(1, 15), 2, phi=F(7, 90)), "ic1:c:w=1/15;m=2;phi=7/90"),
    (cell("hour", 2026, 8, 1, 14), "ic1:g:2026-08-01T14"),
    (cell("isoweek", 2026, 31), "ic1:g:2026-W31"),
    (from_cron("*/5 * * * *"), "ic1:k:0-55/5|*|*|*|*"),
    (NEVER, "ic1:never"),
    (ALWAYS, "ic1:always"),
]


@pytest.mark.parametrize("obj,text", GOLDEN)
def test_golden_names(obj, text):
    assert name(obj) == text
    assert parse(text) == obj


def _objects():
    return [
        NEVER,
        ALWAYS,
        Instant(F(1, 3)),
        Instant(F(-987654321, 7)),
        span(0, F(7, 2)),
        span(F(-5, 3), F(22, 7)),
        phase(F(1, 3), 3, k=2),
        pset(1, [(0, F(1, 4)), (F(1, 3), F(1, 4))]),
        cell("hour", 2026, 8, 1, 14),
        cell("day", 2016, 12, 31),
        cell("minute", 2026, 7, 4, 9, 30, zone="America/New_York"),
        from_cron("*/5 * * * *"),
        from_cron("0 9 * * 2", zone="America/Chicago"),
        windowed(span(0, 10), phase(F(1, 3), 3, k=1)),
    ]


@pytest.mark.parametrize("obj", _objects(), ids=lambda o: name(o)[:40])
def test_roundtrips(obj):
    assert parse(name(obj)) == obj
    assert decode(encode(obj)) == obj
    assert from_url(to_url(obj)) == obj


def test_equal_sets_equal_bytes():
    a = phase(F(1, 3), 3, k=2)
    b = phase(F(1, 3), 3, delta=F(2, 3) + 5)  # same set, redundant input
    assert encode(a) == encode(b)
    assert encode(from_cron("*/5 * * * *")) == encode(from_cron("0-59/5 * * * *"))


def test_instant_byte_sort_is_chronological_by_floor():
    ts = [F(-10), F(-1, 3), F(0), F(1, 7), F(5), F(10**9)]
    ids = [encode(Instant(t)) for t in ts]
    assert ids == sorted(ids)


def test_span_byte_sort_by_start():
    ids = [encode(span(s, s + 1)) for s in [F(-100), F(-1, 2), 0, F(99, 7), 1000]]
    assert ids == sorted(ids)


def test_phase_ids_cluster_by_period():
    small = encode(phase(F(1, 30), 2))
    big = encode(phase(1000, 2))
    assert small < big  # f64(P) big-endian sorts by period


def test_reserved_tag_0x8():
    with pytest.raises(ReservedTypeError):
        decode(bytes([0x18]))
    with pytest.raises(ReservedTypeError):
        parse("ic1:f:fs=10;N=64;k=3")


def test_version_nibble_enforced():
    with pytest.raises(ValueError):
        decode(bytes([0x24]))  # version 2


def test_range_bound():
    with pytest.raises(RangeError):
        Instant(F(2**63) + 1)
    Instant(F(-(2**63)))  # lower edge OK


def test_url_case_and_confusables():
    u = to_url(phase(F(1, 3), 3, k=2))
    assert from_url(u.lower()) == phase(F(1, 3), 3, k=2)
