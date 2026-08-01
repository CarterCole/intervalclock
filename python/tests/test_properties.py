"""Hypothesis property tests over ℚ."""

from fractions import Fraction as F

from hypothesis import given, settings
from hypothesis import strategies as st

from intervalclock import (
    NEVER,
    complement,
    contains,
    decode,
    encode,
    intersect,
    name,
    parse,
    phase,
    pset,
    reduce,
    subset,
    union,
)

rationals_pos = st.builds(
    F, st.integers(min_value=1, max_value=60), st.integers(min_value=1, max_value=12)
)
rationals = st.builds(
    F, st.integers(min_value=-300, max_value=300), st.integers(min_value=1, max_value=12)
)
phases = st.builds(
    lambda w, m, k, d: phase(w, m, k=k, delta=d),
    rationals_pos,
    st.integers(min_value=2, max_value=6),
    st.integers(min_value=0, max_value=11),
    rationals,
)


@given(phases)
def test_reduce_idempotent(p):
    assert reduce(p) == reduce(reduce(p))


@given(phases)
def test_text_and_binary_roundtrip(p):
    assert parse(name(p)) == p
    assert decode(encode(p)) == p


@given(rationals_pos, st.integers(2, 6), st.integers(0, 11), rationals)
def test_redundant_inputs_same_bytes(w, m, k, d):
    # L(w,m,k,δ) = L(w,m,0,δ+kw): same set ⇒ identical ID bytes.
    assert encode(phase(w, m, k=k, delta=d)) == encode(phase(w, m, delta=d + k * w))


@settings(max_examples=60)
@given(phases, phases)
def test_subset_agrees_with_algebra(a, b):
    assert subset(a, b) == (intersect(a, complement(b)) is NEVER)


@settings(max_examples=40)
@given(phases, phases, st.data())
def test_boolean_ops_agree_with_membership(a, b, data):
    from intervalclock.rat import rlcm

    L = rlcm(a.period, b.period)
    t = data.draw(
        st.builds(F, st.integers(0, 600), st.integers(1, 8))
    ) % L
    u = union(a, b)
    i = intersect(a, b)
    assert contains(u, t) == (contains(a, t) or contains(b, t))
    assert contains(i, t) == (contains(a, t) and contains(b, t))
    c = complement(a)
    assert contains(c, t) == (not contains(a, t))


@settings(max_examples=60)
@given(phases, phases)
def test_mutual_subset_means_identical_bytes(a, b):
    if subset(a, b) and subset(b, a):
        assert encode(a) == encode(b)


@given(phases, st.integers(1, 8), st.integers(1, 4))
def test_planted_subperiod_found(p, reps, _):
    # Tile p's arcs reps times over reps·P: pset() must find the sub-period.
    P = p.period
    arcs = [((p.phi + i * P) % (reps * P), p.w) for i in range(reps)]
    assert pset(reps * P, arcs) == p
