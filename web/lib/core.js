// The phase-class algebra for the browser (twin of core.py — the subset the
// site needs: canonical Φ, one-arc PSets, spans, windowed, names, occurrences,
// children/harmonics).

import { Frac, F, ZERO, rgcd } from "./rat.js";

export const ALWAYS = { type: "always", contains: () => true };
export const NEVER = { type: "never", contains: () => false };

export class Span {
  constructor(start, end) {
    if (!start.lt(end)) throw new Error("span requires start < end");
    this.type = "span";
    this.start = start;
    this.end = end;
  }
  get duration() { return this.end.sub(this.start); }
  contains(t) { return this.start.le(t) && t.lt(this.end); }
}

export class Instant {
  constructor(t) { this.type = "instant"; this.t = t; }
  contains(t) { return this.t.eq(t); }
}

export class PhaseClass {
  constructor(w, m, phi) { // use phase() — this trusts canonical inputs
    this.type = "phase";
    this.w = w;
    this.m = m;
    this.phi = phi;
  }
  get period() { return this.w.mul(F(BigInt(this.m))); }
  get state() { // display sugar: k when φ is on the w-grid
    const q = this.phi.div(this.w);
    return q.d === 1n ? Number(q.n) : null;
  }
  contains(t) { return t.sub(this.phi).mod(this.period).lt(this.w); }
  eq(o) {
    return o instanceof PhaseClass && this.w.eq(o.w) && this.m === o.m
      && this.phi.eq(o.phi);
  }
}

export class PSet {
  constructor(period, arcs) { // arcs: [{s, w}] canonical
    this.type = "pset";
    this.period = period;
    this.arcs = arcs;
  }
  contains(t) {
    const r = t.mod(this.period);
    return this.arcs.some(({ s, w }) => {
      if (s.le(r) && r.lt(s.add(w))) return true;
      const wrap = s.add(w).sub(this.period);
      return wrap.cmp(ZERO) > 0 && r.lt(wrap);
    });
  }
}

export class Windowed {
  constructor(support, cls) {
    this.type = "windowed";
    this.support = support;
    this.cls = cls;
  }
  contains(t) { return this.support.contains(t) && this.cls.contains(t); }
}

// Canonical constructor: φ = (phi + δ + k·w) mod P; m = 1 → ALWAYS.
export function phase(w, m, { phi = ZERO, k = 0, delta = ZERO } = {}) {
  if (w.cmp(ZERO) <= 0) throw new Error("slot width must be positive");
  if (!Number.isInteger(m) || m < 1) throw new Error("modulus must be a positive integer");
  if (m === 1) return ALWAYS;
  const P = w.mul(F(BigInt(m)));
  const canon = phi.add(delta).add(w.mul(F(BigInt(k)))).mod(P);
  return new PhaseClass(w, m, canon);
}

export function pset(P, arcs) {
  // Minimal canonicalizer for the site: normalize, merge, collapse.
  if (P.cmp(ZERO) <= 0) throw new Error("period must be positive");
  let segs = [];
  for (let { s, w } of arcs) {
    if (w.cmp(ZERO) <= 0) continue;
    if (w.cmp(P) >= 0) return ALWAYS;
    s = s.mod(P);
    const e = s.add(w);
    if (e.cmp(P) <= 0) segs.push([s, e]);
    else { segs.push([s, P]); segs.push([ZERO, e.sub(P)]); }
  }
  segs.sort((a, b) => a[0].cmp(b[0]));
  const merged = [];
  for (const [a, b] of segs) {
    const last = merged[merged.length - 1];
    if (last && a.cmp(last[1]) <= 0) {
      if (b.cmp(last[1]) > 0) last[1] = b;
    } else merged.push([a, b]);
  }
  if (!merged.length) return NEVER;
  if (merged.length === 1 && merged[0][0].isZero() && merged[0][1].eq(P)) return ALWAYS;
  // wrap-merge across 0
  let out = merged;
  if (out.length >= 2 && out[0][0].isZero() && out[out.length - 1][1].eq(P)) {
    const first = out.shift();
    const last = out.pop();
    out.push([last[0], last[1].add(first[1].sub(first[0]))]);
  }
  const carcs = out.map(([a, b]) => ({ s: a.mod(P), w: b.sub(a) }));
  if (carcs.length === 1) {
    const { s, w } = carcs[0];
    const q = P.div(w);
    if (q.d === 1n && q.n >= 2n) return new PhaseClass(w, Number(q.n), s);
  }
  carcs.sort((a, b) => a.s.cmp(b.s));
  return new PSet(P, carcs);
}

