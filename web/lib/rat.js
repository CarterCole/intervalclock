// Exact rational arithmetic over BigInt — the browser twin of python's rat.py.
// All times, widths, periods, offsets are Frac instances (lowest terms, d > 0).

const babs = (x) => (x < 0n ? -x : x);

function bgcd(a, b) {
  a = babs(a); b = babs(b);
  while (b) { [a, b] = [b, a % b]; }
  return a;
}

export class Frac {
  constructor(n, d = 1n) {
    n = BigInt(n); d = BigInt(d);
    if (d === 0n) throw new Error("zero denominator");
    if (d < 0n) { n = -n; d = -d; }
    const g = bgcd(n, d) || 1n;
    this.n = n / g;
    this.d = d / g;
    Object.freeze(this);
  }

  static parse(s) {
    s = String(s).trim();
    if (s.includes("/")) {
      const [a, b] = s.split("/");
      return new Frac(BigInt(a), BigInt(b));
    }
    if (s.includes(".")) {
      const [w, f] = s.split(".");
      const scale = 10n ** BigInt(f.length);
      const sign = s.startsWith("-") ? -1n : 1n;
      return new Frac(BigInt(w) * scale + sign * BigInt(f), scale);
    }
    return new Frac(BigInt(s));
  }

  add(o) { return new Frac(this.n * o.d + o.n * this.d, this.d * o.d); }
  sub(o) { return new Frac(this.n * o.d - o.n * this.d, this.d * o.d); }
  mul(o) { return new Frac(this.n * o.n, this.d * o.d); }
  div(o) { return new Frac(this.n * o.d, this.d * o.n); }
  neg() { return new Frac(-this.n, this.d); }

  cmp(o) {
    const l = this.n * o.d, r = o.n * this.d;
    return l < r ? -1 : l > r ? 1 : 0;
  }
  lt(o) { return this.cmp(o) < 0; }
  le(o) { return this.cmp(o) <= 0; }
  eq(o) { return this.n === o.n && this.d === o.d; }
  isZero() { return this.n === 0n; }
  isNeg() { return this.n < 0n; }

  floor() { // BigInt floor(n/d)
    const q = this.n / this.d;
    return this.n < 0n && this.n % this.d !== 0n ? q - 1n : q;
  }
  // floored modulo: ((this mod m) + m) mod m, result in [0, m)
  mod(m) {
    const r = this.sub(m.mul(new Frac(this.div(m).floor())));
    return r.isNeg() ? r.add(m) : r;
  }

  toNumber() { return Number(this.n) / Number(this.d); }
  toString() { return this.d === 1n ? `${this.n}` : `${this.n}/${this.d}`; }
}

export const F = (n, d = 1n) => new Frac(n, d);
export const ZERO = F(0n);
export const ONE = F(1n);

export function rgcd(a, b) {
  return new Frac(bgcd(a.n * b.d, b.n * a.d), a.d * b.d);
}

export function rlcm(a, b) {
  const l = (babs(a.n) / bgcd(a.n, b.n)) * babs(b.n);
  return new Frac(l, bgcd(a.d, b.d));
}
