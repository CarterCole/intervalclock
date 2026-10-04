"""Durations: the canonical step in time.

Every other object in this library is a *set* of time. A duration is not:
it is a **measure** — the length of a step, with no place on the timeline.
Formally it is the translation-invariance class of a Span: Span(a, b) and
Span(a+t, b+t) have the same duration, and quotienting the timeline by the
translation group is exactly what "how long" means.

Two layers, forced by the same physics that forces the calendar lens
(PROTOCOL.md §5) — and split along the same line java.time draws between
Duration and Period:

  * ``Duration``    — exact ℚ seconds of TAI. Physical, signed, computable
                      by anyone, no tables consulted.
  * ``CalDuration`` — a *nominal* step: months, days, and an exact tail.
                      "1 month" and "1 day" are not lengths at all until
                      they are applied to an anchor: months vary, DST days
                      are 23/25 h, leap-second days are 86 401 s. Resolving
                      one is stamped with (leap table, tzdata) versions.

A Duration also generates a **grid**: anchor a step at a phase and you get
the coordinate system that tiles all of time into consecutive slots
(``Duration.grid``). A Grid is a coordinate system, not a set of time —
as a set it is simply ALWAYS — so it has no ID; its identity is the pair
(step, phase), both of which do.
"""

from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import timedelta
from fractions import Fraction
from typing import Iterator, Optional

from .calendar import _EPOCH_DT, _aware, _tz, _unix
from .core import PhaseClass, Span, phase
from .rat import fmt, rat
from .timescale import Instant, tai_from_unix, unix_from_tai

__all__ = [
    "Duration", "CalDuration", "CalSpan", "Grid", "duration", "caldur",
    "cal_span", "from_iso", "between", "ZERO",
]


def _t(x) -> Fraction:
    return x.t if isinstance(x, Instant) else rat(x)


class Duration(Fraction):
    """An exact rational number of SI seconds — signed, translation-free.

    It *is* a Fraction (so it compares and computes as the number it is),
    with a canonical name of its own and the projections that put it back
    on the timeline: ``at`` (a Span), ``grid`` (the tiling), ``phase`` (a
    periodic class whose pulse is this long).
    """

    __slots__ = ()

    def __new__(cls, value=0, denominator=None):
        if denominator is None:
            value = rat(value)
            return super().__new__(cls, value.numerator, value.denominator)
        return super().__new__(cls, value, denominator)

    # -- projections back onto the timeline ---------------------------------

    @property
    def seconds(self) -> Fraction:
        """The plain Fraction of seconds (drops the Duration wrapper)."""
        return Fraction(self.numerator, self.denominator)

    @property
    def hz(self) -> Fraction:
        """1/d — the repetition rate of a step this long."""
        if self == 0:
            raise ValueError("a zero-length step has no rate")
        return Fraction(self.denominator, self.numerator)

    @property
    def iso(self) -> str:
        """ISO-8601 form. Raises if there is no exact decimal spelling."""
        return _iso_text(0, 0, self)

    def at(self, t) -> Span:
        """The Span this step covers starting (or ending) at t."""
        a = _t(t)
        if self == 0:
            raise ValueError("a zero-length step covers no span")
        return Span(a, a + self) if self > 0 else Span(a + self, a)

    def grid(self, phi=0) -> "Grid":
        """The coordinate system that tiles all time into steps of this size."""
        return Grid(self, rat(phi))

    def phase(self, m: int, k: int = 0, phi=0) -> PhaseClass:
        """Φ(d, m, ·): a pulse this long, once every m steps, state k."""
        if self <= 0:
            raise ValueError("a phase class needs a positive pulse width")
        return phase(self.seconds, m, phi=rat(phi), k=k)

    # -- arithmetic (dimensionally honest: d/d is a plain ratio) ------------

    def _wrap(self, q):
        return q if q is NotImplemented else Duration(q)

    def __add__(self, other):
        if isinstance(other, Instant):
            return other + self.seconds
        return self._wrap(Fraction.__add__(self, other))

    __radd__ = __add__

    def __sub__(self, other):
        return self._wrap(Fraction.__sub__(self, other))

    def __rsub__(self, other):
        if isinstance(other, Instant):
            return other - self.seconds
        return self._wrap(Fraction.__rsub__(self, other))

    def __mul__(self, other):
        return self._wrap(Fraction.__mul__(self, other))

    __rmul__ = __mul__

    def __truediv__(self, other):
        q = Fraction.__truediv__(self, other)
        # Duration / Duration is a dimensionless ratio, not a duration.
        return q if isinstance(other, Duration) else self._wrap(q)

    def __neg__(self):
        return Duration(Fraction.__neg__(self))

    def __pos__(self):
        return self

    def __abs__(self):
        return Duration(Fraction.__abs__(self))

    def __repr__(self):
        return f"Duration[{fmt(self.seconds)} s]"


