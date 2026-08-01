// Canonical cron for the browser (twin of cron.py): bitset DNF, Vixie
// dom/dow OR split, impossible-record pruning, subsumption, greedy text.

const RANGES = { minute: [0, 59], hour: [0, 23], dom: [1, 31], month: [1, 12], dow: [0, 6] };
const MONTHS = Object.fromEntries("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(" ").map((n, i) => [n, i + 1]));
const DOWS = Object.fromEntries("SUN MON TUE WED THU FRI SAT".split(" ").map((n, i) => [n, i]));
const DAYS_IN_MONTH = [null, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

function full(field) {
  const [lo, hi] = RANGES[field];
  return ((1n << BigInt(hi + 1)) - 1n) & ~((1n << BigInt(lo)) - 1n);
}
export const FULL = Object.fromEntries(Object.keys(RANGES).map((f) => [f, full(f)]));

export function parseField(text, field) {
  const [lo, hi] = RANGES[field];
  const names = field === "month" ? MONTHS : field === "dow" ? DOWS : {};
  const value = (tok) => {
    const t = tok.toUpperCase();
    if (t in names) return names[t];
    let v = parseInt(tok, 10);
    if (Number.isNaN(v)) throw new Error(`bad ${field} value ${tok}`);
    if (field === "dow" && v === 7) v = 0;
    if (v < lo || v > hi) throw new Error(`${field} value ${tok} out of range`);
    return v;
  };
  let mask = 0n;
  for (const termRaw of text.split(",")) {
    if (!termRaw) throw new Error(`empty term in ${field}`);
    let term = termRaw, step = 1;
    if (term.includes("/")) {
      const [t, s] = term.split("/");
      term = t;
      step = parseInt(s, 10);
      if (!(step >= 1)) throw new Error("step must be ≥ 1");
    }
    let a, b;
    if (term === "*") [a, b] = [lo, hi];
    else if (term.includes("-")) {
      const [x, y] = term.split("-");
      a = value(x); b = value(y);
      if (b < a) throw new Error(`inverted range ${term}`);
    } else {
      a = value(term);
      b = step > 1 ? hi : a; // Vixie: N/step extends to the top
    }
    for (let v = a; v <= b; v += step) mask |= 1n << BigInt(v);
  }
  return mask;
}

const bit = (mask, i) => (mask >> BigInt(i)) & 1n;

function recordPossible(r) {
  if (!r.minute || !r.hour || !r.month || !r.dom || !r.dow) return false;
  if (r.dow !== FULL.dow) return true;
  for (let mo = 1; mo <= 12; mo++) {
    if (!bit(r.month, mo)) continue;
    for (let d = 1; d <= DAYS_IN_MONTH[mo]; d++) if (bit(r.dom, d)) return true;
  }
  return false;
}

function subsumes(a, b) {
  return ["minute", "hour", "dom", "month", "dow"].every((f) => (b[f] & ~a[f]) === 0n);
}

export function recordBytes(r) {
  const out = new Uint8Array(18);
  const put = (mask, off, len) => {
    for (let i = 0; i < len; i++) out[off + len - 1 - i] = Number((mask >> BigInt(8 * i)) & 0xffn);
  };
  put(r.minute, 0, 8); put(r.hour, 8, 3); put(r.dom, 11, 4); put(r.month, 15, 2); put(r.dow, 17, 1);
  return out;
}

export function recordFromBytes(b) {
  const get = (off, len) => {
    let m = 0n;
    for (let i = 0; i < len; i++) m = (m << 8n) | BigInt(b[off + i]);
    return m;
  };
  return { minute: get(0, 8), hour: get(8, 3), dom: get(11, 4), month: get(15, 2), dow: get(17, 1) };
}

const cmpBytes = (x, y) => {
  for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] - y[i];
  return 0;
};

export function fromCron(expr, zone = "UTC") {
  const f = expr.trim().split(/\s+/);
  if (f.length !== 5) throw new Error("cron needs 5 fields");
  const minute = parseField(f[0], "minute"), hour = parseField(f[1], "hour");
  const dom = parseField(f[2], "dom"), month = parseField(f[3], "month"), dow = parseField(f[4], "dow");
  const domR = f[2] !== "*" && dom !== FULL.dom;
  const dowR = f[4] !== "*" && dow !== FULL.dow;
  let records = domR && dowR
    ? [{ minute, hour, dom, month, dow: FULL.dow }, { minute, hour, dom: FULL.dom, month, dow }]
    : [{ minute, hour, dom, month, dow }];
  records = records.filter(recordPossible);
  const kept = [];
  for (const r of records) {
    const others = records.filter((o) => o !== r);
    if (others.some((o) => subsumes(o, r)) && !others.some((o) => subsumes(r, o))) continue;
    if (!kept.some((o) => subsumes(o, r) && subsumes(r, o))) kept.push(r);
  }
  if (!kept.length) return { type: "never" };
  kept.sort((a, b) => cmpBytes(recordBytes(a), recordBytes(b)));
  return { type: "cron", records: kept, zone };
}

export function renderField(mask, field) {
  const [lo, hi] = RANGES[field];
  if (mask === FULL[field]) return "*";
  const elems = [];
  for (let v = lo; v <= hi; v++) if (bit(mask, v)) elems.push(v);
  const covered = new Set();
  const parts = [];
  for (const e of elems) {
    if (covered.has(e)) continue;
    let bestLen = 1, bestStep = 1;
    for (let step = 1; step <= hi - e; step++) {
      let n = 1, v = e + step;
      while (v <= hi && bit(mask, v)) { n++; v += step; }
      if (n > bestLen) { bestLen = n; bestStep = step; }
    }
    let run = Array.from({ length: bestLen }, (_, i) => e + i * bestStep);
    if (bestLen === 1) parts.push(`${e}`);
    else if (bestStep === 1) parts.push(`${run[0]}-${run[run.length - 1]}`);
    else if (bestLen >= 3) parts.push(`${run[0]}-${run[run.length - 1]}/${bestStep}`);
    else { parts.push(`${e}`); run = [e]; }
    run.forEach((v) => covered.add(v));
  }
  return parts.join(",");
}

export function recordText(r) {
  return [renderField(r.minute, "minute"), renderField(r.hour, "hour"),
    renderField(r.dom, "dom"), renderField(r.month, "month"),
    renderField(r.dow, "dow")].join("|");
}

export function cronName(s) {
  const body = s.records.map(recordText).join("+");
  return `ic1:k:${body}${s.zone === "UTC" ? "" : "!" + s.zone}`;
}

export function parseCronBody(body) {
  let zone = "UTC";
  const bang = body.indexOf("!");
  if (bang >= 0) { zone = body.slice(bang + 1); body = body.slice(0, bang); }
  const records = body.split("+").map((rec) => {
    const f = rec.split("|");
    if (f.length !== 5) throw new Error("cron record needs 5 fields");
    return {
      minute: parseField(f[0], "minute"), hour: parseField(f[1], "hour"),
      dom: parseField(f[2], "dom"), month: parseField(f[3], "month"),
      dow: parseField(f[4], "dow"),
    };
  });
  records.sort((a, b) => cmpBytes(recordBytes(a), recordBytes(b)));
  return { type: "cron", records, zone };
}

// Matching against a civil wall-clock reading (UTC lens on the site).
export function cronMatches(s, { minute, hour, day, month, dowSun0 }) {
  return s.records.some((r) =>
    bit(r.minute, minute) && bit(r.hour, hour) && bit(r.dom, day)
    && bit(r.month, month) && bit(r.dow, dowSun0));
}

// Next firing strictly after TAI instant t, as {start, end} Fracs — the
// physical span of the fired minute (61 s across a leap second, for free).
// UTC lens only in the browser; other zones resolve via the library/REST.
export function cronNextAfter(s, t) {
  if (s.zone !== "UTC") {
    throw new Error("browser resolves UTC crons only — use the library/REST for zones");
  }
  const { taiFromUnix, unixFromTai } = tsMod;
  const { unix } = unixFromTai(t);
  // start from the next minute boundary at-or-after t
  let ms = (Number(unix.floor()) + 60) * 1000;
  ms = Math.floor(ms / 60000) * 60000;
  const limitMs = ms + 366 * 5 * 86400000;
  while (ms < limitMs) {
    const d = new Date(ms);
    const month = d.getUTCMonth() + 1;
    if (!s.records.some((r) => bit(r.month, month))) {
      ms = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1);
      continue;
    }
    const day = d.getUTCDate(), dowSun0 = d.getUTCDay();
    if (!s.records.some((r) => bit(r.month, month) && bit(r.dom, day) && bit(r.dow, dowSun0))) {
      ms = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), day + 1);
      continue;
    }
    const hour = d.getUTCHours();
    if (!s.records.some((r) => bit(r.month, month) && bit(r.dom, day)
        && bit(r.dow, dowSun0) && bit(r.hour, hour))) {
      ms = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), day, hour + 1);
      continue;
    }
    if (cronMatches(s, { minute: d.getUTCMinutes(), hour, day, month, dowSun0 })) {
      const unixMin = BigInt(ms / 1000);
      const start = taiFromUnix(new Frac2(unixMin));
      if (start.cmp(t) > 0) {
        return { start, end: taiFromUnix(new Frac2(unixMin + 60n)) };
      }
    }
    ms += 60000;
  }
  return null;
}

// deferred import to avoid a cycle at module-eval time
import * as tsMod from "./timescale.js";
import { Frac as Frac2 } from "./rat.js";
