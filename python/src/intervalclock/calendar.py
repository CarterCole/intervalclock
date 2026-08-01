"""The civil lens: calendar cells over the physical timeline.

Calendar units are NOT fixed-length in physical time (leap-second days are
86 401 s, DST days are 23/25 h, months vary) and future leap seconds are not
computable. So Cells are canonical *symbolic* names; resolving one to a
physical Span is a function stamped with (leap-table version, tzdata
version). Same cell ID everywhere; same resolution given the same tables.

DST policy (decisive, tested): nonexistent local times raise
NonexistentTime; ambiguous local times take the requested fold (default 0,
PEP 495). Leap seconds: the UTC lens maps 23:59:60 into the day's 86 401-s
span; physical classes never notice (that is the point of TAI).
"""

from __future__ import annotations

import calendar as _cal
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from zoneinfo import ZoneInfo

from .core import Span
from .timescale import (
    LEAP_TABLE_VERSION,
    Instant,
    tai_from_unix,
    unix_from_tai,
)

__all__ = [
    "Cell", "cell", "cell_span", "civil", "NonexistentTime", "KINDS",
    "resolution_versions",
]

KINDS = ("year", "month", "day", "hour", "minute", "second", "isoweek")

_EPOCH_DT = datetime(1970, 1, 1, tzinfo=timezone.utc)


class NonexistentTime(ValueError):
    """A local wall-clock time skipped by a DST spring-forward."""


def resolution_versions() -> dict:
    """The mutable-table versions a Span resolution is stamped with."""
    import zoneinfo

    try:
        import importlib.metadata as md

        tzver = md.version("tzdata")
    except Exception:
        tzver = "system"
    return {"leap_table": LEAP_TABLE_VERSION, "tzdata": tzver}


@dataclass(frozen=True)
class Cell:
    """A symbolic calendar name: kind + fields + IANA zone.

    fields by kind:
      year (y,) · month (y, mo) · day (y, mo, d) · hour (y, mo, d, h)
      minute (y, mo, d, h, mi) · second (y, mo, d, h, mi, s) · isoweek (y, w)
    second may be 60 only for an inserted leap second (UTC zone).
    """

    kind: str
    fields: tuple[int, ...]
    zone: str = "UTC"

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"unknown cell kind {self.kind!r}")
        f = tuple(int(x) for x in self.fields)
        object.__setattr__(self, "fields", f)
        n_expected = {"year": 1, "month": 2, "day": 3, "hour": 4,
                      "minute": 5, "second": 6, "isoweek": 2}[self.kind]
        if len(f) != n_expected:
            raise ValueError(f"{self.kind} cell needs {n_expected} fields")
        y = f[0]
        if self.kind == "isoweek":
            wk = f[1]
            weeks = date(y, 12, 28).isocalendar().week  # 52 or 53
            if not 1 <= wk <= weeks:
                raise ValueError(f"ISO week {wk} out of range for {y}")
            return
        if len(f) >= 2 and not 1 <= f[1] <= 12:
            raise ValueError("month out of range")
        if len(f) >= 3 and not 1 <= f[2] <= _cal.monthrange(y, f[1])[1]:
            raise ValueError("day out of range")
        if len(f) >= 4 and not 0 <= f[3] <= 23:
            raise ValueError("hour out of range")
        if len(f) >= 5 and not 0 <= f[4] <= 59:
            raise ValueError("minute out of range")
        if len(f) >= 6 and not 0 <= f[5] <= 60:
            raise ValueError("second out of range")

    @property
    def is_leap_second(self) -> bool:
        return self.kind == "second" and self.fields[5] == 60

    def text(self) -> str:
        f = self.fields
        if self.kind == "isoweek":
            body = f"{f[0]:04d}-W{f[1]:02d}"
        else:
            parts = [f"{f[0]:04d}"]
            if len(f) >= 2:
                parts.append(f"-{f[1]:02d}")
            if len(f) >= 3:
                parts.append(f"-{f[2]:02d}")
            if len(f) >= 4:
                parts.append(f"T{f[3]:02d}")
            if len(f) >= 5:
                parts.append(f":{f[4]:02d}")
            if len(f) >= 6:
                parts.append(f":{f[5]:02d}")
            body = "".join(parts)
        return body if self.zone == "UTC" else f"{body}!{self.zone}"

    def __repr__(self):
        return f"Cell[{self.text()}]"


