import math
from fractions import Fraction as F

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from intervalclock import (
    ALWAYS,
    DEFAULT_PHASE_QUANTUM,
    FFTComponent,
    Span,
    alias_class,
    alias_freq,
    bin_identity,
    decode,
    encode,
    from_fft,
    from_url,
    name,
    nyquist,
    parse,
    phase,
    quantize_phase_turns,
    to_url,
)

# The §9 worked example: 7.5 Hz with θ = π/3 (= 1/6 turn) at t₀ = 0.
# fs = 30, N = 8, k = 2 gives f_k = 2·30/8 = 15/2.
GOLDEN_BIN = dict(fs=30, N=8, k=2, t0=0, theta_turns=F(1, 6))


def test_section_9_golden_mapping():
    cls = bin_identity(**GOLDEN_BIN)
    assert cls == phase(F(1, 15), 2, phi=F(7, 90))
    assert name(cls) == "ic1:c:w=1/15;m=2;phi=7/90"


def test_golden_pulses_are_centered_on_the_peaks():
    # cos(2π·7.5·t + π/3) = 1 exactly at t = 1/9 + n·2/15.
    cls = bin_identity(**GOLDEN_BIN)
    for n in range(-3, 4):
        peak = F(1, 9) + n * F(2, 15)
        assert cls.contains(peak)
        # …and the trough half a period away is outside.
        assert not cls.contains(peak + F(1, 15))


def test_bin_identity_is_invariant_under_whole_period_shifts():
    cls = bin_identity(**GOLDEN_BIN)
    shifted = bin_identity(**{**GOLDEN_BIN, "t0": F(2, 15) * 4})
    assert shifted == cls


# --- from_fft ---------------------------------------------------------------


def _spectrum(N, k, amp, theta_turns):
    """A synthetic spectrum with all energy in bin k: X[k] = (N/2)·A·e^{iθ}."""
    X = [complex(0, 0)] * N
    ang = 2 * math.pi * float(theta_turns)
    X[k] = complex(N / 2 * amp * math.cos(ang), N / 2 * amp * math.sin(ang))
    return X


def test_from_fft_recovers_amplitude_and_quantized_phase():
    comps = from_fft(_spectrum(8, 2, 1.5, F(1, 6)), fs=30, t0=0)
    assert len(comps) == 5  # bins 0..N//2
    c = comps[2]
    assert c.freq == F(15, 2)
    assert c.period == F(2, 15)
    assert c.A == pytest.approx(1.5)
    # The estimate is snapped to the declared quantum, so it is *near* 1/6
    # but deliberately not equal to it — 1/6 is not a dyadic rational.
    assert c.theta_turns == F(2796203, 2**24)
    assert c.theta_turns != F(1, 6)
    assert abs(c.theta_turns - F(1, 6)) < DEFAULT_PHASE_QUANTUM


def test_from_fft_dc_bin_is_always_with_a_signed_amplitude():
    X = [complex(-4.0, 0)] * 1 + [complex(0, 0)] * 7
    c = from_fft(X, fs=10, t0=0)[0]
    assert c.is_dc
    assert c.A == -0.5  # signed mean: −4/8
    assert c.theta_turns == 0
    assert c.identity is ALWAYS
    # ALWAYS ∩ capture span is just the span.
    assert c.windowed == Span(F(0), F(4, 5))


def test_from_fft_nyquist_bin_phase_is_binary():
    pos = from_fft(_spectrum(8, 4, 0, 0)[:4] + [complex(8.0, 0)], fs=10, N=8)
    assert pos[4].is_nyquist
    assert pos[4].theta_turns == 0
    assert pos[4].A == 1.0
    neg = from_fft([complex(0, 0)] * 4 + [complex(-8.0, 0)], fs=10, N=8)
    assert neg[4].theta_turns == F(1, 2)
    assert neg[4].A == 1.0  # magnitude only; the sign lives in the phase


def test_odd_n_has_no_nyquist_bin():
    comps = from_fft([complex(0, 0)] * 9, fs=10, t0=0)
    assert [c.k for c in comps] == [0, 1, 2, 3, 4]
    assert not any(c.is_nyquist for c in comps)


def test_from_fft_accepts_a_half_spectrum_when_n_is_given():
    full = from_fft(_spectrum(8, 2, 1.0, F(1, 8)), fs=30)
    half = from_fft(_spectrum(8, 2, 1.0, F(1, 8))[:5], fs=30, N=8)
    assert full == half


