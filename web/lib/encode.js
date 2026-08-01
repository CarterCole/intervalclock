// Binary IDs + Crockford base32 URL form, byte-identical to python encode.py.

import { Frac, F } from "./rat.js";
import {
  ALWAYS, NEVER, Instant, PhaseClass, PSet, Span, Windowed,
  phase, pset, windowed,
} from "./core.js";
import { KINDS, cell } from "./cells.js";
import { recordBytes, recordFromBytes } from "./cron.js";

export const VERSION = 1;
const TYPES = { never: 0x0, always: 0x1, instant: 0x2, span: 0x3, phase: 0x4,
  pset: 0x5, cell: 0x6, cron: 0x7, fftcomp: 0x8, windowed: 0x9 };

const M64 = (1n << 64n) - 1n;

function leb(n) {
  if (n < 0n) throw new Error("LEB128 needs non-negative");
  const out = [];
  for (;;) {
    const b = Number(n & 0x7fn);
    n >>= 7n;
    if (n) out.push(b | 0x80);
    else { out.push(b); return out; }
  }
}

const zigzag = (n) => (n >= 0n ? n << 1n : ((-n) << 1n) - 1n);
const unzigzag = (z) => (z & 1n ? -((z + 1n) >> 1n) : z >> 1n);

function u64be(n) {
  const out = [];
  for (let i = 7; i >= 0; i--) out.push(Number((n >> BigInt(8 * i)) & 0xffn));
  return out;
}

function f64be(x) {
  const buf = new ArrayBuffer(8);
  new DataView(buf).setFloat64(0, x, false);
  return [...new Uint8Array(buf)];
}

const sortkeyTime = (t) => u64be((t.floor() + (1n << 63n)) & M64);
const sortkeyPeriod = (P) => f64be(Number(P.n) / Number(P.d));
const hdr = (t) => [(VERSION << 4) | t];
const fracParts = (q) => { const fl = q.floor(); return [fl, q.sub(new Frac(fl))]; };
const lebFrac = (q) => [...leb(q.n), ...leb(q.d)];

export function encode(x) {
  if (x === NEVER || x?.type === "never") return Uint8Array.from(hdr(TYPES.never));
  if (x === ALWAYS || x?.type === "always") return Uint8Array.from(hdr(TYPES.always));
  if (x instanceof Instant) {
    const [, fr] = fracParts(x.t);
    return Uint8Array.from([...hdr(TYPES.instant), ...sortkeyTime(x.t), ...lebFrac(fr)]);
  }
  if (x instanceof Span) {
    const [, fr] = fracParts(x.start);
    return Uint8Array.from([...hdr(TYPES.span), ...sortkeyTime(x.start),
      ...lebFrac(fr), ...lebFrac(x.duration)]);
  }
  if (x instanceof PhaseClass) {
    return Uint8Array.from([...hdr(TYPES.phase), ...sortkeyPeriod(x.period),
      ...lebFrac(x.w), ...leb(BigInt(x.m)), ...lebFrac(x.phi)]);
  }
  if (x instanceof PSet) {
    const out = [...hdr(TYPES.pset), ...sortkeyPeriod(x.period),
      ...lebFrac(x.period), ...leb(BigInt(x.arcs.length))];
    for (const { s, w } of x.arcs) out.push(...lebFrac(s), ...lebFrac(w));
    return Uint8Array.from(out);
  }
  if (x?.type === "cell") {
    const kindI = KINDS.indexOf(x.kind);
    const zoneB = new TextEncoder().encode(x.zone);
    const y = BigInt(x.fields[0]);
    let packed = 0n;
    for (const f of x.fields.slice(1)) packed = packed * 64n + BigInt(f);
    const key = (((y + (1n << 31n)) << 32n) | (BigInt(kindI) << 28n)
      | (packed & 0x0fffffffn)) & M64;
    const out = [...hdr(TYPES.cell), ...u64be(key), kindI, zoneB.length,
      ...zoneB, ...leb(zigzag(y))];
    for (const f of x.fields.slice(1)) out.push(...leb(BigInt(f)));
    return Uint8Array.from(out);
  }
  if (x?.type === "cron") {
    const zoneB = new TextEncoder().encode(x.zone);
    const out = [...hdr(TYPES.cron), 0, 0, 0, 0, 0, 0, 0, 0,
      zoneB.length, ...zoneB, x.records.length];
    for (const r of x.records) out.push(...recordBytes(r));
    return Uint8Array.from(out);
  }
  if (x instanceof Windowed) {
    const [, fr] = fracParts(x.support.start);
    return Uint8Array.from([...hdr(TYPES.windowed), ...sortkeyTime(x.support.start),
      ...lebFrac(fr), ...lebFrac(x.support.duration), ...encode(x.cls)]);
  }
  throw new Error("cannot encode this object");
}

