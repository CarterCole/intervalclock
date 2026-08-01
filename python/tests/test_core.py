from fractions import Fraction as F

import pytest

from intervalclock import (
    ALWAYS,
    NEVER,
    PhaseClass,
    PSet,
    Span,
    complement,
    intersect,
    next_after,
    occurrences,
    phase,
    prev_before,
    pset,
    reduce,
    span,
    state_at,
    subset,
    union,
    windowed,
)
from intervalclock.lattice import children, harmonics, parent, subharmonics


def test_users_example_state_2_of_3():
    c = phase(F(1, 3), 3, k=2)
    assert (c.w, c.m, c.phi) == (F(1, 3), 3, F(2, 3))
    assert c.state == 2
    assert c.contains(F(2, 3)) and c.contains(F(5, 6)) and not c.contains(F(1, 3))


def test_siblings_partition_always():
    sibs = [phase(F(1, 3), 3, k=i) for i in range(3)]
    assert union(union(sibs[0], sibs[1]), sibs[2]) is ALWAYS
    for a in sibs:
        for b in sibs:
            if a != b:
                assert intersect(a, b) is NEVER


def test_k_absorbs_into_delta():
    assert phase(F(1, 3), 3, k=2, delta=10) == phase(F(1, 3), 3, delta=10 + F(2, 3))


def test_offset_pathology_normalizes():
    p = phase(F(1, 3), 3, delta=F(10**6) + F(1, 7))
    assert 0 <= p.phi < p.period
    q = phase(F(1, 3), 3, delta=-F(22, 7), k=5)  # negative δ, k ≥ m
    assert 0 <= q.phi < q.period


def test_degeneracies():
    assert phase(5, 1) is ALWAYS
    assert pset(1, []) is NEVER
    assert pset(1, [(0, 2)]) is ALWAYS  # arc covering the whole circle
    assert pset(1, [(0, F(1, 2)), (F(1, 2), F(1, 2))]) is ALWAYS


def test_pset_period_minimization():
    ps = pset(2, [(0, F(1, 4)), (1, F(1, 4))])
    assert isinstance(ps, PhaseClass)
    assert ps.period == 1


def test_one_arc_pset_with_nonintegral_ratio_stays_pset():
    ps = pset(F(3, 2), [(0, 1)])  # P/w = 3/2 ∉ ℤ
    assert isinstance(ps, PSet)


def test_wraparound_arc_merge():
    ps = pset(1, [(F(3, 4), F(1, 2))])  # wraps through 0
    assert ps.contains(F(7, 8)) and ps.contains(F(1, 8)) and not ps.contains(F(1, 2))


def test_coprime_grids_lcm_period():
    a = phase(F(1, 6), 2)  # P = 1/3
    b = phase(F(1, 14), 2)  # P = 1/7
    i = intersect(a, b)
    assert isinstance(i, PSet) and i.period == 1


def test_subset_children_and_harmonics():
    c = phase(F(1, 3), 3, k=2)
    for axis in ("decimate", "duty"):
        kids = children(c, 3, axis=axis)
        for k in kids:
            assert subset(k, c)
        u = kids[0]
        for k in kids[1:]:
            u = union(u, k)
        assert u == c
        assert parent(kids[0], 3, axis=axis) == c
    h = harmonics(phase(F(1, 3), 6), 3)
    assert subset(phase(F(1, 3), 6), h)
    assert subharmonics(c, 2) == children(c, 2)


def test_subset_non_divisible_orbit_case():
    # Wide-window B swallowing a small orbit despite P₂ ∤ P₁.
    a = phase(F(1, 10), 30)  # P = 3
    b = phase(F(9, 10), 2)  # P = 9/5; orbit of A's starts mod 9/5 must fit
    got = subset(a, b)
    ref = intersect(a, complement(b)) is NEVER
    assert got == ref
    # near-miss variant
    a2 = phase(F(1, 10), 30, delta=F(1, 2))
    assert subset(a2, b) == (intersect(a2, complement(b)) is NEVER)


def test_next_prev_occurrences():
    c = phase(F(1, 3), 3, k=2)
    assert next_after(c, 0) == Span(F(2, 3), 1)
    assert prev_before(c, 0) == Span(-F(1, 3), 0)
    occ = list(occurrences(c, span(0, 3)))
    assert len(occ) == 3
    assert occ[0].start == F(2, 3)


def test_windowed_pure_tone():
    f = phase(F(1, 15), 2, phi=F(7, 90))  # 7.5 Hz positive half-cycles
    w = windowed(span(0, 1), f)
    assert w.contains(F(1, 9))
    assert not w.contains(F(1, 9) + 5)
    assert subset(w, f)  # dropping the range extends the signal forever
    assert subset(w, span(0, 1))
    assert windowed(span(0, F(1, 100)), phase(F(1, 3), 3, k=2)) is NEVER


def test_state_at_boundary_ambiguity():
    assert state_at(F(1, 3), 3, F(1, 6)) == [0]
    near = F(1, 3) + F(1, 1000)
    assert state_at(F(1, 3), 3, near, err=F(1, 100)) == [0, 1]


def test_reduce_idempotent():
    objs = [
        phase(F(1, 3), 3, k=2),
        pset(2, [(0, F(1, 4)), (1, F(1, 4))]),
        ALWAYS,
        NEVER,
        span(0, 1),
        windowed(span(0, 10), phase(F(1, 3), 3)),
    ]
    for o in objs:
        assert reduce(o) == reduce(reduce(o))


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError):
        phase(0, 3)
    with pytest.raises(ValueError):
        phase(F(-1, 3), 3)
    with pytest.raises(ValueError):
        phase(1, 0)
    with pytest.raises(ValueError):
        span(1, 1)
    with pytest.raises((ValueError, TypeError)):
        phase("pi", 3)  # non-rational string rejected, never approximated
