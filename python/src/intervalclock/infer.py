"""Schedule inference: observed timestamps → names (PROTOCOL.md §10).

Everything else in this library runs names → sets of time. This runs the map
backwards: given when a thing actually happened, what is it called? Point
that at a feed's publication times and it answers "every Tuesday ~09:00".

The method is epoch folding. For a candidate period P, reduce every event to
its phase on the circle ℝ/P and measure how tightly the phases cluster with
the Rayleigh test. A real schedule concentrates; noise spreads out. Calendar
cycles are folded *through the civil lens* (Layer B) rather than as fixed
rational periods, because months vary in length and a local 09:00 shifts by
an hour across a DST boundary — a TAI-rational fold smears exactly the
schedules people care most about.

Confidence bounds are normative (§10), not decoration:

  * ``min_resolution`` caps phase precision. The reported phase is snapped
    to that grid; claiming more would be claiming to resolve what you did
    not measure.
  * The observation span caps the longest detectable period, so candidates
    stop at about span/3 — three cycles is the least that can distinguish a
    period from a coincidence.
  * Event count caps significance. Scores are Rayleigh p-values with a
    small-sample correction, Bonferroni-adjusted for every candidate tried,
    so a handful of events cannot buy confidence by being scanned harder.

Determinism: residues are reduced in exact ℚ *before* any float appears, so
a timestamp near 1.7e9 s never loses precision to a 53-bit mantissa; sums
use math.fsum over the sorted event list; and the phase is quantized to
min_resolution as the very last step, which absorbs libm differences in
sin/cos/atan2 unless the true mean sits within picoseconds of a grid
midpoint. No sets, no dict-order dependence, and a total ordering on the
final ranking.
"""

from __future__ import annotations

import calendar as _cal
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from fractions import Fraction
from typing import Iterable, Optional, Sequence, Union

from .calendar import civil
from .core import PhaseClass, PSet, phase
from .cron import CronSchedule, from_cron, to_cron
from .rat import divides, fmt, rat
from .timescale import Instant, unix_from_tai

__all__ = ["InferResult", "infer"]

_DAY = Fraction(86400)
_WEEK = Fraction(604800)
# Mean Gregorian month and year — nominal cycle lengths, used only for
# ranking and for converting jitter to seconds. The folds themselves go
# through the lens, where a month is however long that month actually is.
_MONTH = Fraction(2629746)
_YEAR = Fraction(31556952)

_CYCLE_LENGTH = {"day": _DAY, "isoweek": _WEEK, "month": _MONTH, "year": _YEAR}
_DOW_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
              "Saturday", "Sunday")
_MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# Candidate rational periods people actually build schedules out of. These
# are tested as exact claims — no refinement, because "every 20 minutes" is
# a hypothesis about the world, not a measurement to be nudged.
_NICE = sorted({
    *(Fraction(s) for s in (1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30)),
    *(Fraction(60 * m) for m in (1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30)),
    *(Fraction(3600 * h) for h in (1, 2, 3, 4, 6, 8, 12)),
    *(Fraction(86400 * d) for d in range(1, 15)),
})


@dataclass(frozen=True)
class InferResult:
    """One candidate schedule, with the evidence for it.

    ``cls`` is the name: a Φ class for rational periods, a CronSchedule for
    calendar cycles (render it with ``to_cron``). ``score`` is the Rayleigh
    concentration R̄ ∈ [0, 1] — 1 is a perfect fold. ``matched_fraction`` is
    the exact share of events the emitted name actually covers, and
    ``phase_jitter`` is the circular spread in seconds. The last two are
    measurement data: they describe the fit, not the identity.
    """

    cls: Union[PhaseClass, PSet, CronSchedule]
    score: float
    matched_fraction: Fraction
    phase_jitter: float
    period: Optional[Fraction]
    p_value: float
    kind: str
    detail: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def cron_text(self) -> Optional[str]:
        """Standard cron text, for calendar winners."""
        return to_cron(self.cls) if isinstance(self.cls, CronSchedule) else None

    def human(self) -> str:
        """A plain-language reading. Lossy on purpose — cls is the name."""
        d = self.detail
        approx = "~" if self.phase_jitter > float(d.get("resolution", 0)) else ""
        clock = d.get("clock", "")
        if self.kind == "day":
            return f"every day {approx}{clock}"
        if self.kind == "isoweek":
            return f"every {_DOW_NAMES[d['weekday']]} {approx}{clock}"
        if self.kind == "month":
            return f"monthly on day {d['dom']} {approx}{clock}"
        if self.kind == "year":
            return (f"yearly on {_MONTH_NAMES[d['month'] - 1]} {d['dom']} "
                    f"{approx}{clock}")
        return f"every {_duration(self.period)} at {approx}+{_duration(d['offset'])}"

    def __repr__(self):
        return (f"InferResult[{self.human()} · R̄={self.score:.3f} · "
                f"{float(self.matched_fraction):.0%} matched]")


