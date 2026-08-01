// Calendar cells for the browser (UTC lens; other zones are named
// symbolically and resolved by the Python library / REST API).

import { F, Frac } from "./rat.js";
import { taiFromUnix, taiMinusUtc, unixFromTai } from "./timescale.js";
import { Span } from "./core.js";

export const KINDS = ["year", "month", "day", "hour", "minute", "second", "isoweek"];
const NFIELDS = { year: 1, month: 2, day: 3, hour: 4, minute: 5, second: 6, isoweek: 2 };

export function cell(kind, fields, zone = "UTC") {
  if (!KINDS.includes(kind)) throw new Error(`unknown cell kind ${kind}`);
  if (fields.length !== NFIELDS[kind]) throw new Error(`${kind} needs ${NFIELDS[kind]} fields`);
  return { type: "cell", kind, fields: fields.map(Number), zone };
}

const p2 = (n) => String(n).padStart(2, "0");
const p4 = (n) => String(n).padStart(4, "0");

export function cellText(c) {
  const f = c.fields;
  let body;
  if (c.kind === "isoweek") body = `${p4(f[0])}-W${p2(f[1])}`;
  else {
    body = p4(f[0]);
    if (f.length >= 2) body += `-${p2(f[1])}`;
    if (f.length >= 3) body += `-${p2(f[2])}`;
    if (f.length >= 4) body += `T${p2(f[3])}`;
    if (f.length >= 5) body += `:${p2(f[4])}`;
    if (f.length >= 6) body += `:${p2(f[5])}`;
  }
  return c.zone === "UTC" ? body : `${body}!${c.zone}`;
}

const CELL_RE = /^(\d{4})(?:-W(\d{2})|(?:-(\d{2})(?:-(\d{2})(?:T(\d{2})(?::(\d{2})(?::(\d{2}))?)?)?)?)?)?$/;

export function parseCell(body) {
  let zone = "UTC";
  const bang = body.indexOf("!");
  if (bang >= 0) { zone = body.slice(bang + 1); body = body.slice(0, bang); }
  const m = CELL_RE.exec(body);
  if (!m) throw new Error(`bad cell name ${body}`);
  const [, y, wk, mo, d, h, mi, s] = m;
  if (wk !== undefined) return cell("isoweek", [+y, +wk], zone);
  const fields = [+y];
  let kind = "year";
  for (const [val, k] of [[mo, "month"], [d, "day"], [h, "hour"], [mi, "minute"], [s, "second"]]) {
    if (val === undefined) break;
    fields.push(+val);
    kind = k;
  }
  return cell(kind, fields, zone);
}

function isoWeekStart(year, week) {
  // ISO 8601: week 1 contains Jan 4. Monday start.
  const jan4 = Date.UTC(year, 0, 4);
  const dow = (new Date(jan4).getUTCDay() + 6) % 7; // Mon=0
  return jan4 - dow * 86400000 + (week - 1) * 7 * 86400000;
}

// UTC-lens resolution (browser). Leap-second days come out 86 401 s long.
export function cellSpan(c) {
  if (c.zone !== "UTC") {
    throw new Error("browser core resolves UTC cells only — use the library/REST for zones");
  }
  const f = c.fields;
  let sMs, eMs;
  if (c.kind === "isoweek") {
    sMs = isoWeekStart(f[0], f[1]);
    eMs = sMs + 7 * 86400000;
  } else if (c.kind === "second" && f[5] === 60) {
    // inserted leap second: [b + o_before, b + o_before + 1)
    const b = BigInt(Date.UTC(f[0], f[1] - 1, f[2], f[3], f[4], 59) / 1000) + 1n;
    const oBefore = taiMinusUtc(F(b - 1n));
    const start = F(b + BigInt(oBefore));
    return new Span(start, start.add(F(1n)));
  } else {
    const [y, mo = 1, d = 1, h = 0, mi = 0, s = 0] = f;
    sMs = Date.UTC(y, mo - 1, d, h, mi, s);
    const bump = { year: [1, 0, 0], month: [0, 1, 0], day: [0, 0, 1] }[c.kind];
    if (bump) eMs = Date.UTC(y + bump[0], mo - 1 + bump[1], d + bump[2], h, mi, s);
    else eMs = sMs + { hour: 3600000, minute: 60000, second: 1000 }[c.kind];
  }
  const start = taiFromUnix(F(BigInt(sMs / 1000)));
  const end = taiFromUnix(F(BigInt(eMs / 1000)));
  return new Span(start, end);
}

// Physical instant → UTC civil reading (with :60 during a leap second).
export function civilUtc(t) {
  const { unix, leap } = unixFromTai(t);
  const whole = Number(unix.floor());
  const dt = new Date(whole * 1000);
  return {
    year: dt.getUTCFullYear(), month: dt.getUTCMonth() + 1, day: dt.getUTCDate(),
    hour: dt.getUTCHours(), minute: dt.getUTCMinutes(),
    second: leap ? 60 : dt.getUTCSeconds(),
    dowSun0: dt.getUTCDay(),
    leap,
  };
}
