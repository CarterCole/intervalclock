"""The canonical phase-class algebra.

The atom is Φ(w, m, φ) = ⋃ₙ [φ + nP, φ + nP + w) with P = w·m: one pulse of
width w per period P, anchored at epoch phase φ ∈ [0, P). Every periodic set
the protocol can name reduces to exactly one canonical object here:

  * PhaseClass — the atom (m ≥ 2)
  * PSet       — closure under boolean ops: disjoint arcs on the circle ℝ/P,
                 period minimized
  * ALWAYS / NEVER — the degenerate top and bottom
  * Span, Windowed — one-shot support and (Span × periodic) composites

User-facing parameters (w, m, state k, offset δ) reduce by the identities
L(w,m,k,δ) = L(w,m,0,δ+kw) and δ ≡ δ mod P, so "offsets that exceed the
period" are a non-issue by construction.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from fractions import Fraction
from typing import Iterator, Optional, Union

from .rat import divides, fmt, rat, rgcd, rlcm
from .timescale import Instant

__all__ = [
    "ALWAYS", "NEVER", "Always", "Never", "PhaseClass", "PSet", "Span",
    "Windowed", "TimeSet", "phase", "pset", "span", "windowed",
    "from_frequency", "reduce", "contains", "subset", "intersect", "union",
    "complement", "next_after", "prev_before", "occurrences", "state_at",
    "complexity",
]


def _t(x) -> Fraction:
    return x.t if isinstance(x, Instant) else rat(x)


# ---------------------------------------------------------------------------
# Types


@dataclass(frozen=True)
class Always:
    """All of time. The root of every hierarchy."""

    def contains(self, t) -> bool:
        return True

    def __repr__(self):
        return "ALWAYS"


@dataclass(frozen=True)
class Never:
    """The empty set."""

    def contains(self, t) -> bool:
        return False

    def __repr__(self):
        return "NEVER"


ALWAYS = Always()
NEVER = Never()


@dataclass(frozen=True)
class Span:
    """Half-open one-shot interval [start, end). Not periodic."""

    start: Fraction
    end: Fraction

    def __post_init__(self):
        object.__setattr__(self, "start", rat(self.start))
        object.__setattr__(self, "end", rat(self.end))
        if not self.start < self.end:
            raise ValueError("span requires start < end")

    @property
    def duration(self) -> Fraction:
        return self.end - self.start

    def contains(self, t) -> bool:
        return self.start <= _t(t) < self.end

    def __repr__(self):
        return f"Span[{fmt(self.start)}, {fmt(self.end)})"


@dataclass(frozen=True)
class PhaseClass:
    """Φ(w, m, φ): one pulse of width w per period P = w·m, forever.

    Use phase() to construct — it applies the canonical reduction. The m
    siblings at fixed (w, m) partition all of time (H3: children tile the
    parent).
    """

    w: Fraction
    m: int
    phi: Fraction

    def __post_init__(self):
        object.__setattr__(self, "w", rat(self.w))
        object.__setattr__(self, "phi", rat(self.phi))
        if self.w <= 0:
            raise ValueError("slot width w must be positive")
        if not isinstance(self.m, int) or self.m < 2:
            raise ValueError("modulus m must be an integer ≥ 2 (m=1 is ALWAYS)")
        if not 0 <= self.phi < self.period:
            raise ValueError("phi must lie in [0, P); use phase() to normalize")

    @property
    def period(self) -> Fraction:
        return self.w * self.m

    @property
    def state(self) -> Optional[int]:
        """Display sugar: k such that φ = k·w, when φ is on the w-grid."""
        q = self.phi / self.w
        return int(q) if q.denominator == 1 else None

    def contains(self, t) -> bool:
        return (_t(t) - self.phi) % self.period < self.w

    def __repr__(self):
        s = self.state
        tail = f" (state {s} of {self.m})" if s is not None else ""
        return f"Φ[w={fmt(self.w)}s · m={self.m} · φ={fmt(self.phi)}s]{tail}"


@dataclass(frozen=True)
class PSet:
    """Period P with disjoint, non-adjacent arcs (start, width) on ℝ/P.

    The closure of phase classes under boolean operations. Use pset() to
    construct — it merges arcs, minimizes the period, and collapses to
    PhaseClass / ALWAYS / NEVER where possible. A single-arc PSet survives
    only when P / width is not an integer ≥ 2 (else it *is* a PhaseClass).
    """

    period: Fraction
    arcs: tuple[tuple[Fraction, Fraction], ...]

    def contains(self, t) -> bool:
        r = _t(t) % self.period
        for s, wd in self.arcs:
            if s <= r < s + wd:
                return True
            if s + wd > self.period and r < (s + wd) - self.period:  # wraps
                return True
        return False

    def __repr__(self):
        a = ",".join(f"[{fmt(s)}+{fmt(w)})" for s, w in self.arcs)
        return f"PSet[P={fmt(self.period)}s · {a}]"


@dataclass(frozen=True)
class Windowed:
    """(Span × periodic class): a phase class restricted to a support range.

    A time range + an interval describes a pure sinusoid perfectly: the
    class fixes period and phase alignment (eternal), the span fixes
    support. Amplitude is measurement data, not identity — it never enters
    the name. Dropping the span "extends the signal forever".
    """

    support: Span
    cls: Union[PhaseClass, PSet]

    def contains(self, t) -> bool:
        return self.support.contains(t) and self.cls.contains(t)

    def __repr__(self):
        return f"Windowed[{self.support!r} × {self.cls!r}]"


TimeSet = Union[Always, Never, Span, PhaseClass, PSet, Windowed, Instant]


# ---------------------------------------------------------------------------
# Constructors (canonical reduction happens here)


def phase(w, m: int, phi=0, k: int = 0, delta=0):
    """Canonical Φ constructor from user-facing (w, m, φ | state k, offset δ).

    Reduction: φ_canonical = (φ + δ + k·w) mod P. m = 1 collapses to ALWAYS.
    """
    w = rat(w)
    if w <= 0:
        raise ValueError("slot width w must be positive")
    if not isinstance(m, int) or m < 1:
        raise ValueError("modulus m must be a positive integer")
    if m == 1:
        return ALWAYS
    P = w * m
    return PhaseClass(w, m, (rat(phi) + rat(delta) + k * w) % P)


def from_frequency(hz, duty=Fraction(1, 2), phi=0):
    """A class from a frequency: P = 1/hz, pulse width duty·P."""
    hz, duty = rat(hz), rat(duty)
    if hz <= 0 or not 0 < duty < 1:
        raise ValueError("need hz > 0 and 0 < duty < 1")
    P = 1 / hz
    w = P * duty
    if not divides(w, P):
        # P/w not integral: a one-arc PSet, still canonical.
        return pset(P, [(rat(phi) % P, w)])
    return phase(w, int(P / w), phi=rat(phi) % P)


def span(start, end) -> Span:
    return Span(rat(start), rat(end))


def windowed(support: Span, cls):
    """Compose support × class, normalizing degenerate cases."""
    cls = reduce(cls)
    if cls is ALWAYS:
        return support
    if cls is NEVER:
        return NEVER
    if not isinstance(cls, (PhaseClass, PSet)):
        raise TypeError("windowed() takes a periodic class")
    # Empty composite → NEVER: no pulse intersects the support.
    first = _next_pulse(cls, support.start, strict=False)
    covering = _pulse_covering(cls, support.start)
    if covering is None and (first is None or first[0] >= support.end):
        return NEVER
    return Windowed(support, cls)


# --- circle-set machinery ---------------------------------------------------
# A periodic set at period L is a list of disjoint linear segments [a, b)
# within [0, L), with wraparound handled at the circle boundary.


def _segments(P: Fraction, arcs) -> list[tuple[Fraction, Fraction]]:
    """Arcs (start, width) on circle P → disjoint sorted segments in [0, P)."""
    segs = []
    for s, wd in arcs:
        s = rat(s) % P
        wd = rat(wd)
        if wd <= 0:
            continue
        if wd >= P:
            return [(Fraction(0), P)]
        e = s + wd
        if e <= P:
            segs.append((s, e))
        else:
            segs.append((s, P))
            segs.append((Fraction(0), e - P))
    return _merge(segs)


def _merge(segs):
    segs = sorted(segs)
    out = []
    for a, b in segs:
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return [tuple(x) for x in out]


def _circle_arcs(P: Fraction, segs):
    """Disjoint sorted segments in [0, P) → circular arcs, merging across 0."""
    segs = _merge(segs)
    if not segs:
        return []
    if segs == [(Fraction(0), P)]:
        return [(Fraction(0), P)]  # full circle; caller collapses to ALWAYS
    if len(segs) >= 2 and segs[0][0] == 0 and segs[-1][1] == P:
        first, last = segs[0], segs[-1]
        segs = segs[1:-1]
        segs.append((last[0], last[1] + (first[1] - first[0])))  # wrap arc
    return [(a, b - a) for a, b in segs]


def _lift_arcs(x, L: Fraction) -> list[tuple[Fraction, Fraction]]:
    """Represent periodic x as arcs on the circle of circumference L."""
    if isinstance(x, PhaseClass):
        P, arcs = x.period, [(x.phi, x.w)]
    elif isinstance(x, PSet):
        P, arcs = x.period, list(x.arcs)
    else:
        raise TypeError(f"not a periodic class: {x!r}")
    n = L / P
    if n.denominator != 1:
        raise ValueError("lift target must be a multiple of the period")
    return [((s + i * P) % L, wd) for s, wd in arcs for i in range(int(n))]


def _minimize_period(P: Fraction, arcs):
    """Smallest P' | P under which the arc pattern is shift-invariant."""
    if not arcs:
        return P, arcs
    key = set(arcs)
    n_arcs = len(arcs)
    for n in range(n_arcs, 1, -1):
        if n_arcs % n:
            continue
        Pp = P / n
        if {((s + Pp) % P, wd) for s, wd in arcs} == key:
            kept = sorted((s, wd) for s, wd in arcs if s < Pp)
            return Pp, kept
    return P, sorted(arcs)


