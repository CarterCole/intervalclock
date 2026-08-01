// Ticker behavior test: events land on the epoch-anchored lattice.
// Run: node web/test/ticker.mjs

import { Frac, F } from "../lib/rat.js";
import { phase } from "../lib/core.js";
import {
  ticker, PhaseEmitter, pulses, setIntervalClock, clearIntervalClock,
} from "../lib/ticker.js";

const FAST = phase(Frac.parse("1/50"), 2); // period 1/25 s
const PERIOD = Frac.parse("1/25");

const fail = (msg) => { console.error("FAIL", msg); process.exit(1); };

// callback style — spacing exact, epoch-anchored, and NO duplicate firings
const got = [];
await new Promise((resolve) => {
  const t = ticker(FAST, (pulse) => {
    got.push(pulse);
    if (got.length === 5) { t.stop(); resolve(); }
  });
});
const starts = got.map((p) => p.start.toString());
if (new Set(starts).size !== starts.length) fail(`duplicate firings: ${starts}`);
if (!got[1].start.sub(got[0].start).eq(PERIOD)) fail("callback spacing");
if (got[0].start.div(PERIOD).d !== 1n) fail("callback not epoch-anchored");

// async-iterator style
let prev = null;
for await (const pulse of pulses(FAST)) {
  if (prev) {
    if (!pulse.start.sub(prev.start).eq(PERIOD)) fail("async-iter spacing");
    break;
  }
  prev = pulse;
}

// EventEmitter style
await new Promise((resolve) => {
  const em = new PhaseEmitter(FAST);
  em.addEventListener("pulse", (e) => {
    if (!e.detail.start || e.detail.start.div(PERIOD).d !== 1n) fail("emitter detail");
    em.stop();
    resolve();
  });
});

// setInterval-shaped API: "1/25" period string lands on the same lattice
await new Promise((resolve) => {
  const h = setIntervalClock((pulse) => {
    if (pulse.start.div(Frac.parse("1/25")).d !== 1n) fail("setIntervalClock lattice");
    clearIntervalClock(h);
    resolve();
  }, "1/25");
});

console.log("TICKER TESTS PASSED (callback, async-iterator, EventEmitter, setIntervalClock — all epoch-anchored)");
