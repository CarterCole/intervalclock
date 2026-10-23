# interval_clock

**Live at [clock.cartercole.com](https://clock.cartercole.com)** · [the
protocol](protocol/PROTOCOL.md) · [playground](https://clock.cartercole.com/playground.html)
· [explore](https://clock.cartercole.com/explore.html)

**An H3 for time.** H3 gives every hexagon on Earth a canonical ID at every
resolution; this project gives a canonical, globally computable name to every
interval, every periodic phase class, and every step in existence — hours, days, ISO
weeks, every possible cron schedule, "every 1/3 second, state 2", any
rational frequency, and (in the protocol) FFT components of signals extended
forever.

Three deliverables, H3-style:

- **[The protocol](protocol/PROTOCOL.md)** — a standalone spec anyone can
  implement: the math model, canonical text grammar, byte-level ID encoding,
  word-alias derivation, cron normalization, and the FFT/Nyquist and
  schedule-inference layers.
- **The library** — `python/`, the reference implementation, plus a REST API
  (`intervalclock.api`, FastAPI) deployable anywhere.
- **The website** — `web/`, a static site: rendered protocol docs, a live
  interval clock, and an encode/decode playground, all client-side.

## The idea in one paragraph

A periodic schedule is modulo math: at 1/3-second resolution there are 3
states to oscillate between, and an offset carries the phase. The canonical
atom is **Φ(w, m, φ)** — one pulse of width *w* per period *w·m*, anchored at
epoch phase *φ* on the TAI timeline (epoch 1970-01-01 TAI, exact rational
seconds, no resolution floor). The three states of the 1/3-s clock partition
all of time, exactly like H3 children tile their parent; divisibility gives
the full containment lattice (harmonics are ancestors, decimations are
children); boolean combinations close over arc-sets on a circle; a **time
range × a phase class describes a pure sinusoid perfectly** (amplitude is
data, not identity). Calendar and cron names are a versioned *civil lens*
over the physical layer — forced, because future leap seconds are not
computable. Everyone NTP-synced computes the same names; near a slot
boundary the current state is honestly ambiguous and reported as such.

## Quickstart

```bash
cd python
python3 -m venv .venv && .venv/bin/pip install -e '.[api,dev]'

# the user's example: every 1/3 s, state 2 of 3
.venv/bin/intervalclock name --period 1/3 --states 3 --state 2
#   name:  ic1:c:w=1/3;m=3;phi=2/3
#   url:   IC1-2Y00...
#   alias: baby-barely-theory-throw

# canonicalize a cron (*/5 ≡ 0-59/5 ≡ the explicit list — same ID)
.venv/bin/intervalclock name --cron '*/5 * * * *'

# where are we right now?
.venv/bin/intervalclock now --of ic1:c:w=1/3;m=3;phi=0

# a calendar cell and its physical resolution (leap-second aware)
.venv/bin/intervalclock parse 2026-08-01T14

# a step — and that step anchored to a spot in time
.venv/bin/intervalclock name --step P1M --anchor 1662854437
#   name: ic1:n:mo=1@1662854437
#   span: ic1:s:1662854437;1665446437 (30 days — that September)

# run the tests / the REST API
.venv/bin/python -m pytest tests/
.venv/bin/uvicorn intervalclock.api:app
```

```python
from fractions import Fraction as F
import intervalclock as ic

c = ic.phase(F(1, 3), 3, k=2)          # Φ[w=1/3s · m=3 · φ=2/3s] (state 2 of 3)
ic.name(c)                              # 'ic1:c:w=1/3;m=3;phi=2/3'
ic.subset(ic.children(c, 4)[0], c)      # True — children tile the parent
ic.union(*[...])                        # boolean algebra, exact over ℚ
ic.from_cron("0 9 * * 2")               # canonical cron → one ID
ic.cell_span(ic.cell("day", 2016, 12, 31)).duration   # Duration[86401 s]

# durations: the canonical step (§2.5). Exact ones are physical…
ic.duration(F(1, 3)).hz                 # 3
ic.duration(300).grid().slot_at(1000)   # Span[900, 1200) — the 5-minute grid

# …nominal ones are not lengths until you anchor them
sep11 = ic.tai_from_unix(1662854400)
ic.caldur(months=1).seconds_at(sep11)   # 2592000 — 30 days, that September
nye16 = ic.cell_span(ic.cell("day", 2016, 12, 31)).start
ic.caldur(days=1).seconds_at(nye16)     # 86401 — the day a leap second landed
ic.name(ic.caldur(months=1).at(sep11))  # 'ic1:n:mo=1@1662854437' (symbolic)
sep11 + ic.duration(90)                 # Instant — exact steps just add
sep11.plus(ic.caldur(months=1), "America/Chicago")   # nominal: via the lens

# a duration translates any set of time; a class is invariant under its period
every5 = ic.duration(5).phase(2)        # 5 s on, 5 s off, forever
every5 + ic.duration(1)                 # Φ[w=5s · m=2 · φ=1s]
every5 + ic.duration(10) == every5      # True

# events on the interval — blocking generator (also: ic.ticks async, ic.every callback)
for pulse in ic.iter_ticks(c):
    print("state 2 began:", pulse)      # fires on the shared lattice, drift-free
```

```js
// browser/Node (web/lib): EventEmitter over a named class
import { PhaseEmitter, setIntervalClock } from "./lib/ticker.js";

const em = new PhaseEmitter(parse("ic1:c:w=1/3;m=3;phi=2/3"));
em.addEventListener("pulse", (e) => console.log("state 2:", e.detail.start));

// or setInterval, but the interval is a name on the shared timeline:
setIntervalClock(() => console.log("tick"), "1/3");   // aligned across machines
```

Every machine running the same name fires at the same instants (± NTP error):
the wait is re-derived from the epoch-anchored lattice before each event, so
nothing drifts — unlike `setInterval`, which is relative to whenever you
happened to call it.

## Worked example: the NIST Randomness Beacon

The [NIST beacon](https://beacon.nist.gov) has published one pulse a minute
since 2013. [`python/examples/nist_beacon.py`](python/examples/nist_beacon.py)
pulls its recent pulses and runs inference over them:

```
every 1 min at +37 s
  name:   ic1:c:w=1;m=60;phi=73/2
  url:    IC1-2H04W0000000000104Y4J0G
  alias:  town-amused-mention-offer
  phase:  φ = 73/2 s, pulse centre at TAI ≡ 37 (mod 60)
  fit:    R̄=1.000000  p=3.20e-47  matched=100%  jitter=±0s
```

Then it checks that class against pulses from the beacon's whole history,
and the physical name turns out to be era-stamped:

```
probe                                     UTC                  unix%60  TAI−UTC  TAI%60  in ic1:c:w=1;m=60;phi=73/2?
v1.0         2014-01-01 (TAI−UTC = 35)    2014-01-01 00:00:00        0       35      35  OUTSIDE
v1.0         2016-01-01 (TAI−UTC = 36)    2016-01-01 00:00:00        0       36      36  OUTSIDE
v1.0         2018-01-01 (TAI−UTC = 37)    2018-01-01 00:00:00        0       37      37  inside
v2 chain 1   pulse 1                      2018-07-23 19:26:00        0       37      37  inside
v2 chain 2   pulse 1                      2022-09-21 19:32:00        0       37      37  inside
```

Every pulse ever published lands on `unix % 60 == 0` — the beacon is locked
to UTC — but the timeline is TAI, so each leap second moved the pulse one
residue along the 60-second circle: 35 until mid-2015, 36 until the end of
2016, 37 since. `ic1:c:w=1;m=60;phi=73/2` is the exact Layer-A name of the
beacon *in the current era*, and the next leap second will change it. The
name that survives is the Layer-B one, cron `* * * * *` (`ic1:k:*|*|*|*|*`).
That is the two-layer split of [§5](protocol/PROTOCOL.md) and
[§11](protocol/PROTOCOL.md) showing up in real data: a civil schedule is
not a phase class, and no amount of fit (R̄ = 1 on 120 pulses) makes it one.

## Worked example: Bitcoin's ten-minute block, which is not a schedule

The beacon is a schedule with a perfect fit. The other half of
[§10](protocol/PROTOCOL.md) is knowing when to return nothing, and Bitcoin's
famous ten-minute block is the cleanest case there is.
[`python/examples/bitcoin_blocks.py`](python/examples/bitcoin_blocks.py) pulls
real block timestamps from mempool.space and folds them:

```
$ python3 examples/bitcoin_blocks.py --tip 972800 --blocks 9072
blocks 963729–972800  n=9072  span=61.13 d

the §10 verdict, from the library:
    no schedule beats chance in this data
```

That is the measurement, not a failure to measure. A schedule is a period *and
a phase*; the block interval has a rate and no phase at all, and the example
shows that four ways.

**The gap is memoryless.** Median 407.0 s against ln2·mean = 403.6 s, CV =
1.020, and `E[gap − s | gap > s]` ≈ 590 s whether you have already waited zero
seconds or forty minutes. It is exponential *per retarget epoch* (KS p =
0.14–0.35 for each of the five in the window); pooled over two months the same
test gives p = 0.001, purely because the rate drifts between epochs. That is a
mixture of exponentials, not a schedule.

**Nothing concentrates at any period.** Each candidate is folded against 200
synthetic homogeneous-Poisson sets of the same n and span:

```
       period   cycles       R̄  Rayleigh p  empirical p
        600 s   8802.6   0.0093      0.4599        0.450
        1 hour   1467.1  0.0066      0.6735        0.695
        1 day     61.1   0.0178      0.0563        0.050
        1 week      8.7  0.0335      0.0000        0.245
      retarget     4.4   0.0616      0.0000        0.740
```

The 600 s fold *is* the noise floor (E[R̄] = 0.0093 for 9072 unscheduled
events). The last two rows are why §10 stops candidates at span/3 and
Bonferroni-adjusts the rest: the asymptotic Rayleigh p-value reads 0.0000 for
a period the span covers four times, and the control says 0.740.

**The spectrum is white.** Binned into 600 s cells the arrival process has
var/mean = 1.011, a flat periodogram, and a loudest bin 8.2× the mean level —
which 12 of 20 simulated Poisson sets beat. [§9](protocol/PROTOCOL.md) names
that bin anyway, honestly, as a measurement rather than a tone. One structural
joke falls out: sampling at 1/600 Hz puts Nyquist at 1/1200 Hz, so the 600 s
target sits exactly *at* f_s and a true 600 s tone would alias to
`ic1:always`. You cannot see Bitcoin's own period in a Bitcoin-paced sampler.

**What is exactly periodic is counted in blocks, not seconds.** One block,
2016 (a retarget), 210000 (a halving) — those are exact. In seconds they are
[§2.5](protocol/PROTOCOL.md) *durations*, a period with no epoch anchor and so
no phase: `ic1:d:600`, `ic1:d:1209600` (= `ic1:n:d=14`, exactly 14 days),
`ic1:d:126000000`. Across all 466 full retarget epochs the mean interval is
564.2 s with 76% of epochs under 600 s, and the lag-1 autocorrelation of the
epoch mean is +0.56: the retarget corrects for an epoch that has ended while
hashrate keeps growing through the next one, so the loop is always behind a
trend it never catches. The 600 s target is a setpoint, not a clock anyone
keeps.

The decomposition, in the protocol's own terms: `ic1:always` × a Poisson rate,
with every exact period on an axis the protocol does not name.

## Repository layout

```
protocol/PROTOCOL.md     the spec (normative)
python/                  reference library + CLI + REST API + tests
python/examples/         worked examples against live data (NIST beacon,
                         Bitcoin blocks)
web/                     static site: docs, live clock, playground (TS core)
future/                  what is still only specified, not built
```

## Status

The core phase-class algebra, encodings, word aliases, calendar lens, and
cron canonicalization all ship, as do the two v2 layers: the FFT/Nyquist
mapping (`dsp.py`, binary type 0x8 and the `f:` text form) and schedule
inference (`infer.py` — point it at a blog's publication timestamps and it
answers "every Tuesday ~09:00"). The duration layer ships too (`duration.py`,
types 0xA–0xC, the `d:` and `n:` text forms): an exact physical step, a
nominal one that only becomes a length against an anchor, and the grid a
step generates. 216 tests, including leap seconds, DST pathologies,
byte-parity cross-tests against the browser core, and hypothesis property
tests.

```python
from intervalclock import infer, tai_from_unix, to_cron
results = infer([tai_from_unix(u) for u in unix_timestamps], min_resolution=60)
print(results[0].human(), "→", to_cron(results[0].cls))
```

Still unbuilt: the optional proleptic-UTC lens that would compile cron to a
400-year PSet (PROTOCOL.md §11.2). Inference runs in Python only; the
browser core carries the FFT encodings but not the analysis.

*Planck time (~5.39×10⁻⁴⁴ s) is a documented physical footnote here, not a
tick: it is a measured constant with error bars, while ℚ over the defined SI
second is exact forever. See PROTOCOL.md §1.*