def test_from_fft_rejects_a_short_spectrum():
    with pytest.raises(ValueError):
        from_fft([complex(0, 0)] * 3, fs=10, N=8)


def test_from_samples_matches_from_fft():
    numpy = pytest.importorskip("numpy")
    xs = [math.cos(2 * math.pi * 2 * n / 8 + 0.4) for n in range(8)]
    from intervalclock import from_samples

    assert from_samples(xs, fs=8) == from_fft(numpy.fft.fft(xs), fs=8, N=8)


# --- phase quantization -----------------------------------------------------


def test_quantization_rounds_half_to_even():
    q = F(1, 4)
    assert quantize_phase_turns(F(1, 8), q) == 0  # 0.5 quanta → 0, not 1
    assert quantize_phase_turns(F(3, 8), q) == F(1, 2)  # 1.5 quanta → 2
    assert quantize_phase_turns(F(5, 8), q) == F(1, 2)  # 2.5 quanta → 2


def test_quantization_wraps_negative_phases_into_one_turn():
    assert quantize_phase_turns(F(-3, 8), F(1, 4)) == F(1, 2)
    assert quantize_phase_turns(-0.25, F(1, 4)) == F(3, 4)


def test_quantization_is_deterministic_and_exact():
    theta = math.atan2(0.3, -0.7) / math.tau
    assert quantize_phase_turns(theta) == quantize_phase_turns(theta)
    assert quantize_phase_turns(theta).denominator <= 2**24


def test_quantum_must_be_positive():
    with pytest.raises(ValueError):
        quantize_phase_turns(0.5, 0)


# --- Nyquist and aliasing ---------------------------------------------------


def test_nyquist_is_per_signal():
    assert nyquist(10) == 5
    assert nyquist(F(1, 3)) == F(1, 6)
    with pytest.raises(ValueError):
        nyquist(0)


def test_alias_folding_matches_the_spec_example():
    # 15/2 Hz sampled at 10 Hz → 5/2 Hz, conjugated.
    assert alias_freq(F(15, 2), 10) == F(5, 2)
    folded = alias_class(F(15, 2), 10, t0=0, theta_turns=F(1, 6))
    # Conjugation: θ → −θ, i.e. 1/6 turn → 5/6 turn, at the folded frequency.
    assert folded == bin_identity(fs=10, N=4, k=1, t0=0, theta_turns=F(5, 6))


def test_alias_of_a_multiple_of_the_rate_is_dc():
    assert alias_freq(20, 10) == 0
    assert alias_class(20, 10) is ALWAYS


def test_alias_tie_at_exactly_nyquist_folds_positive():
    # f/fs = 1/2 rounds half-even to 0, so r = +fs/2: no conjugation.
    assert alias_freq(5, 10) == 5
    assert alias_class(5, 10, theta_turns=F(1, 6)) == alias_class(
        5, 10, theta_turns=F(1, 6)
    )
    unconjugated = bin_identity(fs=10, N=2, k=1, t0=0, theta_turns=F(1, 6))
    assert alias_class(5, 10, theta_turns=F(1, 6)) == unconjugated


def test_aliasing_never_exceeds_nyquist():
    for f in [F(1, 7), 3, F(99, 4), 1000]:
        assert alias_freq(f, 10) <= nyquist(10)


# --- the provenance record --------------------------------------------------


def _components():
    return [
        FFTComponent(F(10), 64, 3, F(0), 1.0, F(1, 6)),
        FFTComponent(F(10), 64, 0, F(-7, 3), -0.5, 0),
        FFTComponent(F(10), 64, 32, F(1, 3), 0.25, F(1, 2)),
        FFTComponent(F(1, 3), 9, 4, F(10**9), 1e-9, F(2796203, 2**24)),
    ]


@pytest.mark.parametrize("c", _components(), ids=lambda c: f"k{c.k}/N{c.N}")
def test_record_roundtrips(c):
    assert parse(name(c)) == c
    assert decode(encode(c)) == c
    assert from_url(to_url(c)) == c


def test_amplitude_is_data_not_identity():
    quiet = FFTComponent(F(10), 64, 3, F(0), 1e-12, F(1, 6))
    loud = FFTComponent(F(10), 64, 3, F(0), 5.0, F(1, 6))
    assert quiet != loud
    assert encode(quiet) != encode(loud)
    # …but they name the same set of time.
    assert quiet.identity == loud.identity
    assert name(quiet.identity) == name(loud.identity)


