"""Hypothesis property tests over ℚ."""

from fractions import Fraction as F

from hypothesis import given, settings
from hypothesis import strategies as st

import intervalclock as ic

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


# The boolean-algebra properties below run without a deadline. Two phase
# classes with co-prime periods intersect over their rational lcm, so the
# result honestly carries hundreds of arcs and takes a few hundred
# milliseconds to build. That is exactness costing what exactness costs;
# timing it would only make these tests flaky on a loaded machine.
@settings(max_examples=60, deadline=None)
@given(phases, phases)
def test_subset_agrees_with_algebra(a, b):
    assert subset(a, b) == (intersect(a, complement(b)) is NEVER)


@settings(max_examples=40, deadline=None)
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


@settings(max_examples=60, deadline=None)
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


# --- durations: the canonical step (§2.5) ----------------------------------

steps = st.builds(ic.duration, rationals)
anchors = st.integers(min_value=0, max_value=2_000_000_000)


@given(steps)
def test_step_names_round_trip(d):
    assert parse(name(d)) == d
    assert decode(encode(d)) == d
    assert name(decode(encode(d))) == name(d)


@given(rationals_pos, rationals, rationals)
def test_grid_brackets_every_instant(step, phi, t):
    g = ic.duration(step).grid(phi)
    lo = g.floor(t)
    assert lo <= t < lo + step
    assert g.slot_at(t).contains(t)
    assert g.slot(g.index(t)) == g.slot_at(t)


@given(rationals_pos, rationals, st.integers(min_value=2, max_value=5))
def test_grid_siblings_partition_time(step, phi, m):
    cls = ic.duration(step).grid(phi).classes(m)
    for i, a in enumerate(cls):
        for b in cls[i + 1:]:
            assert intersect(a, b) is NEVER or intersect(a, b) == NEVER
    merged = cls[0]
    for c in cls[1:]:
        merged = union(merged, c)
    assert merged == ic.ALWAYS


@given(st.integers(min_value=1, max_value=48), anchors)
def test_month_steps_are_monotone(n, anchor):
    # Nominal steps have no fixed length, but they never run backwards.
    a = ic.caldur(months=n).resolve(anchor).t
    b = ic.caldur(months=n + 1).resolve(anchor).t
    assert a < b


@given(anchors)
def test_a_civil_day_is_86400_or_86401_seconds(anchor):
    assert ic.caldur(days=1).seconds_at(anchor) in (86400, 86401)


@given(phases, rationals, rationals)
def test_translation_is_a_group_action(cls, a, b):
    assert ic.shift(ic.shift(cls, a), b) == ic.shift(cls, a + b)
    assert ic.shift(cls, 0) == cls
    assert ic.shift(cls, cls.period) == cls          # invariant under P
    assert ic.shift(ic.shift(cls, a), -a) == cls


@given(phases, rationals, rationals)
def test_translation_moves_membership_with_it(cls, d, t):
    assert contains(ic.shift(cls, d), t + d) == contains(cls, t)