ZERO = Duration(0)


def duration(x) -> Duration:
    """Coerce seconds (int, Fraction, '5/2', float) to a Duration."""
    return x if isinstance(x, Duration) else Duration(rat(x))


def between(a, b) -> Duration:
    """The step from a to b (signed): b − a."""
    return Duration(_t(b) - _t(a))


# ---------------------------------------------------------------------------
# The grid: a step + a phase = a coordinate system on the timeline


@dataclass(frozen=True)
class Grid:
    """All of time cut into consecutive slots of one step, anchored at phi.

    Not a set of time (as a set it is ALWAYS) and therefore not nameable:
    a Grid is a *coordinate system*, the physical twin of the calendar. Its
    identity is (step, phi) — both of which have canonical names.
    """

    step: Duration
    phi: Fraction = Fraction(0)

    def __post_init__(self):
        object.__setattr__(self, "step", duration(self.step))
        if self.step <= 0:
            raise ValueError("a grid step must be positive")
        object.__setattr__(self, "phi", rat(self.phi) % self.step.seconds)

    def index(self, t) -> int:
        """Which slot contains t (slot 0 starts at phi)."""
        return int((_t(t) - self.phi) // self.step.seconds)

    def slot(self, n: int) -> Span:
        start = self.phi + n * self.step.seconds
        return Span(start, start + self.step.seconds)

    def slot_at(self, t) -> Span:
        return self.slot(self.index(t))

    def floor(self, t) -> Fraction:
        """Snap down to the grid."""
        return self.phi + self.index(t) * self.step.seconds

    def ceil(self, t) -> Fraction:
        f = self.floor(t)
        return f if f == _t(t) else f + self.step.seconds

    def snap(self, t) -> Fraction:
        """Snap to the nearest gridpoint (ties go up, like round-half-up)."""
        f = self.floor(t)
        return f if _t(t) - f < self.step.seconds / 2 else f + self.step.seconds

    def slots(self, within: Span) -> Iterator[Span]:
        """Every slot that intersects a span, in order."""
        n = self.index(within.start)
        while True:
            s = self.slot(n)
            if s.start >= within.end:
                return
            yield s
            n += 1

    def classes(self, m: int) -> list[PhaseClass]:
        """The m siblings at this step: they partition all of time."""
        return [self.step.phase(m, k=k, phi=self.phi) for k in range(m)]

    def __repr__(self):
        return f"Grid[step={fmt(self.step.seconds)} s @ phi={fmt(self.phi)}]"


# ---------------------------------------------------------------------------
# Nominal (civil) durations

_ISO_RE = re.compile(
    r"^(?P<sign>[+-])?P(?!$)(?:(?P<y>-?\d+)Y)?(?:(?P<mo>-?\d+)M)?"
    r"(?:(?P<w>-?\d+)W)?(?:(?P<d>-?\d+)D)?"
    r"(?:T(?!$)(?:(?P<h>-?\d+)H)?(?:(?P<mi>-?\d+)M)?"
    r"(?:(?P<s>-?\d+(?:\.\d+)?)S)?)?$"
)


@dataclass(frozen=True)
class CalDuration:
    """A nominal step: months, then days, then an exact tail of seconds.

    Applied in that order to an anchor. Only three fields are needed because
    the civil calendar fixes the rest exactly: 1 year = 12 months and
    1 week = 7 days *always*, while 1 hour, minute and second are exact
    physical seconds. What months and days are *not* is a length: they mean
    "same day-of-month next month" and "same wall clock tomorrow", so they
    only become seconds against an anchor and a zone.

    Day-of-month clamping is the standard one: Jan 31 + 1 month = Feb 28
    (29 in a leap year).
    """

    months: int = 0
    days: int = 0
    secs: Duration = ZERO

    def __post_init__(self):
        object.__setattr__(self, "months", int(self.months))
        object.__setattr__(self, "days", int(self.days))
        object.__setattr__(self, "secs", duration(self.secs))
        if self.months == 0 and self.days == 0:
            # Nothing but an exact tail is a physical step, and has its own
            # type — one name per thing. Use caldur() to get the reduction.
            raise ValueError("a nominal step needs months or days; this is a Duration")

    @property
    def is_nominal(self) -> bool:
        return True

    def text(self) -> str:
        parts = []
        if self.months:
            parts.append(f"mo={self.months}")
        if self.days:
            parts.append(f"d={self.days}")
        if self.secs:
            parts.append(f"s={fmt(self.secs.seconds)}")
        return ";".join(parts)

    @property
    def iso(self) -> str:
        """ISO-8601 form. Raises if the tail has no exact decimal spelling."""
        return _iso_text(self.months, self.days, self.secs)

    # -- resolution against an anchor (the civil lens) ----------------------

    def resolve(self, anchor, zone: str = "UTC",
                fold: Optional[int] = None) -> Instant:
        """anchor + this step, on the civil lens of `zone`.

        Months and days are wall-clock arithmetic (a DST day really is 23 or
        25 hours); the seconds tail is added as exact physical time, so a
        tail that crosses a leap second lands one second earlier on the wall
        clock than a naive reading suggests. Both are the honest answers —
        see PROTOCOL.md §5.
        """
        t = _t(anchor)
        unix, _leap = unix_from_tai(t)
        whole = int(unix // 1)
        frac = unix - whole
        aware = (_EPOCH_DT + timedelta(seconds=whole)).astimezone(_tz(zone))
        naive = aware.replace(tzinfo=None)
        if self.months:
            total = naive.year * 12 + (naive.month - 1) + self.months
            y, mo = divmod(total, 12)
            mo += 1
            naive = naive.replace(
                year=y, month=mo, day=min(naive.day, monthrange(y, mo)[1])
            )
        if self.days:
            naive = naive + timedelta(days=self.days)
        f = aware.fold if fold is None else fold
        moved = tai_from_unix(_unix(_aware(naive, zone, f)))
        return Instant(moved.t + frac + self.secs.seconds)

    def span(self, anchor, zone: str = "UTC",
             fold: Optional[int] = None) -> Span:
        """The interval this step covers from an anchor."""
        a = _t(anchor)
        b = self.resolve(a, zone, fold).t
        if a == b:
            raise ValueError("this step is zero-length at that anchor")
        return Span(min(a, b), max(a, b))

    def seconds_at(self, anchor, zone: str = "UTC",
                   fold: Optional[int] = None) -> Duration:
        """How many exact seconds this nominal step is worth at an anchor."""
        return Duration(self.resolve(anchor, zone, fold).t - _t(anchor))

    def __neg__(self) -> "CalDuration":
        return CalDuration(-self.months, -self.days, -self.secs)

    def __repr__(self):
        return f"CalDuration[{self.iso}]"


def _iso_text(months: int, days: int, secs: "Duration") -> str:
    """The ISO-8601 spelling shared by both kinds of step."""
    y, mo = divmod(abs(months), 12)
    sign = "-" if months < 0 else ""
    date_part = ""
    if y:
        date_part += f"{sign}{y}Y"
    if mo:
        date_part += f"{sign}{mo}M"
    if days:
        date_part += f"{days}D"
    time_part = ""
    if secs:
        q = abs(secs.seconds)
        sg = "-" if secs < 0 else ""
        h, q = divmod(q, 3600)
        mi, q = divmod(q, 60)
        if h:
            time_part += f"{sg}{int(h)}H"
        if mi:
            time_part += f"{sg}{int(mi)}M"
        if q:
            time_part += f"{sg}{_decimal(q)}S"
        time_part = "T" + time_part
    return "P" + (date_part + time_part or "T0S")


def _decimal(q: Fraction) -> str:
    """Exact decimal spelling, or a refusal — never a silent rounding."""
    from decimal import Decimal

    d = q.denominator
    for p in (2, 5):
        while d % p == 0:
            d //= p
    if d != 1:
        raise ValueError(
            f"{fmt(q)} s has no exact decimal form; use the ic1:n: name"
        )
    out = str(Decimal(q.numerator) / Decimal(q.denominator))
    return out.rstrip("0").rstrip(".") if "." in out else out


def caldur(years: int = 0, months: int = 0, weeks: int = 0, days: int = 0,
           hours=0, minutes=0, seconds=0):
    """Build a nominal step, reducing to a physical Duration when it is one.

    Years fold into months and weeks into days exactly (12 and 7, always);
    hours, minutes and seconds fold into the exact tail. A step with nothing
    but a tail *is* a physical Duration, and reduces to one — one name per
    thing.
    """
    mo = int(years) * 12 + int(months)
    d = int(weeks) * 7 + int(days)
    tail = Duration(rat(hours) * 3600 + rat(minutes) * 60 + rat(seconds))
    if mo == 0 and d == 0:
        return tail
    return CalDuration(mo, d, tail)


def from_iso(s: str):
    """Parse an ISO-8601 duration into a Duration or CalDuration."""
    m = _ISO_RE.match(s.strip())
    if not m:
        raise ValueError(f"bad ISO-8601 duration {s!r}")
    g = {k: (rat(v) if v is not None else 0) for k, v in m.groupdict().items()
         if k != "sign"}
    out = caldur(years=g["y"], months=g["mo"], weeks=g["w"], days=g["d"],
                 hours=g["h"], minutes=g["mi"], seconds=g["s"])
    if m.group("sign") == "-":
        out = (-out if isinstance(out, Duration)
               else CalDuration(-out.months, -out.days, -out.secs))
    return out


# ---------------------------------------------------------------------------
# Anchored nominal steps: "1 month starting 2022-09-11"


@dataclass(frozen=True)
class CalSpan:
    """A nominal step pinned to an anchor: a *symbolic* interval.

    Anchoring a physical step needs nothing new — ``Duration.at(t)`` is a
    Span, already canonical. A nominal step is different, for exactly the
    reason Cells are (§5): "one month from 2022-09-11" is 30 days here, 31
    days elsewhere in the year, and 30 days ± an hour in a zone that
    springs forward in between. Baking today's tzdata and leap table into
    the name would make the name a moving target, so the name stays
    symbolic and ``span()`` does the resolving, stamped with
    ``resolution_versions()``.

    Cells cover only intervals the calendar has a word for; this covers the
    rest ("a month from the 11th", "90 days from signing", "a fortnight").
    """

    anchor: Fraction
    step: CalDuration
    zone: str = "UTC"

    def __post_init__(self):
        object.__setattr__(self, "anchor", _t(self.anchor))
        if not isinstance(self.step, CalDuration):
            raise TypeError(
                "an anchored physical step is just a Span — use Duration.at()"
            )

    def end(self, fold: Optional[int] = None) -> Instant:
        return self.step.resolve(self.anchor, self.zone, fold)

    def span(self, fold: Optional[int] = None) -> Span:
        """Resolve to the physical Span (leap table + tzdata dependent)."""
        return self.step.span(self.anchor, self.zone, fold)

    @property
    def duration(self) -> Duration:
        """What this nominal step is actually worth, here."""
        return self.step.seconds_at(self.anchor, self.zone)

    def text(self) -> str:
        body = f"{self.step.text()}@{fmt(self.anchor)}"
        return body if self.zone == "UTC" else f"{body}!{self.zone}"

    def __repr__(self):
        return f"CalSpan[{self.step.iso} @ {fmt(self.anchor)} {self.zone}]"


def cal_span(anchor, step, zone: str = "UTC"):
    """Anchor a step. Physical steps give a Span, nominal ones a CalSpan."""
    if isinstance(step, Duration):
        return step.at(anchor)
    return CalSpan(_t(anchor), step, zone)


def _cal_at(self, anchor, zone: str = "UTC") -> CalSpan:
    """The symbolic interval this nominal step covers from an anchor."""
    return CalSpan(_t(anchor), self, zone)


CalDuration.at = _cal_at
