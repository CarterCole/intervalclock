"""Decompose the Bitcoin block interval — and find that there is no clock in it.

Bitcoin's "ten minute block" sounds like a schedule, and this is what the
library says about it:

    no schedule beats chance in this data

That is the §10 null result, and it is the honest answer. A schedule is a
period *and a phase*; the block interval has a rate and no phase at all.
This script fetches real block timestamps from mempool.space and shows the
four ways that shows up:

  A. the gap is exponential — memoryless, CV ≈ 1, median ≈ ln2·mean — and it
     is exponential *per retarget epoch*; pooled over months it fails a KS
     test only because the rate drifts between epochs, which is a mixture,
     not a schedule;
  B. epoch folding finds nothing: every candidate period sits at the Rayleigh
     noise floor, checked against synthetic homogeneous-Poisson sets rather
     than against an asymptotic p-value that is wrong when the span holds
     only a few cycles (§10's span/3 cap, earned the hard way);
  C. the spectrum of the arrival process is flat — var/mean ≈ 1, the loudest
     bin no louder than white noise allows — and the one structural joke is
     that sampling at 1/600 Hz puts the 600 s target exactly *at* Nyquist, so
     a true 600 s tone would alias to ic1:always;
  D. what is exactly periodic in Bitcoin (1 block, 2016, 210000) is counted
     in blocks, not in seconds. In seconds those are ic1:d: durations — a
     period with no epoch anchor — which is precisely §2.5's distinction
     between a duration and a phase class.

    python3 examples/bitcoin_blocks.py                    # ~135 requests
    python3 examples/bitcoin_blocks.py --blocks 9072      # two months, ~605
    python3 examples/bitcoin_blocks.py --tip 972800 --blocks 9072   # pinned
    python3 examples/bitcoin_blocks.py --dump | intervalclock infer - --unix

Stdlib only — the FFT here is twenty lines of Cooley-Tukey, so N is a power
of two. Fetched timestamps are cached under --cache, so re-runs are free and
a pinned --tip reproduces every number exactly.
"""

from __future__ import annotations

import argparse
import cmath
import json
import math
import random
import statistics
import sys
import urllib.request
from fractions import Fraction as F
from pathlib import Path

import intervalclock as ic
from intervalclock import dsp

API = "https://mempool.space/api"
GENESIS = 1231006505          # the unix timestamp in block 0
EPOCH_BLOCKS = 2016           # blocks per difficulty retarget
TARGET = 600                  # the protocol's target interval, in seconds
BIN = F(600)                  # bin width for the counting-process spectrum


# --- fetching ---------------------------------------------------------------


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "intervalclock-example"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


def fetch_blocks(cache: Path, tip: int | None, count: int) -> dict[int, int]:
    """{height: unix timestamp} for `count` blocks ending at `tip`.

    /api/v1/blocks/<h> answers with the 15 headers at or below h — usually.
    Short answers happen, so this asks for whatever is still missing until
    nothing new arrives, rather than assuming the run came back contiguous.
    """
    store = cache / "blocks.txt"
    have: dict[int, int] = {}
    if store.exists():
        have = {int(h): int(t) for h, t in
                (l.split() for l in store.read_text().split("\n") if l)}
    if tip is None:
        tip = int(_get(f"{API}/blocks/tip/height"))
    want = range(tip - count + 1, tip + 1)
    missing = [h for h in want if h not in have]
    fetched = 0
    while missing:
        for b in json.loads(_get(f"{API}/v1/blocks/{max(missing)}")):
            have[int(b["height"])] = int(b["timestamp"])
        fetched += 1
        if fetched % 20 == 0:
            print(f"  ... {fetched} requests, {len(missing)} blocks to go",
                  file=sys.stderr)
        still = [h for h in want if h not in have]
        if len(still) >= len(missing):
            raise RuntimeError(f"no progress fetching below {max(missing)}")
        missing = still
    if fetched:
        cache.mkdir(parents=True, exist_ok=True)
        store.write_text("".join(f"{h} {have[h]}\n" for h in sorted(have)))
    return {h: have[h] for h in want}