def _duration(q: Fraction) -> str:
    """Human-scale rendering of an exact rational number of seconds."""
    q = rat(q)
    if q == 0:
        return "0 s"
    for unit, size in (("d", _DAY), ("h", Fraction(3600)), ("min", Fraction(60))):
        if q >= size and divides(size, q):
            return f"{fmt(q / size)} {unit}"
    return f"{fmt(q)} s"


# --- the scoring core -------------------------------------------------------


def _rayleigh(fracs: Sequence[float]) -> tuple[float, float]:
    """Circular concentration R̄ and circular mean, from phases in [0, 1).

    R̄ = |Σ e^{iα}| / n. fsum keeps the accumulation order-independent for a
    fixed input order, which the caller guarantees by sorting once.
    """
    n = len(fracs)
    c = math.fsum(math.cos(math.tau * f) for f in fracs)
    s = math.fsum(math.sin(math.tau * f) for f in fracs)
    rbar = min(1.0, math.hypot(c, s) / n)
    return rbar, (math.atan2(s, c) / math.tau) % 1.0


def _rayleigh_p(rbar: float, n: int) -> float:
    """p-value with the small-sample correction (Wilkie 1983).

    The correction is the whole point: at n = 5 the asymptotic exp(−Z) is
    optimistic by enough to manufacture schedules out of noise.
    """
    z = n * rbar * rbar
    if z > 700:  # exp underflows; the answer is "certain" either way
        return 0.0
    p = math.exp(-z) * (
        1 + (2 * z - z * z) / (4 * n)
        - (24 * z - 132 * z**2 + 76 * z**3 - 9 * z**4) / (288 * n * n)
    )
    return min(1.0, max(0.0, p))


def _fold_rational(ts: Sequence[Fraction], P: Fraction,
                   t_ref: Fraction) -> tuple[float, float]:
    """Fold events onto the circle ℝ/P. Residues are exact before floats."""
    return _rayleigh([float(((t - t_ref) % P) / P) for t in ts])


def _circular_sigma(rbar: float, cycle: Fraction) -> float:
    """Circular standard deviation √(−2 ln R̄), expressed in seconds."""
    if rbar <= 0:
        return math.inf
    if rbar >= 1:
        return 0.0
    return math.sqrt(-2 * math.log(rbar)) * float(cycle) / math.tau


# --- candidate periods ------------------------------------------------------