def pset(P, arcs):
    """Canonical periodic-set constructor: merge, minimize, collapse."""
    P = rat(P)
    if P <= 0:
        raise ValueError("period must be positive")
    segs = _segments(P, arcs)
    if not segs:
        return NEVER
    if segs == [(Fraction(0), P)]:
        return ALWAYS
    carcs = _circle_arcs(P, segs)
    P, carcs = _minimize_period(P, carcs)
    carcs = tuple(sorted((s % P, wd) for s, wd in carcs))
    if len(carcs) == 1:
        s, wd = carcs[0]
        q = P / wd
        if q.denominator == 1 and int(q) >= 2:
            return PhaseClass(wd, int(q), s)
    return PSet(P, carcs)


def reduce(x):
    """Idempotent canonicalization: equal sets ⇒ equal objects."""
    if isinstance(x, (Always, Never, Span, Instant)):
        return x
    if isinstance(x, PhaseClass):
        return phase(x.w, x.m, phi=x.phi)
    if isinstance(x, PSet):
        return pset(x.period, x.arcs)
    if isinstance(x, Windowed):
        return windowed(x.support, x.cls)
    raise TypeError(f"not a TimeSet: {x!r}")


# ---------------------------------------------------------------------------
# Membership, occurrences


def contains(x, t) -> bool:
    return x.contains(t)