class Reader {
  constructor(b, pos = 0) { this.b = b; this.pos = pos; }
  leb() {
    let shift = 0n, out = 0n;
    for (;;) {
      const byte = this.b[this.pos++];
      out |= BigInt(byte & 0x7f) << shift;
      if (!(byte & 0x80)) return out;
      shift += 7n;
    }
  }
  frac() { const n = this.leb(); return new Frac(n, this.leb()); }
  take(n) { const out = this.b.slice(this.pos, this.pos + n); this.pos += n; return out; }
  u64() { let v = 0n; for (const byte of this.take(8)) v = (v << 8n) | BigInt(byte); return v; }
}

export function decode(b) {
  if (!b.length) throw new Error("empty ID");
  const ver = b[0] >> 4, typ = b[0] & 0x0f;
  if (ver !== VERSION) throw new Error(`unsupported version ${ver}`);
  if (typ === TYPES.never) return NEVER;
  if (typ === TYPES.always) return ALWAYS;
  if (typ === TYPES.fftcomp) throw new Error("type 0x8 (FFT) is reserved for v2");
  const r = new Reader(b, 1);
  if (typ === TYPES.instant) {
    const fl = r.u64() - (1n << 63n);
    return new Instant(new Frac(fl).add(r.frac()));
  }
  if (typ === TYPES.span) {
    const fl = r.u64() - (1n << 63n);
    const start = new Frac(fl).add(r.frac());
    return new Span(start, start.add(r.frac()));
  }
  if (typ === TYPES.phase) {
    r.take(8);
    const w = r.frac(), m = Number(r.leb()), phi = r.frac();
    return phase(w, m, { phi });
  }
  if (typ === TYPES.pset) {
    r.take(8);
    const P = r.frac(), n = Number(r.leb());
    const arcs = [];
    for (let i = 0; i < n; i++) arcs.push({ s: r.frac(), w: r.frac() });
    return pset(P, arcs);
  }
  if (typ === TYPES.cell) {
    r.take(8);
    const kindI = r.take(1)[0], zlen = r.take(1)[0];
    const zone = new TextDecoder().decode(Uint8Array.from(r.take(zlen)));
    const y = Number(unzigzag(r.leb()));
    const kind = KINDS[kindI];
    const nExtra = { year: 0, month: 1, day: 2, hour: 3, minute: 4, second: 5, isoweek: 1 }[kind];
    const fields = [y];
    for (let i = 0; i < nExtra; i++) fields.push(Number(r.leb()));
    return cell(kind, fields, zone);
  }
  if (typ === TYPES.cron) {
    r.take(8);
    const zlen = r.take(1)[0];
    const zone = new TextDecoder().decode(Uint8Array.from(r.take(zlen)));
    const n = r.take(1)[0];
    const records = [];
    for (let i = 0; i < n; i++) records.push(recordFromBytes(r.take(18)));
    return n ? { type: "cron", records, zone } : NEVER;
  }
  if (typ === TYPES.windowed) {
    const fl = r.u64() - (1n << 63n);
    const start = new Frac(fl).add(r.frac());
    const end = start.add(r.frac());
    const cls = decode(b.slice(r.pos));
    return windowed(new Span(start, end), cls);
  }
  throw new Error(`type 0x${typ.toString(16)} is reserved`);
}

// --- URL form ---------------------------------------------------------------

const B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
const B32_REV = {};
for (let i = 0; i < 32; i++) { B32_REV[B32[i]] = i; B32_REV[B32[i].toLowerCase()] = i; }
Object.assign(B32_REV, { O: 0, o: 0, I: 1, i: 1, L: 1, l: 1 });

export function toUrl(x) {
  const b = encode(x);
  const bits = b.length * 8;
  const chars = Math.ceil(bits / 5);
  let n = 0n;
  for (const byte of b) n = (n << 8n) | BigInt(byte);
  n <<= BigInt(chars * 5 - bits); // left-align
  let digits = "";
  for (let i = 0; i < chars; i++) { digits = B32[Number(n & 31n)] + digits; n >>= 5n; }
  return "IC1-" + digits;
}

export function fromUrl(s) {
  s = s.trim();
  if (!s.toUpperCase().startsWith("IC1-")) throw new Error("URL IDs start with IC1-");
  const digits = [...s.slice(4)].filter((c) => c !== "-");
  let n = 0n;
  for (const c of digits) {
    if (!(c in B32_REV)) throw new Error(`bad base32 digit ${c}`);
    n = (n << 5n) | BigInt(B32_REV[c]);
  }
  const bits = digits.length * 5;
  const nbytes = Math.floor(bits / 8);
  n >>= BigInt(bits - nbytes * 8);
  const out = new Uint8Array(nbytes);
  for (let i = nbytes - 1; i >= 0; i--) { out[i] = Number(n & 0xffn); n >>= 8n; }
  return decode(out);
}