export function windowed(support, cls) {
  if (cls === ALWAYS) return support;
  if (cls === NEVER) return NEVER;
  const first = nextPulse(cls, support.start, false);
  const cover = pulseCovering(cls, support.start);
  if (!cover && (!first || first.start.cmp(support.end) >= 0)) return NEVER;
  return new Windowed(support, cls);
}

// --- occurrences ------------------------------------------------------------

function pulses(x) {
  if (x instanceof PhaseClass) return { P: x.period, arcs: [{ s: x.phi, w: x.w }] };
  if (x instanceof PSet) return { P: x.period, arcs: x.arcs };
  throw new Error("not periodic");
}

export function nextPulse(x, t, strict = true) {
  const { P, arcs } = pulses(x);
  let best = null;
  for (const { s, w } of arcs) {
    let start = s.add(P.mul(new Frac(t.sub(s).div(P).floor())));
    while (strict ? start.cmp(t) <= 0 : start.cmp(t) < 0) start = start.add(P);
    if (!best || start.cmp(best.start) < 0) best = { start, end: start.add(w) };
  }
  return best;
}

export function prevPulse(x, t, strict = true) {
  const { P, arcs } = pulses(x);
  let best = null;
  for (const { s, w } of arcs) {
    let start = s.add(P.mul(new Frac(t.sub(s).div(P).floor()))).add(P);
    while (strict ? start.cmp(t) >= 0 : start.cmp(t) > 0) start = start.sub(P);
    if (!best || start.cmp(best.start) > 0) best = { start, end: start.add(w) };
  }
  return best;
}

export function pulseCovering(x, t) {
  const p = prevPulse(x, t, false);
  return p && p.start.le(t) && t.lt(p.end) ? p : null;
}

export function stateAt(w, m, t, err = null) {
  const slot = t.div(w).floor();
  const mm = BigInt(m);
  const norm = (v) => Number(((v % mm) + mm) % mm);
  const states = [norm(slot)];
  if (err && !err.isZero()) {
    if (t.sub(w.mul(new Frac(slot))).lt(err)) states.unshift(norm(slot - 1n));
    if (w.mul(new Frac(slot + 1n)).sub(t).lt(err)) states.push(norm(slot + 1n));
  }
  return [...new Set(states)];
}

// --- lattice (phase classes) -----------------------------------------------

export function children(x, c, axis = "decimate") {
  if (!(x instanceof PhaseClass)) throw new Error("children() needs a phase class");
  const out = [];
  if (axis === "decimate") {
    const P = x.period;
    for (let i = 0; i < c; i++) {
      out.push(phase(x.w, x.m * c, { phi: x.phi.add(P.mul(F(BigInt(i)))) }));
    }
  } else {
    const wc = x.w.div(F(BigInt(c)));
    for (let i = 0; i < c; i++) {
      out.push(phase(wc, x.m * c, { phi: x.phi.add(wc.mul(F(BigInt(i)))) }));
    }
  }
  return out;
}

export function harmonics(x, n) {
  if (!(x instanceof PhaseClass)) throw new Error("harmonics() needs a phase class");
  if (x.m % n) throw new Error(`harmonic requires n | m (n=${n}, m=${x.m})`);
  const mp = x.m / n;
  if (mp === 1) return ALWAYS;
  return phase(x.w, mp, { phi: x.phi.mod(x.w.mul(F(BigInt(mp)))) });
}

// --- boolean algebra (twin of core.py's circle-set machinery) ---------------

import { rlcm } from "./rat.js";

function segmentsOf(P, arcs) {
  // arcs on circle P → disjoint sorted linear segments in [0, P)
  let segs = [];
  for (let { s, w } of arcs) {
    if (w.cmp(ZERO) <= 0) continue;
    if (w.cmp(P) >= 0) return [[ZERO, P]];
    s = s.mod(P);
    const e = s.add(w);
    if (e.cmp(P) <= 0) segs.push([s, e]);
    else { segs.push([s, P]); segs.push([ZERO, e.sub(P)]); }
  }
  segs.sort((a, b) => a[0].cmp(b[0]));
  const out = [];
  for (const [a, b] of segs) {
    const last = out[out.length - 1];
    if (last && a.cmp(last[1]) <= 0) { if (b.cmp(last[1]) > 0) last[1] = b; }
    else out.push([a, b]);
  }
  return out;
}