def _pulses(x):
    """(P, [(start, width)]) of a periodic class."""
    if isinstance(x, PhaseClass):
        return x.period, [(x.phi, x.w)]
    if isinstance(x, PSet):
        return x.period, list(x.arcs)
    raise TypeError(f"not periodic: {x!r}")


def _next_pulse(x, t, strict=True):
    """Earliest pulse (start, end) with start > t (or ≥ t when not strict)."""
    t = _t(t)
    P, arcs = _pulses(x)
    best = None
    for s, wd in arcs:
        start = s + ((t - s) // P) * P  # latest start ≤ t
        while (start <= t) if strict else (start < t):
            start += P
        if best is None or start < best[0]:
            best = (start, start + wd)
    return best


def _prev_pulse(x, t, strict=True):
    """Latest pulse (start, end) with start < t (or ≤ t when not strict)."""
    t = _t(t)
    P, arcs = _pulses(x)
    best = None
    for s, wd in arcs:
        start = s + ((t - s) // P) * P + P  # earliest start > t (or = t)
        while (start >= t) if strict else (start > t):
            start -= P
        if best is None or start > best[0]:
            best = (start, start + wd)
    return best


def _pulse_covering(x, t):
    """The pulse containing t, if any."""
    p = _prev_pulse(x, t, strict=False)
    if p and p[0] <= _t(t) < p[1]:
        return p
    return None


def next_after(x, t) -> Optional[Span]:
    """The next occurrence (pulse span) starting strictly after t.

    ALWAYS/NEVER have no discrete occurrences → None.
    """
    if isinstance(x, (Always, Never)):
        return None
    if isinstance(x, Instant):
        return None
    if isinstance(x, Span):
        return x if x.start > _t(t) else None
    if isinstance(x, Windowed):
        probe = max(_t(t), x.support.start - 1)  # cheap fast-forward
        while True:
            p = _next_pulse(x.cls, probe)
            if p is None or p[0] >= x.support.end:
                return None
            if p[1] > x.support.start and p[0] > _t(t):
                a, b = max(p[0], x.support.start), min(p[1], x.support.end)
                if a < b and p[0] > _t(t):
                    return Span(p[0], p[1])
            probe = p[0]
    p = _next_pulse(x, t)
    return Span(*p) if p else None


def prev_before(x, t) -> Optional[Span]:
    """The latest occurrence starting strictly before t."""
    if isinstance(x, (Always, Never, Instant)):
        return None
    if isinstance(x, Span):
        return x if x.start < _t(t) else None
    if isinstance(x, Windowed):
        p = _prev_pulse(x.cls, t)
        while p is not None and p[0] >= x.support.end:
            p = _prev_pulse(x.cls, p[0])
        if p is None or p[1] <= x.support.start:
            return None
        return Span(*p)
    p = _prev_pulse(x, t)
    return Span(*p) if p else None


def occurrences(x, within: Span) -> Iterator[Span]:
    """All occurrences whose start lies in [within.start, within.end)."""
    if isinstance(x, (Always, Never, Instant)):
        return
    if isinstance(x, Span):
        if within.start <= x.start < within.end:
            yield x
        return
    cls = x.cls if isinstance(x, Windowed) else x
    first = _next_pulse(cls, within.start, strict=False)
    while first is not None and first[0] < within.end:
        s = Span(*first)
        if not isinstance(x, Windowed) or (
            s.start < x.support.end and s.end > x.support.start
        ):
            yield s
        first = _next_pulse(cls, first[0])


def state_at(w, m: int, t, err=0):
    """Which state(s) of the (w, m) epoch-anchored grid is t in?

    Returns one state, or two when t is within err of a slot boundary — NTP
    sync error makes the current state genuinely ambiguous near boundaries,
    and this surfaces it rather than hiding it.
    """
    w, t, err = rat(w), _t(t), rat(err)
    slot = t // w
    states = [int(slot % m)]
    if err > 0:
        if t - slot * w < err:  # within err of the boundary below
            states.insert(0, int((slot - 1) % m))
        if (slot + 1) * w - t < err:  # within err of the boundary above
            states.append(int((slot + 1) % m))
    seen = []
    for s in states:
        if s not in seen:
            seen.append(s)
    return seen


# ---------------------------------------------------------------------------
# Boolean algebra (closed on the periodic family) and the lattice


def _as_periodic(x):
    if isinstance(x, (PhaseClass, PSet)):
        return x
    raise TypeError(
        f"boolean algebra is defined on periodic classes (got {x!r}); "
        "intersect a Span via windowed()"
    )


def intersect(a, b):
    if a is NEVER or b is NEVER:
        return NEVER
    if a is ALWAYS:
        return reduce(b)
    if b is ALWAYS:
        return reduce(a)
    if isinstance(a, Span) and isinstance(b, Span):
        s, e = max(a.start, b.start), min(a.end, b.end)
        return Span(s, e) if s < e else NEVER
    if isinstance(a, Span):
        return windowed(a, _as_periodic(b))
    if isinstance(b, Span):
        return windowed(b, _as_periodic(a))
    if isinstance(a, Windowed) or isinstance(b, Windowed):
        aw = a if isinstance(a, Windowed) else None
        bw = b if isinstance(b, Windowed) else None
        if aw and bw:
            sp = intersect(aw.support, bw.support)
            if sp is NEVER:
                return NEVER
            return windowed(sp, intersect(aw.cls, bw.cls))
        wnd, other = (aw, b) if aw else (bw, a)
        return windowed(wnd.support, intersect(wnd.cls, _as_periodic(other)))
    a, b = _as_periodic(a), _as_periodic(b)
    L = rlcm(a.period, b.period)
    sa = _merge(_segments(L, _lift_arcs(a, L)))
    sb = _merge(_segments(L, _lift_arcs(b, L)))
    out = []
    for (a1, a2), (b1, b2) in itertools.product(sa, sb):
        lo, hi = max(a1, b1), min(a2, b2)
        if lo < hi:
            out.append((lo, hi))
    return pset(L, _circle_arcs(L, _merge(out)))


def union(a, b):
    if a is ALWAYS or b is ALWAYS:
        return ALWAYS
    if a is NEVER:
        return reduce(b)
    if b is NEVER:
        return reduce(a)
    a, b = _as_periodic(a), _as_periodic(b)
    L = rlcm(a.period, b.period)
    segs = _merge(
        _segments(L, _lift_arcs(a, L)) + _segments(L, _lift_arcs(b, L))
    )
    return pset(L, _circle_arcs(L, segs))


def complement(x):
    if x is ALWAYS:
        return NEVER
    if x is NEVER:
        return ALWAYS
    x = _as_periodic(x)
    P, _ = _pulses(x)
    segs = _merge(_segments(P, _pulses(x)[1]))
    out, cursor = [], Fraction(0)
    for a, b in segs:
        if cursor < a:
            out.append((cursor, a))
        cursor = b
    if cursor < P:
        out.append((cursor, P))
    return pset(P, _circle_arcs(P, out))


def subset(a, b) -> bool:
    """Exact A ⊆ B.

    Phase × Phase uses the closed-form orbit predicate; the general case
    falls back to intersect(a, ¬b) = ∅ (exact over ℚ).
    """
    if a is NEVER or b is ALWAYS:
        return True
    if b is NEVER:
        return a is NEVER
    if a is ALWAYS:
        return b is ALWAYS
    if isinstance(a, Span) and isinstance(b, Span):
        return b.start <= a.start and a.end <= b.end
    if isinstance(a, PhaseClass) and isinstance(b, PhaseClass):
        return _phase_subset(a, b)
    if isinstance(a, Windowed):
        inner = b.cls if isinstance(b, Windowed) else b
        sup_ok = (
            subset(a.support, b.support) if isinstance(b, Windowed) else True
        )
        if isinstance(b, Span):
            # every pulse of a within its support must land inside b
            return subset(a.support, b)
        return sup_ok and subset(a.cls, inner)
    if isinstance(a, (PhaseClass, PSet)) and isinstance(b, (PhaseClass, PSet)):
        return intersect(a, complement(b)) is NEVER
    if isinstance(a, Span) and isinstance(b, (PhaseClass, PSet)):
        cov = _pulse_covering(b, a.start)
        return cov is not None and a.end <= cov[1]
    return False


def _phase_subset(a: PhaseClass, b: PhaseClass) -> bool:
    """A ⊆ B ⟺ w₁ ≤ w₂ ∧ ∀r ∈ orbit: (r − φ₂) mod P₂ ≤ w₂ − w₁."""
    if a.w > b.w:
        return False
    g = rgcd(a.period, b.period)
    count = int(b.period / g)
    slack = b.w - a.w
    r = a.phi % b.period
    step = g
    for _ in range(count):
        if (r - b.phi) % b.period > slack:
            return False
        r = (r + step) % b.period
    return True


def complexity(x) -> int:
    """Rough cost measure: arc count × period bit-size. Boolean combinations
    of unrelated periods blow up — check this before iterating."""
    if isinstance(x, (Always, Never, Span, Instant)):
        return 1
    if isinstance(x, Windowed):
        return complexity(x.cls)
    P, arcs = _pulses(x)
    return max(1, len(arcs)) * (P.numerator.bit_length() + P.denominator.bit_length())
