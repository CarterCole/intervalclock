// FFT provenance records — the browser twin of python's dsp.py (record half).
//
// The v1 core names sets of time; an FFT component is a *record about a
// measurement* whose canonical projection is a set of time. See PROTOCOL.md §9:
// bin k of an N-sample capture at rate fs starting t0 has period P = N/(k·fs)
// and eternal identity Φ(w = P/2, m = 2, φ = (t0 − θ·P − P/4) mod P), with θ in
// turns. Amplitude and the declared phase quantum ride along as data.
//
// Analysis itself (running an FFT, estimating θ) stays in the Python library;
// this module carries, names, and projects records.

import { Frac } from "./rat.js";
import { ALWAYS, Span, phase, windowed } from "./core.js";

export const DEFAULT_PHASE_QUANTUM = new Frac(1n, 1n << 24n);

const ZERO = new Frac(0n);
const ONE = new Frac(1n);
const TWO = new Frac(2n);
const FOUR = new Frac(4n);
const HALF = new Frac(1n, 2n);
const MAX_ABS_SECONDS = 1n << 63n;

export function fftComponent({ fs, N, k, t0, A, th, q = DEFAULT_PHASE_QUANTUM }) {
  N = Number(N); k = Number(k); A = Number(A);
  if (!Number.isInteger(N) || N < 1) throw new Error("N must be a positive integer");
  if (!Number.isInteger(k) || k < 0 || k > Math.floor(N / 2)) {
    throw new Error(`bin k must lie in [0, ${Math.floor(N / 2)}]`);
  }
  if (!fs || fs.isNeg() || fs.isZero()) throw new Error("sample rate must be positive");
  if (t0.floor() < -MAX_ABS_SECONDS || t0.floor() >= MAX_ABS_SECONDS) {
    throw new Error("capture start outside ±2^63 s window");
  }
  if (!Number.isFinite(A)) throw new Error("amplitude must be finite");
  if (th.isNeg() || !th.lt(ONE)) throw new Error("th must lie in [0, 1)");
  if (q.isNeg() || q.isZero()) throw new Error("phase quantum must be positive");
  const isDc = k === 0;
  const isNyquist = N % 2 === 0 && k === N / 2;
  if (isDc && !th.isZero()) throw new Error("DC bin has no phase: th must be 0");
  if (isNyquist && !(th.isZero() || th.eq(HALF))) {
    throw new Error("Nyquist bin has th ∈ {0, 1/2}");
  }
  return { type: "fftcomp", fs, N, k, t0, A, th, q, isDc, isNyquist };
}

/** The frozen §9 mapping: bin → eternal positive-half-cycle class. */
export function binIdentity(fs, N, k, t0 = ZERO, th = ZERO) {
  if (k === 0) return ALWAYS;
  const P = new Frac(BigInt(N)).div(new Frac(BigInt(k)).mul(fs));
  return phase(P.div(TWO), 2, { phi: t0.sub(th.mul(P)).sub(P.div(FOUR)).mod(P) });
}

export const identityOf = (c) => binIdentity(c.fs, c.N, c.k, c.t0, c.th);
export const supportOf = (c) =>
  new Span(c.t0, c.t0.add(new Frac(BigInt(c.N)).div(c.fs)));
export const windowedOf = (c) => windowed(supportOf(c), identityOf(c));

// Amplitude is the one float in the protocol. Shortest-decimal formatting
// differs between languages (Python repr(1e16) is "1e+16", JS gives
// "10000000000000000"), so the canonical text carries raw binary64 bits as 16
// lowercase hex digits — exact, and identical in both.

export function ampHex(a) {
  const buf = new ArrayBuffer(8);
  new DataView(buf).setFloat64(0, a, false);
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function ampFromHex(h) {
  if (!/^[0-9a-f]{16}$/.test(h)) throw new Error("amplitude must be 16 lowercase hex digits");
  const buf = new ArrayBuffer(8);
  const view = new DataView(buf);
  for (let i = 0; i < 8; i++) view.setUint8(i, parseInt(h.slice(i * 2, i * 2 + 2), 16));
  const a = view.getFloat64(0, false);
  if (!Number.isFinite(a)) throw new Error("amplitude must be finite");
  return a;
}