def test_windowed_projection_is_the_capture_bounded_set():
    c = FFTComponent(F(10), 64, 3, F(0), 1.0, F(1, 6))
    assert c.support == Span(F(0), F(32, 5))
    w = c.windowed
    assert w.support == c.support and w.cls == c.identity
    assert c.contains(F(1, 100)) == w.contains(F(1, 100))
    assert not c.contains(F(100))  # outside the capture


def test_dc_record_has_no_period():
    with pytest.raises(ValueError):
        FFTComponent(F(10), 64, 0, F(0), 1.0, 0).period


def test_records_sort_chronologically_by_capture_start():
    ids = [encode(FFTComponent(F(10), 8, 1, t0, 1.0, 0))
           for t0 in [F(-100), F(-1, 2), F(0), F(99, 7), F(1000)]]
    assert ids == sorted(ids)


def test_one_captures_bins_stay_adjacent():
    a = [encode(c) for c in from_fft([complex(1, 1)] * 8, fs=10, t0=0)]
    later = encode(FFTComponent(F(10), 8, 1, F(5), 1.0, 0))
    assert all(x < later for x in a)


@pytest.mark.parametrize("kwargs", [
    dict(k=33),                                   # k > N//2
    dict(k=0, theta_turns=F(1, 4)),               # DC has no phase
    dict(k=32, theta_turns=F(1, 4)),              # Nyquist θ ∉ {0, 1/2}
    dict(theta_turns=F(5, 4)),                    # θ outside [0, 1)
    dict(theta_turns=-F(1, 4)),
    dict(fs=0),
    dict(N=0),
    dict(A=float("nan")),
    dict(A=float("inf")),
    dict(quantum=0),
])
def test_record_validation(kwargs):
    base = dict(fs=F(10), N=64, k=3, t0=F(0), A=1.0, theta_turns=F(1, 6))
    with pytest.raises(ValueError):
        FFTComponent(**{**base, **kwargs})


@pytest.mark.parametrize("text", [
    "ic1:f:fs=10;N=64;k=3;t0=0;A=3ff0000000000000;th=1/6",       # missing q
    "ic1:f:N=64;fs=10;k=3;t0=0;A=3ff0000000000000;th=1/6;q=1",   # reordered
    "ic1:f:fs=10;N=64;k=3;t0=0;A=3FF0000000000000;th=1/6;q=1",   # uppercase hex
    "ic1:f:fs=10;N=64;k=3;t0=0;A=3ff000000000000;th=1/6;q=1",    # 15 digits
    "ic1:f:fs=10;N=64;k=3;t0=0;A=7ff0000000000000;th=1/6;q=1",   # +inf bits
])
def test_noncanonical_text_is_rejected(text):
    with pytest.raises(ValueError):
        parse(text)


# --- properties -------------------------------------------------------------

rates = st.builds(F, st.integers(1, 96000), st.integers(1, 8))
quanta = st.sampled_from([F(1, 2**24), F(1, 2**10), F(1, 4), F(1, 3)])


@st.composite
def records(draw):
    fs = draw(rates)
    N = draw(st.integers(1, 512))
    k = draw(st.integers(0, N // 2))
    q = draw(quanta)
    if k == 0:
        th = F(0)
    elif N % 2 == 0 and k == N // 2:
        th = draw(st.sampled_from([F(0), F(1, 2)]))
    else:
        th = (draw(st.integers(0, 10**6)) * q) % 1
    return FFTComponent(fs, N, k, draw(st.integers(-10**9, 10**9)),
                        draw(st.floats(-1e6, 1e6)), th, q)


@given(records())
@settings(max_examples=60)
def test_property_roundtrips(c):
    assert parse(name(c)) == c
    assert decode(encode(c)) == c
    assert from_url(to_url(c)) == c


@given(records())
@settings(max_examples=60)
def test_property_identity_ignores_amplitude(c):
    louder = FFTComponent(c.fs, c.N, c.k, c.t0, c.A + 1.0, c.theta_turns,
                          c.quantum)
    assert louder.identity == c.identity


@given(rates, rates)
@settings(max_examples=60)
def test_property_alias_lands_below_nyquist(f, fs):
    assert alias_freq(f, fs) <= nyquist(fs)


@given(rates, rates)
@settings(max_examples=60)
def test_property_folding_is_idempotent(f, fs):
    once = alias_freq(f, fs)
    assert alias_freq(once, fs) == once
