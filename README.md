# interval_clock

**Live at [clock.cartercole.com](https://clock.cartercole.com)** · [the
protocol](protocol/PROTOCOL.md) · [playground](https://clock.cartercole.com/playground.html)
· [explore](https://clock.cartercole.com/explore.html)

**An H3 for time.** H3 gives every hexagon on Earth a canonical ID at every
resolution; this project gives a canonical, globally computable name to every
interval and every periodic phase class in existence — hours, days, ISO
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
ic.cell_span(ic.cell("day", 2016, 12, 31)).duration   # Fraction(86401, 1)

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

## Repository layout

```
protocol/PROTOCOL.md     the spec (normative)
python/                  reference library + CLI + REST API + tests
web/                     static site: docs, live clock, playground (TS core)
future/                  v2 stubs: FFT toolkit, schedule inference
```

## Status

v1 implements the core phase-class algebra, encodings, word aliases,
calendar lens, and cron canonicalization (89 tests, including leap seconds,
DST pathologies, and hypothesis property tests). The FFT/Nyquist layer and
schedule inference (pull a blog's publishing schedule out of RSS timestamps)
are fully specified in the protocol and reserved in the encoding, arriving
in v2.

*Planck time (~5.39×10⁻⁴⁴ s) is a documented physical footnote here, not a
tick: it is a measured constant with error bars, while ℚ over the defined SI
second is exact forever. See PROTOCOL.md §1.*
