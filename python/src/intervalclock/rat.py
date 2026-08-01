"""Exact rational arithmetic helpers.

All times, widths, periods, and offsets in intervalclock are exact
``fractions.Fraction`` values of SI seconds. There is no resolution floor:
1/3 s is exact, any rational Hz is exact. (Planck time is a physical
footnote, not a mechanism — see PROTOCOL.md §1.)
"""

from __future__ import annotations

from fractions import Fraction
from math import gcd, lcm
from numbers import Rational

Rat = Fraction


def rat(x) -> Fraction:
    """Coerce to an exact Fraction.

    Accepts int, Fraction, str ("7", "1/3", "0.25"), and float. Floats are
    converted *exactly* (every float is a dyadic rational) — callers who want
    a nicer nearby rational should use ``Fraction.limit_denominator`` first.
    """
    if isinstance(x, Fraction):
        return x
    if isinstance(x, (int, str, Rational)):
        return Fraction(x)
    if isinstance(x, float):
        return Fraction(x)
    raise TypeError(f"cannot interpret {x!r} as a rational")


def rgcd(a: Fraction, b: Fraction) -> Fraction:
    """gcd over ℚ: gcd(a/b, c/d) = gcd(ad, cb) / bd."""
    a, b = rat(a), rat(b)
    return Fraction(
        gcd(a.numerator * b.denominator, b.numerator * a.denominator),
        a.denominator * b.denominator,
    )


def rlcm(a: Fraction, b: Fraction) -> Fraction:
    """lcm over ℚ: lcm(a/b, c/d) = lcm(a, c) / gcd(b, d)."""
    a, b = rat(a), rat(b)
    return Fraction(lcm(a.numerator, b.numerator), gcd(a.denominator, b.denominator))


def divides(small: Fraction, big: Fraction) -> bool:
    """Rational divisibility: small | big  ⟺  big / small ∈ ℤ."""
    q = rat(big) / rat(small)
    return q.denominator == 1


def fmt(q: Fraction) -> str:
    """Canonical text form: lowest terms, '/' only when denominator > 1."""
    q = rat(q)
    if q.denominator == 1:
        return str(q.numerator)
    return f"{q.numerator}/{q.denominator}"


def period_of_hz(hz) -> Fraction:
    """Frequency (Hz) → period (s), exactly."""
    f = rat(hz)
    if f <= 0:
        raise ValueError("frequency must be positive")
    return 1 / f


def hz_of_period(p) -> Fraction:
    p = rat(p)
    if p <= 0:
        raise ValueError("period must be positive")
    return 1 / p