def fetch_retargets(cache: Path) -> list[list]:
    """Every difficulty retarget ever, as [unix, height, difficulty, multiplier].

    One request. Only retargets where the difficulty actually *changed* are
    listed, so consecutive entries are not always 2016 blocks apart.
    """
    store = cache / "retargets.json"
    if not store.exists():
        cache.mkdir(parents=True, exist_ok=True)
        store.write_text(_get(f"{API}/v1/mining/difficulty-adjustments/all"))
    return sorted(json.loads(store.read_text()), key=lambda r: r[1])


# --- statistics the stdlib does not have ------------------------------------


def ks_exponential(xs: list[float]) -> tuple[float, float]:
    """Kolmogorov-Smirnov D and p against Exp(mean of xs).

    The scale is fitted from the sample, so p is optimistic (Lilliefors);
    it is quoted to show the *shape* is not being rejected, not to certify it.
    """
    n = len(xs)
    mean = statistics.fmean(xs)
    d = 0.0
    for i, x in enumerate(sorted(xs)):
        f = 1 - math.exp(-x / mean)
        d = max(d, f - i / n, (i + 1) / n - f)
    lam = (math.sqrt(n) + 0.12 + 0.11 / math.sqrt(n)) * d
    p = 2 * math.fsum((-1) ** (j - 1) * math.exp(-2 * j * j * lam * lam)
                      for j in range(1, 101))
    return d, min(max(p, 0.0), 1.0)


def rbar(phases: list[float]) -> float:
    """Rayleigh concentration R̄ of phases given in turns."""
    a = [2 * math.pi * p for p in phases]
    return math.hypot(math.fsum(math.cos(x) for x in a),
                      math.fsum(math.sin(x) for x in a)) / len(a)


def fold_exact(ts: list[F], P: F) -> list[float]:
    """Phases in turns, reduced in exact ℚ before any float appears (§10)."""
    return [float((t % P) / P) for t in ts]