def cell(kind: str, *fields: int, zone: str = "UTC") -> Cell:
    return Cell(kind, tuple(fields), zone)


def _tz(zone: str):
    return timezone.utc if zone == "UTC" else ZoneInfo(zone)


def _aware(naive: datetime, zone: str, fold: int) -> datetime:
    """Attach a zone, raising NonexistentTime for DST-gap wall times."""
    tz = _tz(zone)
    dt = naive.replace(tzinfo=tz, fold=fold)
    # A nonexistent local time fails the UTC round-trip.
    if dt.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != naive:
        raise NonexistentTime(f"{naive} does not exist in {zone}")
    return dt


def _unix(dt_aware: datetime) -> int:
    d = dt_aware.astimezone(timezone.utc) - _EPOCH_DT
    return d.days * 86400 + d.seconds


def _bounds_naive(c: Cell) -> tuple[datetime, datetime]:
    f = c.fields
    y = f[0]
    if c.kind == "year":
        return datetime(y, 1, 1), datetime(y + 1, 1, 1)
    if c.kind == "month":
        nxt = (y + 1, 1) if f[1] == 12 else (y, f[1] + 1)
        return datetime(y, f[1], 1), datetime(*nxt, 1)
    if c.kind == "isoweek":
        d0 = date.fromisocalendar(y, f[1], 1)
        return (
            datetime(d0.year, d0.month, d0.day),
            datetime(d0.year, d0.month, d0.day) + timedelta(days=7),
        )
    if c.kind == "day":
        s = datetime(y, f[1], f[2])
        return s, s + timedelta(days=1)
    if c.kind == "hour":
        s = datetime(y, f[1], f[2], f[3])
        return s, s + timedelta(hours=1)
    if c.kind == "minute":
        s = datetime(y, f[1], f[2], f[3], f[4])
        return s, s + timedelta(minutes=1)
    # second
    s = datetime(y, f[1], f[2], f[3], f[4], f[5] if f[5] < 60 else 59)
    return s, s + timedelta(seconds=1)


def cell_span(c: Cell, fold: int = 0) -> Span:
    """Resolve a symbolic cell to its physical TAI Span.

    The result depends on the bundled leap table and the host tzdata — see
    resolution_versions(). Leap-second days come out 86 401 s long without
    any special-casing: that is the two-layer split doing its job.
    """
    if c.is_leap_second:
        if c.zone != "UTC":
            raise ValueError("leap seconds are a UTC phenomenon")
        # 23:59:60 occupies TAI [b + o_before, b + o_before + 1) where b is
        # the unix midnight boundary it precedes (= the end bound of the
        # :59 second it follows).
        b = _unix(_bounds_naive(c)[1].replace(tzinfo=timezone.utc))
        from .timescale import tai_minus_utc

        o_before = tai_minus_utc(Fraction(b) - 1)
        return Span(b + o_before, b + o_before + 1)
    s_naive, e_naive = _bounds_naive(c)
    s = tai_from_unix(_unix(_aware(s_naive, c.zone, fold)))
    e = tai_from_unix(_unix(_aware(e_naive, c.zone, fold)))
    return Span(s.t, e.t)


def civil(t: Instant | Fraction, zone: str = "UTC") -> Cell:
    """The second-kind cell containing a physical instant.

    During an inserted leap second the UTC cell reads :60 (only meaningful
    for zone='UTC'; other zones re-read the previous second, PEP-495-style).
    """
    unix, leap = unix_from_tai(t)
    whole = int(unix // 1)
    dt = (_EPOCH_DT + timedelta(seconds=whole)).astimezone(_tz(zone))
    sec = 60 if (leap and zone == "UTC") else dt.second
    return Cell(
        "second", (dt.year, dt.month, dt.day, dt.hour, dt.minute, sec), zone
    )
