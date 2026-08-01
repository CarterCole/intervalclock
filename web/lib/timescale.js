// TAI timeline for the browser: leap table + conversions (twin of timescale.py).

import { Frac, F } from "./rat.js";

export const LEAP_TABLE_VERSION = "IERS-2017-01";

// (UTC date the offset takes effect, TAI−UTC from then on)
const LEAP_DATES = [
  [1972, 1, 10], [1972, 7, 11], [1973, 1, 12], [1974, 1, 13], [1975, 1, 14],
  [1976, 1, 15], [1977, 1, 16], [1978, 1, 17], [1979, 1, 18], [1980, 1, 19],
  [1981, 7, 20], [1982, 7, 21], [1983, 7, 22], [1985, 7, 23], [1988, 1, 24],
  [1990, 1, 25], [1991, 1, 26], [1992, 7, 27], [1993, 7, 28], [1994, 7, 29],
  [1996, 1, 30], [1997, 7, 31], [1999, 1, 32], [2006, 1, 33], [2009, 1, 34],
  [2012, 7, 35], [2015, 7, 36], [2017, 1, 37],
];

const LEAP_UNIX = LEAP_DATES.map(([y, mo, off]) => [
  BigInt(Date.UTC(y, mo - 1, 1) / 1000), off,
]);

export function taiMinusUtc(unixFrac) {
  let off = 10; // proleptic before 1972
  for (const [b, o] of LEAP_UNIX) {
    if (unixFrac.cmp(F(b)) >= 0) off = o;
    else break;
  }
  return off;
}

export function taiFromUnix(unixFrac) {
  return unixFrac.add(F(BigInt(taiMinusUtc(unixFrac))));
}

// TAI → { unix, leap }: during an inserted leap second unix pins to the
// final second of the day (re-read as 23:59:59, flag set).
export function unixFromTai(t) {
  for (let i = LEAP_UNIX.length; i >= 0; i--) {
    const o = i === 0 ? 10 : LEAP_UNIX[i - 1][1];
    const lo = i === 0 ? null : LEAP_UNIX[i - 1][0];
    const hi = i === LEAP_UNIX.length ? null : LEAP_UNIX[i][0];
    const u = t.sub(F(BigInt(o)));
    if ((lo === null || u.cmp(F(lo)) >= 0) && (hi === null || u.cmp(F(hi)) < 0)) {
      return { unix: u, leap: false };
    }
    if (hi !== null) {
      const leapStart = F(hi).add(F(BigInt(o)));
      if (t.cmp(leapStart) >= 0 && t.cmp(leapStart.add(F(1n))) < 0) {
        return { unix: F(hi - 1n).add(t.sub(leapStart)), leap: true };
      }
    }
  }
  throw new Error("leap bracket search failed");
}

// Current instant (browser clock, assumed NTP-disciplined by the OS).
export function nowTai() {
  const ms = BigInt(Date.now());
  return taiFromUnix(new Frac(ms, 1000n));
}

export const NOW_UNCERTAINTY_S = 0.1; // conservative NTP assumption