def fft(a: list[complex]) -> list[complex]:
    """Radix-2 Cooley-Tukey, same sign convention as numpy.fft.fft."""
    n = len(a)
    if n == 1:
        return list(a)
    ev, od = fft(a[0::2]), fft(a[1::2])
    out = [0j] * n
    for k in range(n // 2):
        t = cmath.exp(-2j * cmath.pi * k / n) * od[k]
        out[k], out[k + n // 2] = ev[k] + t, ev[k] - t
    return out


def periodogram(counts: list[float]) -> list[float]:
    """|X_k|²/N of the mean-removed series: the white-noise level is its variance."""
    n = len(counts)
    mean = statistics.fmean(counts)
    X = fft([complex(c - mean) for c in counts])
    return [abs(z) ** 2 / n for z in X[:n // 2 + 1]]


def bin_counts(ts: list[F], t0: F, width: F, n: int) -> list[float]:
    """Event counts in n bins of `width` starting at t0."""
    c = [0.0] * n
    for t in ts:
        k = int((t - t0) / width)
        if 0 <= k < n:
            c[k] += 1
    return c


# --- A. the gap -------------------------------------------------------------


def section_gap(heights: list[int], ts: list[F]) -> None:
    g = [float(b - a) for a, b in zip(ts, ts[1:])]
    mean = statistics.fmean(g)
    sd = statistics.stdev(g)
    med = statistics.median(g)
    m3 = statistics.fmean([((x - mean) / sd) ** 3 for x in g])
    print(f"A. THE GAP — shape of {len(g)} intervals")
    print(f"     mean      {mean:9.2f} s   ({mean / 60:.3f} min; the target is "
          f"{TARGET} s)")
    print(f"     median    {med:9.2f} s   ln2·mean = {math.log(2) * mean:.2f}"
          f"   — equal for an exponential")
    print(f"     CV        {sd / mean:9.4f}     sd/mean; an exponential has 1")
    print(f"     skew      {m3:9.4f}     an exponential has 2")
    print(f"     min/max   {min(g):9.0f} / {max(g):.0f} s")
    neg = [x for x in g if x < 0]
    print(f"     {len(neg)} gaps are negative ({len(neg) / len(g):.1%}): block"
          f" timestamps are miner-reported, and")
    print(f"     consensus only asks a block to beat the median of the last 11."
          f" The 'interval'")
    print(f"     is not even a well-ordered duration.")
    pos = [x for x in g if x > 0]
    d, p = ks_exponential(pos)
    print(f"\n     KS against Exp(fitted) on the {len(pos)} positive gaps: "
          f"D={d:.4f} p={p:.3f}")
    print(f"     memoryless — E[gap − s | gap > s] should not depend on s:")
    for s in (0, 300, 600, 1200, 2400):
        r = [x - s for x in pos if x > s]
        if len(r) > 20:
            print(f"       s = {s:>4} s   n = {len(r):>5}   "
                  f"E[gap − s | gap > s] = {statistics.fmean(r):7.1f} s")
    print(f"\n     per retarget epoch, where the rate is actually constant:")
    print(f"       {'epoch':>7}  {'blocks':>6}  {'mean':>8}  {'CV':>6}  "
          f"{'KS D':>7}  {'KS p':>6}")
    rows = 0
    for e in sorted({h // EPOCH_BLOCKS for h in heights}):
        idx = [i for i, h in enumerate(heights) if h // EPOCH_BLOCKS == e]
        if len(idx) < 400:
            continue
        eg = [float(ts[i + 1] - ts[i]) for i in idx[:-1] if i + 1 < len(ts)]
        ep = [x for x in eg if x > 0]
        d, p = ks_exponential(ep)
        print(f"       {e:>7}  {len(eg):>6}  {statistics.fmean(eg):8.1f}  "
              f"{statistics.stdev(eg) / statistics.fmean(eg):6.3f}  "
              f"{d:7.4f}  {p:6.3f}")
        rows += 1
    if rows > 1:
        print(f"     Each epoch is exponential; pooled, the fit degrades as the"
              f" rate drifts between")
        print(f"     them. A mixture of exponentials — not a schedule.")


# --- B. the phase -----------------------------------------------------------


def section_phase(ts: list[F], trials: int, seed: int) -> None:
    span = float(ts[-1] - ts[0])
    n = len(ts)
    rng = random.Random(seed)
    print(f"B. THE PHASE — epoch folding, against a homogeneous-Poisson control")
    print(f"     noise floor: E[R̄] for {n} unscheduled events is "
          f"{math.sqrt(math.pi / (4 * n)):.4f}")
    print(f"\n       {'period':>10} {'cycles':>8} {'R̄':>8} {'Rayleigh p':>11} "
          f"{'empirical p':>12}")
    cands = [(F(TARGET), f"{TARGET} s"), (F(1200), "1200 s"),
             (F(3600), "1 hour"), (F(43200), "12 hours"),
             (F(86400), "1 day"), (F(604800), "1 week"),
             (F(EPOCH_BLOCKS * TARGET), "retarget")]
    cands = [(P, lab) for P, lab in cands if span / float(P) >= 1.2]
    for P, label in cands:
        r = rbar(fold_exact(ts, P))
        asym = math.exp(-n * r * r)
        hits = 0
        for _ in range(trials):
            draw = [rng.uniform(0, span) / float(P) % 1 for _ in range(n)]
            if rbar(draw) >= r:
                hits += 1
        print(f"       {label:>10} {span / float(P):8.1f} {r:8.4f} "
              f"{asym:11.4f} {hits / trials:12.3f}")
    print(f"\n     The Rayleigh p-value is asymptotic and assumes the span holds"
          f" many cycles. Where")
    print(f"     it does not, it is wildly overconfident — which is why §10 "
          f"stops candidates at")
    print(f"     span/3. The empirical column is {trials} synthetic Poisson sets"
          f" of the same n and")
    print(f"     span, folded the same way, and it is the one to read.")
    print(f"     Whatever sits nearest significance there, {len(cands)} "
          f"candidates were tried: §10")
    print(f"     Bonferroni-adjusts for every candidate scanned, which is why "
          f"infer() reports none.")


# --- C. the spectrum --------------------------------------------------------


def section_spectrum(ts: list[F], trials: int, seed: int) -> None:
    t0, span = ts[0], ts[-1] - ts[0]
    avail = int(span / BIN)
    n_bins = 1 << (avail.bit_length() - 1)      # stdlib FFT: power of two
    c = bin_counts(ts, t0, BIN, n_bins)
    mean, var = statistics.fmean(c), statistics.variance(c)
    pw = periodogram(c)
    level = statistics.fmean(pw[1:len(pw) - 1])
    k = max(range(1, len(pw) - 1), key=lambda i: pw[i])
    ratio = pw[k] / level
    bins = len(pw) - 2
    analytic = 1 - (1 - math.exp(-ratio)) ** bins
    print(f"C. THE SPECTRUM — the counting process in {BIN} s bins")
    print(f"     N = {n_bins} bins of {BIN} s (of {avail} the span allows; the "
          f"FFT here is radix-2)")
    print(f"     mean count {mean:.4f}, variance {var:.4f}, var/mean "
          f"{var / mean:.4f} — Poisson is 1")
    print(f"     mean periodogram level {level:.4f} = the variance — flat, i.e."
          f" white")
    rng = random.Random(seed + 1)
    worse = 0
    for _ in range(trials):
        draw = sorted(F(int(rng.uniform(0, float(span)))) for _ in range(len(ts)))
        p2 = periodogram(bin_counts(draw, F(0), BIN, n_bins))
        lv = statistics.fmean(p2[1:len(p2) - 1])
        if max(p2[1:len(p2) - 1]) / lv >= ratio:
            worse += 1
    P_k = n_bins * float(BIN) / k
    print(f"     loudest bin k={k}: P = N/(k·f_s) = {P_k:.0f} s "
          f"({P_k / 3600:.2f} h) at {ratio:.2f}× the level")
    print(f"       P(any of {bins} white bins that loud) = {analytic:.3f}; "
          f"{worse}/{trials} Poisson")
    print(f"       sets had a louder bin. Nothing here is a tone.")
    comp = dsp.from_fft([complex(z) for z in
                         fft([complex(x - mean) for x in c])],
                        1 / BIN, t0=t0)[k]
    print(f"\n     §9 still names it — honestly, as a measurement and not a tone:")
    print(f"       identity {ic.name(comp.identity)}")
    print(f"       alias    {ic.alias(comp.identity)}")
    fs = 1 / BIN
    print(f"\n     f_s = {fs} Hz puts Nyquist at {dsp.nyquist(fs)} Hz — a period"
          f" of {1 / float(dsp.nyquist(fs)):.0f} s.")
    print(f"     The {TARGET} s target sits exactly *at* f_s, so a true "
          f"{TARGET} s tone aliases to")
    print(f"     {ic.name(dsp.alias_class(F(1, TARGET), fs))}: you cannot see "
          f"Bitcoin's own period in a Bitcoin-paced sampler.")


# --- D. the height axis -----------------------------------------------------


def section_height(retargets: list[list]) -> None:
    rows = [(h1 - h0, (t1 - t0) / (h1 - h0), m1)
            for (t0, h0, _, _), (t1, h1, _, m1)
            in zip(retargets, retargets[1:])]
    full = [(mi, m) for dh, mi, m in rows if dh == EPOCH_BLOCKS]
    mis = [mi for mi, _ in full]
    mult = [m for _, m in full]
    mean = statistics.fmean(mis)
    tip_t, tip_h = retargets[-1][0], retargets[-1][1]
    print(f"D. WHAT IS PERIODIC — the height axis")
    print(f"     {len(retargets)} retargets listed, heights {retargets[0][1]}"
          f"–{tip_h}; {len(full)} of them exactly {EPOCH_BLOCKS} blocks apart")
    print(f"     mean interval per epoch: mean {mean:.1f} s, median "
          f"{statistics.median(mis):.1f} s, sd {statistics.stdev(mis):.1f} s")
    under = sum(1 for x in mis if x < TARGET) / len(mis)
    print(f"     {under:.0%} of epochs ran under {TARGET} s, and {sum(1 for m in mult if m > 1) / len(mult):.0%} "
          f"of retargets were increases:")
    print(f"     hashrate grows *inside* the epoch the retarget is correcting for.")
    lag1 = (statistics.correlation(mis[:-1], mis[1:]) if len(mis) > 30 else
            float("nan"))
    print(f"     lag-1 autocorrelation of the epoch mean: {lag1:+.3f} — the loop"
          f" is always behind")
    print(f"     a trend it never catches, not ringing around the setpoint.")
    print(f"     last 20 epochs: mean {statistics.fmean(mis[-20:]):.1f} s, "
          f"{min(mis[-20:]):.0f}–{max(mis[-20:]):.0f} s")
    print(f"     all-time mean interval, genesis–{tip_h}: "
          f"{(tip_t - GENESIS) / tip_h:.2f} s")
    print(f"\n     The exact periods are counted in blocks. In seconds they are"
          f" ic1:d: durations —")
    print(f"     a period with no epoch anchor and so no phase (§2.5):")
    for nb, label in ((1, "block"), (6, "hour"), (144, "day"),
                      (EPOCH_BLOCKS, "retarget"), (210000, "halving")):
        s = F(nb * TARGET)
        print(f"       {nb:>7} blocks  {label:<9} {str(s):>10} s = "
              f"{float(s) / 86400:9.4f} d   {ic.name(ic.duration(s))}")
    retarget = ic.duration(F(EPOCH_BLOCKS * TARGET))
    print(f"     The retarget target is exactly 14 days: {ic.name(retarget)} = "
          f"{ic.name(ic.caldur(days=14))}")
    print(f"     alias {ic.alias(retarget)}; one nominal block is "
          f"{ic.name(ic.duration(F(TARGET)))}, alias "
          f"{ic.alias(ic.duration(F(TARGET)))}")


# --- main -------------------------------------------------------------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--blocks", type=int, default=EPOCH_BLOCKS,
                    help="how many blocks to analyse (default one retarget "
                         "epoch, 2016 — about 135 requests)")
    ap.add_argument("--tip", type=int,
                    help="pin the top height, so re-runs reproduce exactly")
    ap.add_argument("--resolution", default="1",
                    help="min_resolution in seconds for infer() (default 1)")
    ap.add_argument("--trials", type=int, default=200,
                    help="synthetic Poisson sets per control (default 200)")
    ap.add_argument("--seed", type=int, default=11,
                    help="seed for the controls, so p-values reproduce")
    ap.add_argument("--cache", default=".bitcoin-blocks-cache",
                    help="directory for fetched timestamps")
    ap.add_argument("--dump", action="store_true",
                    help="print the block times as unix seconds and stop")
    args = ap.parse_args(argv)
    cache = Path(args.cache)

    blocks = fetch_blocks(cache, args.tip, args.blocks)
    heights = sorted(blocks)
    if args.dump:
        print("\n".join(str(blocks[h]) for h in heights))
        return 0
    unix = [F(blocks[h]) for h in heights]
    tai = [ic.tai_from_unix(u).t for u in unix]
    res = ic.rat(args.resolution)

    print(f"blocks {heights[0]}–{heights[-1]}  n={len(heights)}  "
          f"span={float(unix[-1] - unix[0]) / 86400:.2f} d")
    print(f"min_resolution={res} s, {args.trials} control sets, seed {args.seed}\n")

    results = ic.infer(tai, min_resolution=res, top_k=3)
    print("the §10 verdict, from the library:")
    if not results:
        print("    no schedule beats chance in this data\n")
    else:  # pragma: no cover - would be news
        for r in results:
            print(f"    {r.human()}  [{r.cron_text or ic.name(r.cls)}]  "
                  f"R̄={r.score:.4f} p={r.p_value:.2e}")
        print()
    print("Why — four ways:\n")
    section_gap(heights, unix)
    print()
    section_phase(unix, args.trials, args.seed)
    print()
    section_spectrum(unix, min(args.trials, 20), args.seed)
    print()
    section_height(fetch_retargets(cache))
    print(f"\nThe decomposition: ic1:always × a Poisson rate, with every exact "
          f"period on an axis")
    print(f"the protocol does not name. 'Every ten minutes' is a rate, not a "
          f"schedule — and")
    print(f"§10 returning nothing is the measurement, not a failure to measure.")
    return 0 if not results else 1


if __name__ == "__main__":
    sys.exit(main())
