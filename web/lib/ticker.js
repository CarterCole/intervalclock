// Emit events on a named class's occurrences (twin of ticker.py).
//
// Epoch-anchored and drift-free: every timeout is recomputed from the
// current clock against the shared timeline, so two browsers running the
// same name fire in lockstep (± NTP error ± timer jitter).
//
//   import { ticker } from "./lib/ticker.js";
//   const t = ticker(phase(Frac.parse("1/3"), 3, {k: 2}),
//                    (pulse) => console.log("state 2 began", pulse.start));
//   t.stop();

import { nextPulse, phase, PhaseClass, PSet, Windowed } from "./core.js";
import { nowTai } from "./timescale.js";
import { Frac, F } from "./rat.js";
import { parse } from "./names.js";

// EventEmitter style: a browser/Node-native EventTarget that dispatches a
// "pulse" CustomEvent on every occurrence.
//
//   const em = new PhaseEmitter(cls);
//   em.addEventListener("pulse", (e) => console.log(e.detail.start));
//   em.stop();
export class PhaseEmitter extends EventTarget {
  constructor(cls, opts = {}) {
    super();
    this.cls = cls;
    this._t = ticker(cls, (pulse) => {
      this.dispatchEvent(new CustomEvent("pulse", { detail: pulse }));
    }, opts);
  }
  stop() {
    this._t.stop();
  }
}

// Async-iterator style: `for await (const pulse of pulses(cls)) ...`
export async function* pulses(cls, { lead = 0 } = {}) {
  let lastFired = null;
  for (;;) {
    const t = nowTai();
    const q = lastFired && lastFired.cmp(t) > 0 ? lastFired : t;
    const nxt = nextOccurrence(cls, q); // strictly after q — no duplicates
    if (!nxt) return;
    const delayMs = nxt.start.sub(t).toNumber() * 1000 - lead;
    if (delayMs > 0) await new Promise((r) => setTimeout(r, delayMs));
    lastFired = nxt.start;
    yield nxt;
  }
}

// Support-aware next: a Windowed class stops emitting past its support.
function nextOccurrence(cls, t) {
  if (cls instanceof Windowed) {
    let p = nextPulse(cls.cls, t);
    while (p && p.end.cmp(cls.support.start) <= 0) p = nextPulse(cls.cls, p.start);
    if (!p || p.start.cmp(cls.support.end) >= 0) return null;
    return p;
  }
  return nextPulse(cls, t);
}

// setInterval, but the interval is a NAME on the shared timeline.
//
//   const h = setIntervalClock(() => console.log("tick"), "1/3");     // every 1/3 s
//   const h2 = setIntervalClock(fn, 250);                              // every 250 ms
//   const h3 = setIntervalClock(fn, "ic1:c:w=1/3;m=3;phi=2/3");        // a named class
//   clearIntervalClock(h);
//
// Unlike setInterval, firings land on the epoch-anchored lattice: aligned
// across every machine running the same spec, and drift-free (each wait is
// re-derived from the clock). A number is milliseconds for familiarity; a
// string is either a rational period in seconds ("1/3") or an ic1: name.
export function setIntervalClock(callback, spec, opts = {}) {
  let cls;
  if (typeof spec === "number") {
    const P = new Frac(BigInt(Math.round(spec)), 1000n);
    cls = phase(P.div(F(2n)), 2, {});
  } else if (typeof spec === "string") {
    if (spec.startsWith("ic1:")) {
      cls = parse(spec);
    } else {
      const P = Frac.parse(spec);
      cls = phase(P.div(F(2n)), 2, {});
    }
  } else {
    cls = spec;
  }
  if (!(cls instanceof PhaseClass || cls instanceof PSet || cls instanceof Windowed)) {
    throw new Error("setIntervalClock needs a periodic class, a period, or ms");
  }
  return ticker(cls, callback, opts);
}

export function clearIntervalClock(handle) {
  handle?.stop?.();
}

export function ticker(cls, callback, { lead = 0 } = {}) {
  let stopped = false;
  let timer = null;
  let lastFired = null; // guard: timers can fire early; never re-fire a pulse

  function arm() {
    if (stopped) return;
    const t = nowTai();
    const q = lastFired && lastFired.cmp(t) > 0 ? lastFired : t;
    const nxt = nextOccurrence(cls, q); // strictly after q — no duplicates
    if (!nxt) return; // no further occurrences
    const delayMs = nxt.start.sub(t).toNumber() * 1000 - lead;
    timer = setTimeout(() => {
      if (stopped) return;
      lastFired = nxt.start;
      callback(nxt);
      arm(); // re-derive from the clock — never accumulate drift
    }, Math.max(delayMs, 0));
  }

  arm();
  return {
    stop() {
      stopped = true;
      clearTimeout(timer);
    },
  };
}