function liftArcs(x, L) {
  const { P, arcs } = x instanceof PhaseClass
    ? { P: x.period, arcs: [{ s: x.phi, w: x.w }] }
    : { P: x.period, arcs: x.arcs };
  const n = Number(L.div(P).n); // integral by construction
  const out = [];
  for (const { s, w } of arcs) {
    for (let i = 0; i < n; i++) out.push({ s: s.add(P.mul(F(BigInt(i)))).mod(L), w });
  }
  return out;
}

const isPeriodic = (x) => x instanceof PhaseClass || x instanceof PSet;

export function union(a, b) {
  if (a === ALWAYS || b === ALWAYS) return ALWAYS;
  if (a === NEVER) return b;
  if (b === NEVER) return a;
  if (!isPeriodic(a) || !isPeriodic(b)) throw new Error("union needs periodic classes");
  const L = rlcm(a.period, b.period);
  const segs = [...segmentsOf(L, liftArcs(a, L)), ...segmentsOf(L, liftArcs(b, L))];
  return pset(L, segs.map(([s, e]) => ({ s, w: e.sub(s) })));
}

export function intersect(a, b) {
  if (a === NEVER || b === NEVER) return NEVER;
  if (a === ALWAYS) return b;
  if (b === ALWAYS) return a;
  if (a instanceof Span && b instanceof Span) {
    const s = a.start.cmp(b.start) > 0 ? a.start : b.start;
    const e = a.end.cmp(b.end) < 0 ? a.end : b.end;
    return s.lt(e) ? new Span(s, e) : NEVER;
  }
  if (a instanceof Span && isPeriodic(b)) return windowed(a, b);
  if (b instanceof Span && isPeriodic(a)) return windowed(b, a);
  if (a instanceof Windowed || b instanceof Windowed) {
    const aw = a instanceof Windowed ? a : null;
    const bw = b instanceof Windowed ? b : null;
    if (aw && bw) {
      const sp = intersect(aw.support, bw.support);
      if (sp === NEVER) return NEVER;
      return windowed(sp, intersect(aw.cls, bw.cls));
    }
    const [wnd, other] = aw ? [aw, b] : [bw, a];
    if (other instanceof Span) return windowed(intersect(wnd.support, other), wnd.cls);
    return windowed(wnd.support, intersect(wnd.cls, other));
  }
  if (!isPeriodic(a) || !isPeriodic(b)) throw new Error("cannot intersect these types");
  const L = rlcm(a.period, b.period);
  const sa = segmentsOf(L, liftArcs(a, L));
  const sb = segmentsOf(L, liftArcs(b, L));
  const out = [];
  for (const [a1, a2] of sa) {
    for (const [b1, b2] of sb) {
      const lo = a1.cmp(b1) > 0 ? a1 : b1;
      const hi = a2.cmp(b2) < 0 ? a2 : b2;
      if (lo.lt(hi)) out.push({ s: lo, w: hi.sub(lo) });
    }
  }
  return pset(L, out);
}

export function complement(x) {
  if (x === ALWAYS) return NEVER;
  if (x === NEVER) return ALWAYS;
  if (!isPeriodic(x)) throw new Error("complement needs a periodic class");
  const P = x.period;
  const segs = segmentsOf(P, liftArcs(x, P));
  const out = [];
  let cursor = ZERO;
  for (const [a, b] of segs) {
    if (cursor.lt(a)) out.push({ s: cursor, w: a.sub(cursor) });
    cursor = b;
  }
  if (cursor.lt(P)) out.push({ s: cursor, w: P.sub(cursor) });
  return pset(P, out);
}

// Exact Φ×Φ subset via the orbit predicate.
export function phaseSubset(a, b) {
  if (a.w.cmp(b.w) > 0) return false;
  const g = rgcd(a.period, b.period);
  const count = Number(b.period.div(g).n); // integral by construction
  const slack = b.w.sub(a.w);
  let r = a.phi.mod(b.period);
  for (let j = 0; j < count; j++) {
    if (r.sub(b.phi).mod(b.period).cmp(slack) > 0) return false;
    r = r.add(g).mod(b.period);
  }
  return true;
}
