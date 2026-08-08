"""The FFT layer: naming spectral components (PROTOCOL.md §9).

Bin k of an N-sample capture at rational rate f_s starting at t₀ has exact
frequency f_k = k·f_s/N and period P = N/(k·f_s). Its *eternal* identity is
the positive-half-cycle class — the pulse centered on every peak, as if the
tone continued forever — which is always exactly

    Φ(w = P/2, m = 2, φ = (t₀ − θ_turns·P − P/4) mod P)

A slot width of 1/f_s would fail whenever k ∤ N; the half-cycle form never
does. The mapping is frozen: two implementations given the same provenance
MUST produce the same name.

Amplitude and the declared phase quantum are *measurement data*, not
identity (§2.4). They live on the FFTComponent provenance record (text form
``f:``, binary type 0x8) and never enter the class name; the record's
canonical projections are ``.identity`` (the eternal Φ) and ``.windowed``
(that Φ restricted to the capture span).

Determinism notes, since two implementations must agree bit-for-bit:

  * θ is carried in **turns** as an exact rational, never radians — turns
    keep the whole φ computation inside ℚ.
  * Estimated phases are snapped to a declared quantum before φ is
    computed: n = round_half_even(exact(θ)/q), θ = (n·q) mod 1, all in ℚ.
    Language-level rounding differs (JS Math.round is half-up), so the
    half-even rule is normative.
  * Amplitude uses the naive sqrt(re² + im²), not hypot or fma — the naive
    form is a sequence of correctly-rounded IEEE ops and so is reproducible.
  * atan2 itself is only correctly-rounded up to a ulp or so across libms.
    The quantum absorbs that; the record certifies *the analyzer's*
    estimate, and the identity is exact given the record.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from fractions import Fraction
from typing import Union

from .core import ALWAYS, Always, PhaseClass, Span, phase, windowed
from .rat import rat
from .timescale import MAX_ABS_SECONDS, RangeError

__all__ = [
    "DEFAULT_PHASE_QUANTUM", "FFTComponent", "alias_class", "alias_freq",
    "bin_identity", "from_fft", "from_samples", "nyquist",
    "quantize_phase_turns",
]

# One turn / 2²⁴ ≈ 0.0000000596 turn ≈ 0.02 arcsecond of phase.
DEFAULT_PHASE_QUANTUM = Fraction(1, 2**24)


# --- frequency helpers ------------------------------------------------------


def nyquist(fs) -> Fraction:
    """The per-signal ceiling f_s/2. There is no global ceiling (§1)."""
    f = rat(fs)
    if f <= 0:
        raise ValueError("sample rate must be positive")
    return f / 2


def _fold(f, fs) -> Fraction:
    """Signed alias residue r = f − f_s·round(f/f_s), exactly in ℚ.

    Python's round() on a Fraction is half-even, which is the normative
    tie rule: f = f_s/2 folds to +f_s/2 (n = 0), never to −f_s/2.
    """
    f, s = rat(f), rat(fs)
    if s <= 0:
        raise ValueError("sample rate must be positive")
    return f - s * round(f / s)


def alias_freq(f, fs) -> Fraction:
    """Where frequency f lands after sampling at f_s: |r|, always ≤ f_s/2."""
    return abs(_fold(f, fs))


def alias_class(f, fs, t0=0, theta_turns=0):
    """The class a tone at f is *indistinguishable from* when sampled at f_s.

    Folding past Nyquist conjugates the phase (r < 0 ⇒ θ → −θ); an exact
    multiple of f_s folds to DC, which is ALWAYS.
    """
    r = _fold(f, fs)
    if r == 0:
        return ALWAYS
    th = rat(theta_turns) % 1
    if r < 0:
        th = (-th) % 1
    return _class_at(1 / abs(r), rat(t0), th)


def _class_at(P: Fraction, t0: Fraction, theta_turns: Fraction) -> PhaseClass:
    """The positive-half-cycle class of a tone with period P (the §9 map)."""
    return phase(P / 2, 2, phi=(t0 - theta_turns * P - P / 4) % P)


def quantize_phase_turns(theta_turns, quantum=DEFAULT_PHASE_QUANTUM) -> Fraction:
    """Snap an estimated phase to the declared quantum, exactly.

    Floats in, exact rational out: the float is taken at its exact dyadic
    value, divided in ℚ, and rounded half-even. Result is in [0, 1).
    """
    q = rat(quantum)
    if q <= 0:
        raise ValueError("phase quantum must be positive")
    n = round(rat(theta_turns) / q)
    return (n * q) % 1


def bin_identity(fs, N: int, k: int, t0=0, theta_turns=0):
    """The eternal identity of FFT bin k: ALWAYS for DC, else the Φ."""
    fs = rat(fs)
    if fs <= 0:
        raise ValueError("sample rate must be positive")
    if not isinstance(N, int) or N < 1:
        raise ValueError("N must be a positive integer")
    if not isinstance(k, int) or not 0 <= k <= N // 2:
        raise ValueError(f"bin k must lie in [0, {N // 2}]")
    if k == 0:
        return ALWAYS
    P = Fraction(N) / (k * fs)
    return _class_at(P, rat(t0), rat(theta_turns) % 1)


# --- the provenance record --------------------------------------------------


@dataclass(frozen=True)
class FFTComponent:
    """One analysis bin, with the provenance needed to reproduce its name.

    This is a *record about a measurement*, not a set of time: two records
    differing only in amplitude are different records but project to the
    same class. Text form ``ic1:f:...``, binary type 0x8.
    """

    fs: Fraction
    N: int
    k: int
    t0: Fraction
    A: float
    theta_turns: Fraction
    quantum: Fraction = DEFAULT_PHASE_QUANTUM

    def __post_init__(self):
        object.__setattr__(self, "fs", rat(self.fs))
        object.__setattr__(self, "t0", rat(self.t0))
        object.__setattr__(self, "theta_turns", rat(self.theta_turns))
        object.__setattr__(self, "quantum", rat(self.quantum))
        object.__setattr__(self, "A", float(self.A))
        if self.fs <= 0:
            raise ValueError("sample rate must be positive")
        if not isinstance(self.N, int) or self.N < 1:
            raise ValueError("N must be a positive integer")
        if not isinstance(self.k, int) or not 0 <= self.k <= self.N // 2:
            raise ValueError(f"bin k must lie in [0, {self.N // 2}]")
        if not (-MAX_ABS_SECONDS <= self.t0 < MAX_ABS_SECONDS):
            raise RangeError(f"capture start {self.t0} outside ±2^63 s window")
        if not math.isfinite(self.A):
            raise ValueError("amplitude must be finite")
        if not 0 <= self.theta_turns < 1:
            raise ValueError("theta_turns must lie in [0, 1)")
        if self.quantum <= 0:
            raise ValueError("phase quantum must be positive")
        if self.is_dc and self.theta_turns != 0:
            raise ValueError("DC bin (k=0) has no phase: theta_turns must be 0")
        if self.is_nyquist and self.theta_turns not in (0, Fraction(1, 2)):
            raise ValueError("Nyquist bin (k=N/2) has theta_turns ∈ {0, 1/2}")

    # --- derived quantities

    @property
    def freq(self) -> Fraction:
        """Exact bin frequency f_k = k·f_s/N (0 for DC)."""
        return self.k * self.fs / self.N

    @property
    def period(self) -> Fraction:
        """Exact bin period P = N/(k·f_s). DC has no period."""
        if self.is_dc:
            raise ValueError("the DC bin has no period")
        return Fraction(self.N) / (self.k * self.fs)

    @property
    def support(self) -> Span:
        """The capture span [t₀, t₀ + N/f_s)."""
        return Span(self.t0, self.t0 + Fraction(self.N) / self.fs)

    @property
    def is_dc(self) -> bool:
        return self.k == 0

    @property
    def is_nyquist(self) -> bool:
        return self.N % 2 == 0 and self.k == self.N // 2

    @property
    def identity(self) -> Union[Always, PhaseClass]:
        """The eternal class: "as if this component continued forever"."""
        return bin_identity(self.fs, self.N, self.k, self.t0, self.theta_turns)

    @property
    def windowed(self):
        """The honest capture-bounded set: Windowed(capture span, identity).

        DC collapses to the bare support span (ALWAYS ∩ span = span).
        """
        return windowed(self.support, self.identity)

    def contains(self, t) -> bool:
        return self.windowed.contains(t)

    def __repr__(self):
        return (f"FFTComponent[bin {self.k}/{self.N} @ {self.fs} Hz · "
                f"A={self.A!r} · {self.identity!r}]")


# --- analysis ---------------------------------------------------------------


def from_fft(X, fs, t0=0, *, N=None,
             phase_quantum_turns=DEFAULT_PHASE_QUANTUM) -> list[FFTComponent]:
    """Name every bin of a spectrum: bins 0..N//2 as provenance records.

    ``X`` is any sequence of values accepted by ``complex()`` — a numpy
    array works by duck typing, but numpy is not required. Pass ``N``
    explicitly when handing in a half-spectrum (rfft output).

    The amplitude convention is X[k] = (N/2)·A·e^{iθ} for interior bins,
    i.e. the analysis frame's component is A·cos(2πf_k(t − t₀) + 2πθ).
    Honesty (§9): each name describes *the analysis frame's component*, not
    the underlying tone — a non-bin tone leaks across bins.
    """
    fs = rat(fs)
    t0 = rat(t0)
    q = rat(phase_quantum_turns)
    n = len(X) if N is None else N
    if not isinstance(n, int) or n < 1:
        raise ValueError("N must be a positive integer")
    if len(X) < n // 2 + 1:
        raise ValueError(f"need at least {n // 2 + 1} bins for N={n}")

    out = []
    for k in range(n // 2 + 1):
        z = complex(X[k])
        re, im = z.real, z.imag
        if k == 0:  # DC: the signed mean. No phase.
            amp, th = re / n, Fraction(0)
        elif n % 2 == 0 and k == n // 2:  # Nyquist: θ ∈ {0, π}.
            amp = abs(re) / n
            th = Fraction(0) if re >= 0 else Fraction(1, 2)
        else:
            # Naive sqrt, deliberately not math.hypot — see module docstring.
            amp = 2.0 * math.sqrt(re * re + im * im) / n
            th = quantize_phase_turns(math.atan2(im, re) / math.tau, q)
        out.append(FFTComponent(fs, n, k, t0, amp, th, q))
    return out


def from_samples(samples, fs, t0=0, *,
                 phase_quantum_turns=DEFAULT_PHASE_QUANTUM) -> list[FFTComponent]:
    """Convenience: run the FFT, then name the bins. Needs numpy."""
    try:
        import numpy
    except ImportError as e:  # pragma: no cover - exercised only without numpy
        raise ImportError(
            "from_samples() needs numpy: pip install 'intervalclock[dsp]'. "
            "from_fft() takes a spectrum you computed yourself and is "
            "dependency-free."
        ) from e
    x = numpy.asarray(samples)
    return from_fft(numpy.fft.fft(x), fs, t0, N=len(x),
                    phase_quantum_turns=phase_quantum_turns)


# --- amplitude wire form ----------------------------------------------------
# Amplitude is the one float in the protocol. Shortest-decimal formatting
# differs between languages (Python's repr(1e16) is '1e+16', JS gives
# '10000000000000000'), so the canonical text form carries the raw binary64
# bits as 16 lowercase hex digits — exact, and trivially identical in both.


def amp_hex(a: float) -> str:
    return struct.pack(">d", a).hex()


def amp_from_hex(h: str) -> float:
    if len(h) != 16 or any(c not in "0123456789abcdef" for c in h):
        raise ValueError("amplitude must be 16 lowercase hex digits")
    a = struct.unpack(">d", bytes.fromhex(h))[0]
    if not math.isfinite(a):
        raise ValueError("amplitude must be finite")
    return a