def _simplest_between(lo: Fraction, hi: Fraction) -> Fraction:
    """The minimal-denominator rational in [lo, hi] (Stern–Brocot descent).

    This is the honest answer to "which period do we name": the simplest
    one the data cannot distinguish from the best fit.
    """
    if hi < lo:
        lo, hi = hi, lo
    fl = Fraction(lo // 1)
    if lo == fl:
        return fl
    if fl + 1 <= hi:
        return fl + 1
    return fl + 1 / _simplest_between(1 / (hi - fl), 1 / (lo - fl))


def _snap(best: Fraction, lo: Fraction, hi: Fraction) -> Fraction:
    """Simplest rational in the bracket, nearest to the fit among equals.

    Whole seconds all have denominator 1, so when several sit in the
    bracket "simplest" cannot choose between them — 1199 is no simpler than
    1200. Break that tie by distance to the measured optimum, or a schedule
    that is plainly every 20 minutes gets named 1199 s.
    """
    ints = range(math.ceil(lo), math.floor(hi) + 1)
    if len(ints) > 0:
        return Fraction(min(ints, key=lambda c: (abs(Fraction(c) - best), c)))
    return _simplest_between(lo, hi)


def _gap_seeds(ts: Sequence[Fraction], q: Fraction) -> list[Fraction]:
    """Seed periods from the histogram of consecutive gaps.

    A missed event doubles a gap, so each mode also seeds its halves and
    thirds; the exact rational gcd of the gaps catches grids whose modal
    gap is not the fundamental.
    """
    counts: dict[Fraction, int] = {}
    for a, b in zip(ts, ts[1:]):
        g = round((b - a) / q) * q
        if g > 0:
            counts[g] = counts.get(g, 0) + 1
    modes = sorted(counts, key=lambda g: (-counts[g], g))[:5]
    seeds = []
    for g in modes:
        seeds += [g, g / 2, g / 3, 2 * g]
    if counts:
        from functools import reduce as _reduce

        from .rat import rgcd
        common = _reduce(rgcd, counts)
        if common > 0:
            seeds.append(common)
    return seeds


def _scan_periods(min_res: Fraction, longest: Fraction,
                  span: Fraction) -> list[Fraction]:
    """Uniform frequency grid, 4× oversampled past the Fourier spacing."""
    df = 1 / (4 * span)
    lo_f, hi_f = 1 / longest, 1 / (2 * min_res)
    count = int((hi_f - lo_f) / df) + 1
    if count > 100_000:
        raise ValueError(
            f"scan would need {count} candidates; raise min_resolution "
            f"or pass explicit candidates"
        )
    return [1 / (lo_f + i * df) for i in range(max(count, 0))]


def _refine(ts, P0: Fraction, t_ref: Fraction, min_res: Fraction,
            span: Fraction) -> tuple[Fraction, int]:
    """Local search around a measured seed, then snap to a nameable rational.

    A seed quantized to min_resolution can be off by half a quantum, which
    over many cycles smears the fold completely; the grid below is fine
    enough to resolve that (its step keeps end-to-end drift under half a
    resolution) and wide enough to cover it.

    Returns the period and how many hypotheses the search burned — the
    caller must charge those against significance, or maximizing R̄ over a
    few hundred grid points will "find" a period in anything.
    """
    half = min_res / 2
    step = P0 * min_res / (2 * span)
    if step <= 0:
        return P0, 1
    n_side = min(int(half / step), 200)
    best, best_r = P0, _fold_rational(ts, P0, t_ref)[0]
    evaluated = 1
    for i in range(-n_side, n_side + 1):
        P = P0 + i * step
        if P <= 0:
            continue
        evaluated += 1
        r = _fold_rational(ts, P, t_ref)[0]
        if r > best_r:
            best, best_r = P, r
    drift = best * min_res / span  # periods the span cannot tell apart
    return _snap(best, best - drift, best + drift), evaluated


# --- the civil-lens folds ---------------------------------------------------


def _civil_parts(t: Fraction, zone: str):
    """(year, month, day, seconds-into-day) for an event, through the lens."""
    u, _ = unix_from_tai(t)
    frac = u - (u // 1)
    y, mo, d, h, mi, s = civil(Instant(t), zone).fields
    if s == 60:  # a leap second reads as the last second of its day
        s = 59
    return y, mo, d, Fraction(h * 3600 + mi * 60 + s) + frac


def _calendar_fracs(parts, kind: str) -> list[float]:
    """Position on a calendar cycle, in [0, 1).

    Month and year positions are normalized by the *actual* length of that
    month or year — the reason §10 insists calendar folding goes through
    Layer B rather than pretending a month is 30 days of TAI.
    """
    out = []
    for y, mo, d, tod in parts:
        if kind == "day":
            out.append(float(tod / _DAY))
        elif kind == "isoweek":
            wd = date(y, mo, d).weekday()  # Monday = 0, matching ISO weeks
            out.append(float((wd * _DAY + tod) / _WEEK))
        elif kind == "month":
            dim = _cal.monthrange(y, mo)[1]
            out.append(float(((d - 1) * _DAY + tod) / (dim * _DAY)))
        else:  # year
            doy = date(y, mo, d).timetuple().tm_yday
            diy = 366 if _cal.isleap(y) else 365
            out.append(float(((doy - 1) * _DAY + tod) / (diy * _DAY)))
    return out


def _mode(values) -> int:
    """Most common value, ties broken by the smaller — deterministic."""
    counts: dict[int, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return sorted(counts, key=lambda v: (-counts[v], v))[0]


def _clock(tod_seconds: Fraction, min_res: Fraction) -> tuple[int, int]:
    """Circular-mean time of day → (hour, minute) on the resolution grid.

    Cron cannot express seconds, so the grid is at least a minute wide and
    any finer resolution shows up as jitter instead of false precision.
    """
    step = max(rat(min_res), Fraction(60))
    q = (round(tod_seconds / step) * step) % _DAY
    total = int(q // 60) % 1440
    return divmod(total, 60)


# --- emission ---------------------------------------------------------------


def _emit_phase(ts, P: Fraction, mean_frac: float, t_ref: Fraction,
                min_res: Fraction, rbar: float, p: float) -> Optional[InferResult]:
    """A rational winner becomes a Φ class one resolution-quantum wide."""
    m = round(P / min_res)
    if m < 2:
        return None  # the resolution cannot name a pulse inside this period
    w = P / m
    # Quantize the phase last, so float error in the circular mean is
    # absorbed rather than propagated into the name.
    center = (round((t_ref + rat(mean_frac) * P) / min_res) * min_res) % P
    cls = phase(w, m, phi=(center - w / 2) % P)
    n = len(ts)
    matched = Fraction(sum(1 for t in ts if cls.contains(t)), n)
    return InferResult(
        cls=cls, score=rbar, matched_fraction=matched,
        phase_jitter=_circular_sigma(rbar, P), period=P, p_value=p,
        kind="phase", detail={"offset": center, "resolution": min_res},
    )


def _emit_calendar(ts, parts, kind: str, tod_mean: Fraction, zone: str,
                   min_res: Fraction, rbar: float, p: float) -> Optional[InferResult]:
    """A calendar winner becomes a cron schedule, canonicalized as usual.

    Day-of-month and month come from the mode of what was observed, not the
    circular mean: a mean position inside an irregular month can land on a
    day no event ever hit.
    """
    h, mi = _clock(tod_mean, min_res)
    detail = {"clock": f"{h:02d}:{mi:02d}", "resolution": min_res}
    if kind == "day":
        expr = f"{mi} {h} * * *"
    elif kind == "isoweek":
        wd = _mode([date(y, mo, d).weekday() for y, mo, d, _ in parts])
        detail["weekday"] = wd
        expr = f"{mi} {h} * * {(wd + 1) % 7}"  # cron counts Sunday as 0
    elif kind == "month":
        dom = _mode([d for _, _, d, _ in parts])
        detail["dom"] = dom
        expr = f"{mi} {h} {dom} * *"
    else:  # year
        mon = _mode([mo for _, mo, _, _ in parts])
        dom = _mode([d for y, mo, d, _ in parts if mo == mon])
        detail.update({"month": mon, "dom": dom})
        expr = f"{mi} {h} {dom} {mon} *"

    schedule = from_cron(expr, zone)
    if not isinstance(schedule, CronSchedule):
        return None
    hits = sum(
        1 for (y, mo, d, tod) in parts
        if schedule.contains_local(
            datetime(y, mo, d, int(tod // 3600), int(tod // 60) % 60)
        )
    )
    return InferResult(
        cls=schedule, score=rbar, matched_fraction=Fraction(hits, len(ts)),
        phase_jitter=_circular_sigma(rbar, _CYCLE_LENGTH[kind]), period=None,
        p_value=p, kind=kind, detail=detail,
    )


# --- the entry point --------------------------------------------------------


def _coerce(timestamps: Iterable) -> list[Fraction]:
    out = []
    for x in timestamps:
        out.append(x.t if isinstance(x, Instant) else rat(x))
    return sorted(set(out))


def infer(timestamps: Iterable, min_resolution=Fraction(1), top_k: int = 3,
          candidates="auto", zone: str = "UTC",
          significance: float = 0.05) -> list[InferResult]:
    """Rank the schedules that could have produced these timestamps.

    ``timestamps`` are TAI seconds since epoch (Instants, Fractions, ints,
    floats, or strings); use ``tai_from_unix`` on unix logs first.
    ``min_resolution`` is how finely you are willing to claim a phase.
    ``candidates`` is "auto" (a lattice of human periods plus seeds from
    the observed gaps), "scan" (an oversampled frequency sweep — slower,
    for periods nothing human would pick), or an explicit sequence of
    periods. ``zone`` is the civil lens used for calendar folding.

    Returns up to ``top_k`` results, best first. An empty list is a real
    answer: nothing here beats chance.
    """
    ts = _coerce(timestamps)
    n = len(ts)
    if n < 4:
        raise ValueError("need at least 4 distinct timestamps to infer anything")
    min_res = rat(min_resolution)
    if min_res <= 0:
        raise ValueError("min_resolution must be positive")
    span = ts[-1] - ts[0]
    if span <= 0:
        raise ValueError("timestamps must span a positive interval")
    t_ref = ts[0]
    longest = span / 3  # three cycles is the least that distinguishes a period
    shortest = 2 * min_res

    # --- rational candidates
    if isinstance(candidates, str):
        exact = [P for P in _NICE if shortest <= P <= longest]
        seeds = [P for P in _gap_seeds(ts, min_res) if shortest <= P <= longest]
        if candidates == "scan":
            seeds += _scan_periods(min_res, longest, span)
        elif candidates != "auto":
            raise ValueError("candidates must be 'auto', 'scan', or a sequence")
    else:
        exact = [rat(P) for P in candidates]
        seeds = []

    scored = []  # (period, rbar, mean_frac, refined?)
    for P in dict.fromkeys(exact):
        rbar, mean = _fold_rational(ts, P, t_ref)
        scored.append((P, rbar, mean))
    # Refine only measured seeds — a nice period is a claim under test, not
    # an estimate to nudge. Refining the best few keeps the cost bounded.
    seeds = sorted(dict.fromkeys(seeds))
    # Every divisor of the true period folds just as tightly, so ranking
    # seeds by R̄ alone hands refinement to the shortest one and the
    # fundamental never becomes a candidate for occupancy to vote on.
    # Differences below a thousandth of R̄ are not evidence; among those,
    # take the longest period.
    seed_scores = sorted(
        ((P, *_fold_rational(ts, P, t_ref)) for P in seeds),
        key=lambda r: (-round(r[1], 3), -r[0]),
    )
    known = {P for P, _, _ in scored}
    refine_cost = 0
    for P0, _, _ in seed_scores[:3]:
        P, evaluated = _refine(ts, P0, t_ref, min_res, span)
        refine_cost += evaluated
        if P in known or not shortest <= P <= longest:
            continue
        known.add(P)
        rbar, mean = _fold_rational(ts, P, t_ref)
        scored.append((P, rbar, mean))

    # --- calendar candidates, folded through the lens
    parts = [_civil_parts(t, zone) for t in ts]
    tod_rbar, tod_mean = _rayleigh(_calendar_fracs(parts, "day"))
    cal_scored = []
    for kind, cycle in _CYCLE_LENGTH.items():
        if span < 3 * cycle:
            continue
        rbar, _ = _rayleigh(_calendar_fracs(parts, kind))
        cal_scored.append((kind, rbar))

    # Every hypothesis tested dilutes significance — including the ones the
    # refinement search burned. That is what stops a wide sweep from
    # "finding" a schedule in noise.
    tested = len(scored) + len(cal_scored) + len(seed_scores) + refine_cost
    results = []
    for P, rbar, mean in scored:
        p = min(1.0, _rayleigh_p(rbar, n) * tested)
        if p > significance:
            continue
        r = _emit_phase(ts, P, mean, t_ref, min_res, rbar, p)
        if r is not None:
            results.append(r)
    for kind, rbar in cal_scored:
        p = min(1.0, _rayleigh_p(rbar, n) * tested)
        if p > significance:
            continue
        r = _emit_calendar(ts, parts, kind, Fraction(tod_mean) * _DAY, zone,
                           min_res, rbar, p)
        if r is not None:
            results.append(r)

    # A name that misses most of the events it was derived from is not a
    # name for them. This is what rejects an "almost weekly" rational period
    # fitted to events that are actually weekly in *local* time: the fold
    # looks concentrated, but the class it emits contains nothing.
    results = [r for r in results if r.matched_fraction >= Fraction(1, 2)]
    results = _suppress_subharmonics(results, ts, parts, span)
    results = _prefer_calendar(results)
    results.sort(key=lambda r: (-(n * r.score * r.score),
                                r.period if r.period is not None
                                else _CYCLE_LENGTH[r.kind],
                                r.kind))
    return results[:top_k]


# A finer calendar cycle tiles a coarser one, exactly as P/k tiles P.
# (ISO weeks nest in nothing: they straddle month and year boundaries.)
_CAL_NESTS = {"day": ("isoweek", "month", "year"), "month": ("year",)}


def _nests(a: InferResult, b: InferResult) -> bool:
    """Does a's cycle tile b's — i.e. is a a possible subharmonic of b?"""
    if a.period is not None and b.period is not None:
        return divides(a.period, b.period)
    if a.period is None and b.period is None:
        return b.kind in _CAL_NESTS.get(a.kind, ())
    if a.period is not None:
        # A rational period tiles a calendar cycle when it divides it. Days
        # and weeks are exact; months and years are not fixed lengths, but
        # they are whole numbers of days, so any within-day rhythm tiles
        # them. (Weekly events fold perfectly at "every hour" too — one
        # hour in 168 is occupied, which is what occupancy then catches.)
        if b.kind in ("day", "isoweek"):
            return divides(a.period, _CYCLE_LENGTH[b.kind])
        return divides(a.period, _DAY)
    return False


def _occupancy(r: InferResult, ts, parts, span: Fraction) -> Fraction:
    """Share of this cycle's slots that actually contain an event.

    Events every 20 minutes also fold perfectly at 10 minutes — every other
    slot is simply empty. A weekly schedule folds perfectly on the daily
    cycle too, and hits one day in seven. Occupancy is what tells them
    apart.
    """
    if r.period is not None:
        hit = len({int((t - ts[0]) // r.period) for t in ts})
        total = int((ts[-1] - ts[0]) // r.period) + 1
    else:
        if r.kind == "day":
            hit = len({(y, mo, d) for y, mo, d, _ in parts})
        elif r.kind == "isoweek":
            hit = len({date(y, mo, d).isocalendar()[:2] for y, mo, d, _ in parts})
        elif r.kind == "month":
            hit = len({(y, mo) for y, mo, _, _ in parts})
        else:
            hit = len({y for y, _, _, _ in parts})
        total = int(span // _CYCLE_LENGTH[r.kind]) + 1
    return Fraction(hit, max(total, 1))


def _cycle_length(r: InferResult) -> Fraction:
    return r.period if r.period is not None else _CYCLE_LENGTH[r.kind]


def _suppress_subharmonics(results, ts, parts, span: Fraction) -> list:
    """Prefer the fundamental over the cycles that tile it.

    Folding at P/k concentrates just as tightly as folding at P, so score
    alone cannot choose; the longer cycle with fuller slots is the honest
    name for the same events. This is why "every Tuesday" beats "every day"
    on Tuesday-only data even though both fold perfectly.
    """
    if len(results) < 2:
        return results
    occ = {id(r): _occupancy(r, ts, parts, span) for r in results}
    drop = set()
    for a in results:
        for b in results:
            if a is b or _cycle_length(a) == _cycle_length(b):
                continue
            if not (_nests(a, b) or _nests(b, a)):
                continue
            if b.score >= 0.95 * a.score and (occ[id(b)], _cycle_length(b)) > (
                occ[id(a)], _cycle_length(a)
            ):
                drop.add(id(a))
    return [r for r in results if id(r) not in drop]


def _prefer_calendar(results) -> list:
    """A daily or weekly rhythm is named by the calendar, not by 86400 s.

    Only when the calendar fold holds up: if the events are anchored in TAI
    they drift against local time across a DST boundary, the civil fold
    scores worse, and the Φ class is then the truer name.
    """
    by_kind = {r.kind: r for r in results if r.period is None}
    drop = set()
    for r in results:
        twin = ({_DAY: "day", _WEEK: "isoweek"}).get(r.period)
        cal = by_kind.get(twin)
        if cal is not None and cal.score >= 0.95 * r.score:
            drop.add(id(r))
    return [r for r in results if id(r) not in drop]
