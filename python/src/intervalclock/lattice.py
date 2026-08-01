"""The divisibility lattice: the "H3-ness" of the system.

Time has no privileged branching factor (7-day weeks vs decimal vs dyadic),
so unlike H3 there is no single God-given hierarchy. The invariant is the
divisibility *lattice*; hierarchies are named chains through it. Two child
axes, both of which partition the parent (children tile the parent, H3-style):

  * decimate — period × c: "every c-th occurrence"
  * duty     — slot ÷ c:   "the c slices of each pulse"

harmonics(x, n) (n | m) is an *ancestor* of x — n× the frequency, same pulse
width; subharmonics are the decimation children.
"""

from __future__ import annotations

from fractions import Fraction

from .core import ALWAYS, Always, PhaseClass, phase
from .rat import rat

__all__ = [
    "children", "parent", "harmonics", "subharmonics", "decimal_states",
    "decimal_grid_class",
]


def children(x, c: int, axis: str = "decimate") -> list[PhaseClass]:
    """Partition x into c children along the given axis."""
    if not isinstance(c, int) or c < 2:
        raise ValueError("branching factor c must be an integer ≥ 2")
    if isinstance(x, Always):
        # The m-ary decimation children of ALWAYS with slot w are the states
        # of a w-clock; callers use decimal_states()/phase() for that.
        raise ValueError(
            "ALWAYS has no unique children — pick a slot width via phase(w, c)"
        )
    if not isinstance(x, PhaseClass):
        raise TypeError("children() is defined on phase classes")
    if axis == "decimate":
        P = x.period
        return [phase(x.w, x.m * c, phi=(x.phi + i * P)) for i in range(c)]
    if axis == "duty":
        wc = x.w / c
        return [phase(wc, x.m * c, phi=(x.phi + i * wc)) for i in range(c)]
    raise ValueError("axis must be 'decimate' or 'duty'")


def parent(x: PhaseClass, c: int, axis: str = "decimate"):
    """The parent of which x is one of c children along the given axis."""
    if not isinstance(x, PhaseClass):
        raise TypeError("parent() is defined on phase classes")
    if not isinstance(c, int) or c < 2:
        raise ValueError("branching factor c must be an integer ≥ 2")
    if x.m % c:
        raise ValueError(f"m={x.m} is not divisible by c={c}")
    mp = x.m // c
    if axis == "decimate":
        if mp == 1:
            return ALWAYS
        return phase(x.w, mp, phi=x.phi % (x.w * mp))
    if axis == "duty":
        wp = x.w * c
        if mp == 1:
            return ALWAYS
        return phase(wp, mp, phi=(x.phi // wp) * wp % (wp * mp))
    raise ValueError("axis must be 'decimate' or 'duty'")


def harmonics(x: PhaseClass, n: int):
    """n-th harmonic: same pulse width, n× frequency. Requires n | m.

    The harmonic is an ANCESTOR (superset) of x in the lattice — every pulse
    of x is a pulse of its harmonic. (Sinusoid-style duty-preserving
    harmonics belong to the FFT layer and are not containment-related.)
    """
    if not isinstance(n, int) or n < 1:
        raise ValueError("n must be a positive integer")
    if x.m % n:
        raise ValueError(f"harmonic requires n | m (n={n}, m={x.m})")
    return parent(x, n, axis="decimate") if n > 1 else x


def subharmonics(x: PhaseClass, c: int) -> list[PhaseClass]:
    """The c subharmonics (period × c) — identical to decimation children."""
    return children(x, c, axis="decimate")


def decimal_states(power: int) -> list[PhaseClass]:
    """The 10 states of the decimal grid at slot width 10^power seconds."""
    w = Fraction(10) ** power
    return [phase(w, 10, k=k) for k in range(10)]


def decimal_grid_class(power: int, k: int) -> PhaseClass:
    """State k of the decimal grid at 10^power s (epoch-anchored)."""
    if not 0 <= k < 10:
        raise ValueError("decimal grid state must be 0–9")
    return phase(Fraction(10) ** power, 10, k=k)
