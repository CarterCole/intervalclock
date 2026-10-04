// Durations: the canonical step in time (PROTOCOL.md §2.5) — the browser
// twin of python's duration.py. A duration is a *measure*, not a set of
// time: the translation-invariance class of a Span.
//
// Two layers, same forcing as the calendar lens: an exact physical step in
// ℚ seconds, and a nominal step (months, days, exact tail) that is not a
// length at all until it is anchored. As in cells.js, the browser resolves
// the UTC lens only; other zones stay symbolic here and resolve in the
// library / REST API.

import { F, Frac } from "./rat.js";
import { Span } from "./core.js";
import { taiFromUnix, unixFromTai } from "./timescale.js";

export const duration = (d) => ({ type: "duration", d });

export function caldur({ years = 0, months = 0, weeks = 0, days = 0,
  hours = 0, minutes = 0, seconds = F(0n) } = {}) {
  const mo = Number(years) * 12 + Number(months);
  const d = Number(weeks) * 7 + Number(days);
  const tail = F(BigInt(hours) * 3600n).add(F(BigInt(minutes) * 60n))
    .add(seconds instanceof Frac ? seconds : F(BigInt(seconds)));
  // A step with nothing but an exact tail *is* a physical step.
  if (mo === 0 && d === 0) return duration(tail);
  return { type: "caldur", months: mo, days: d, secs: tail };
}

export const calSpan = (anchor, step, zone = "UTC") =>
  (step.type === "duration"
    ? new Span(anchor, anchor.add(step.d))
    : { type: "calspan", anchor, step, zone });

export function caldurText(s) {
  const parts = [];
  if (s.months) parts.push(`mo=${s.months}`);
  if (s.days) parts.push(`d=${s.days}`);
  if (!s.secs.isZero()) parts.push(`s=${s.secs}`);
  return parts.join(";");
}

export function calspanText(x) {
  const body = `${caldurText(x.step)}@${x.anchor}`;
  return x.zone === "UTC" ? body : `${body}!${x.zone}`;
}

const NOMINAL_KEYS = { mo: "months", d: "days", s: "seconds" };

// n: a nominal step, optionally anchored (@t) in a zone (!zone).
export function parseNominalBody(body) {
  let zone = "UTC";
  const bang = body.indexOf("!");
  if (bang >= 0) { zone = body.slice(bang + 1); body = body.slice(0, bang); }
  let anchor = null;
  const at = body.indexOf("@");
  if (at >= 0) { anchor = Frac.parse(body.slice(at + 1)); body = body.slice(0, at); }
  const kw = {};
  for (const part of body.split(";")) {
    if (!part) throw new Error("n: needs at least one of mo=, d=, s=");
    const eq = part.indexOf("=");
    const key = NOMINAL_KEYS[part.slice(0, eq)];
    if (!key) throw new Error(`unknown nominal field ${part.slice(0, eq)}`);
    kw[key] = Frac.parse(part.slice(eq + 1));
    if (key !== "seconds" && kw[key].d !== 1n) throw new Error(`${key} must be whole`);
  }
  const step = caldur({
    months: kw.months ? Number(kw.months.n) : 0,
    days: kw.days ? Number(kw.days.n) : 0,
    seconds: kw.seconds ?? F(0n),
  });
  if (anchor === null) return step;
  if (step.type !== "caldur") throw new Error("an anchored exact step is a span — use ic1:s:");
  return { type: "calspan", anchor, step, zone };
}

// --- the grid: a step + a phase = a coordinate system on the timeline ------

export function grid(step, phi = F(0n)) {
  const d = step.type === "duration" ? step.d : step;
  if (d.isNeg() || d.isZero()) throw new Error("a grid step must be positive");
  const p = phi.mod(d);
  const index = (t) => t.sub(p).div(d).floor();
  const slot = (n) => {
    const start = p.add(d.mul(new Frac(n)));
    return new Span(start, start.add(d));
  };
  return {
    step: d, phi: p, index, slot,
    slotAt: (t) => slot(index(t)),
    floor: (t) => p.add(d.mul(new Frac(index(t)))),
  };
}

// --- resolving a nominal step (UTC lens; see cells.js) ---------------------

export function calResolve(step, anchor, zone = "UTC") {
  if (zone !== "UTC") {
    throw new Error("browser core resolves UTC steps only — use the library/REST for zones");
  }
  const { unix } = unixFromTai(anchor);
  const whole = unix.floor();
  const frac = unix.sub(new Frac(whole));
  const dt = new Date(Number(whole) * 1000);
  let y = dt.getUTCFullYear();
  let mo = dt.getUTCMonth();          // 0-based
  let day = dt.getUTCDate();
  if (step.months) {
    const total = y * 12 + mo + step.months;
    y = Math.floor(total / 12);
    mo = total - y * 12;
    day = Math.min(day, new Date(Date.UTC(y, mo + 1, 0)).getUTCDate());
  }
  const ms = Date.UTC(y, mo, day + step.days, dt.getUTCHours(),
    dt.getUTCMinutes(), dt.getUTCSeconds());
  const moved = taiFromUnix(F(BigInt(Math.round(ms / 1000))));
  return moved.add(frac).add(step.secs);
}

export const calSecondsAt = (step, anchor, zone = "UTC") =>
  calResolve(step, anchor, zone).sub(anchor);

export function calspanSpan(x) {
  const end = calResolve(x.step, x.anchor, x.zone);
  return end.lt(x.anchor) ? new Span(end, x.anchor) : new Span(x.anchor, end);
}

// --- ISO-8601 sugar (ergonomics, not canonical naming) --------------------

const ISO_RE = /^([+-])?P(?!$)(?:(-?\d+)Y)?(?:(-?\d+)M)?(?:(-?\d+)W)?(?:(-?\d+)D)?(?:T(?!$)(?:(-?\d+)H)?(?:(-?\d+)M)?(?:(-?\d+(?:\.\d+)?)S)?)?$/;

export function fromIso(text) {
  const m = ISO_RE.exec(String(text).trim());
  if (!m) throw new Error(`bad ISO-8601 duration ${text}`);
  const [, sign, y, mo, w, d, h, mi, sec] = m;
  const num = (v) => (v === undefined ? 0 : Number(v));
  const step = caldur({
    years: num(y), months: num(mo), weeks: num(w), days: num(d),
    hours: num(h), minutes: num(mi),
    seconds: sec === undefined ? F(0n) : Frac.parse(sec),
  });
  if (sign !== "-") return step;
  return step.type === "duration"
    ? duration(step.d.neg())
    : { type: "caldur", months: -step.months, days: -step.days, secs: step.secs.neg() };
}
