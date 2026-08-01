"""The physical timeline: exact rational seconds on TAI.

Epoch E = 1970-01-01T00:00:00 TAI (the IEEE 1588 / PTP epoch): leap-second
free and monotone. Civil time (UTC, zones, calendars) is a *lens* layered on
top — see calendar.py. Conversions go through a bundled, versioned
leap-second table (exact from 1972; proleptic offset of 10 s before that —
the 1958–1972 "rubber seconds" era is deliberately not modeled).

Names in this system are pure functions of their parameters; no clock is
needed to compute them. Only now() consults a clock, and it returns an
uncertainty bound because NTP sync error makes "which state are we in right
now" genuinely ambiguous near slot boundaries.
"""

from __future__ import annotations

import time
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timezone
from fractions import Fraction

from .rat import rat

# ±2^63 integer seconds (~±292 Gyr) — enforces the fixed window. Product
# intent is ±20 Gyr (Big Bang to far future), comfortably inside.
MAX_ABS_SECONDS = 2**63

LEAP_TABLE_VERSION = "IERS-2017-01"

# (UTC date the new offset takes effect, TAI−UTC seconds from that date on).
_LEAP_DATES: list[tuple[date, int]] = [
    (date(1972, 1, 1), 10),
    (date(1972, 7, 1), 11),
    (date(1973, 1, 1), 12),
    (date(1974, 1, 1), 13),
    (date(1975, 1, 1), 14),
    (date(1976, 1, 1), 15),
    (date(1977, 1, 1), 16),
    (date(1978, 1, 1), 17),
    (date(1979, 1, 1), 18),
    (date(1980, 1, 1), 19),
    (date(1981, 7, 1), 20),
    (date(1982, 7, 1), 21),
    (date(1983, 7, 1), 22),
    (date(1985, 7, 1), 23),
    (date(1988, 1, 1), 24),
    (date(1990, 1, 1), 25),
    (date(1991, 1, 1), 26),
    (date(1992, 7, 1), 27),
    (date(1993, 7, 1), 28),
    (date(1994, 7, 1), 29),
    (date(1996, 1, 1), 30),
    (date(1997, 7, 1), 31),
    (date(1999, 1, 1), 32),
    (date(2006, 1, 1), 33),
    (date(2009, 1, 1), 34),
    (date(2012, 7, 1), 35),
    (date(2015, 7, 1), 36),
    (date(2017, 1, 1), 37),
]


def _unix_of_date(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


# (unix boundary, TAI−UTC after boundary), ascending.
_LEAP_UNIX: list[tuple[int, int]] = [(_unix_of_date(d), o) for d, o in _LEAP_DATES]
_BOUNDS = [b for b, _ in _LEAP_UNIX]


class RangeError(ValueError):
    """Instant outside the ±2^63-second window."""


@dataclass(frozen=True, order=True)
class Instant:
    """An exact point on the TAI timeline: rational seconds since epoch."""

    t: Fraction

    def __post_init__(self):
        q = rat(self.t)
        object.__setattr__(self, "t", q)
        if not (-MAX_ABS_SECONDS <= q < MAX_ABS_SECONDS):
            raise RangeError(f"instant {q} outside ±2^63 s window")

    def __add__(self, dt) -> "Instant":
        return Instant(self.t + rat(dt))

    def __sub__(self, other):
        if isinstance(other, Instant):
            return self.t - other.t
        return Instant(self.t - rat(other))


def tai_minus_utc(unix: Fraction) -> int:
    """TAI−UTC offset in effect at a given unix (UTC-scale) time."""
    i = bisect_right(_BOUNDS, unix)
    if i == 0:
        return 10  # proleptic: extend the 1972 offset backwards
    return _LEAP_UNIX[i - 1][1]


def tai_from_unix(unix) -> Instant:
    """Unix (UTC-scale, leap-second-blind) → TAI seconds since epoch."""
    u = rat(unix)
    return Instant(u + tai_minus_utc(u))


def unix_from_tai(t: Instant | Fraction) -> tuple[Fraction, bool]:
    """TAI → (unix seconds, in_leap_second).

    During an inserted leap second (UTC 23:59:60), unix time has no honest
    value; we return the unix boundary minus 1 plus the fraction elapsed in
    the leap second, with in_leap_second=True (i.e. the :60 second re-reads
    as a second pass through :59, PEP-495-style).
    """
    q = t.t if isinstance(t, Instant) else rat(t)
    # Find the offset o such that u = q - o falls in o's validity bracket.
    for i in range(len(_LEAP_UNIX), -1, -1):
        o = 10 if i == 0 else _LEAP_UNIX[i - 1][1]
        lo = None if i == 0 else _LEAP_UNIX[i - 1][0]
        hi = None if i == len(_LEAP_UNIX) else _LEAP_UNIX[i][0]
        u = q - o
        if (lo is None or u >= lo) and (hi is None or u < hi):
            return u, False
        # Inserted leap second before boundary i: TAI in [hi + o, hi + o + 1)
        if hi is not None and hi + o <= q < hi + o + 1:
            frac = q - (hi + o)
            return hi - 1 + frac, True
    raise AssertionError("unreachable: leap table bracket search failed")


def now(uncertainty: Fraction | None = None) -> tuple[Instant, Fraction]:
    """Current instant on TAI, with a sync-uncertainty bound.

    Assumes the system clock is NTP-disciplined. We do not query the NTP
    daemon; the default bound is a conservative 100 ms. Callers with a
    chrony/PTP-grade setup can pass their own bound.
    """
    unix = Fraction(time.time_ns(), 10**9)
    err = rat(uncertainty) if uncertainty is not None else Fraction(1, 10)
    return tai_from_unix(unix), err
