// The canonical text grammar: name() and parse() dispatch (twin of encode.py's
// text half).

import { Frac } from "./rat.js";
import {
  ALWAYS, NEVER, Instant, PhaseClass, PSet, Span, Windowed,
  phase, pset, windowed,
} from "./core.js";
import { cellText, parseCell } from "./cells.js";
import { cronName, parseCronBody } from "./cron.js";
import { ampFromHex, ampHex, fftComponent } from "./fft.js";

// f: field order is canonical, not optional — unlike c:, which tolerates
// reordering, an f: record has exactly one spelling.
const FFT_FIELDS = ["fs", "N", "k", "t0", "A", "th", "q"];

function parseFftBody(rest) {
  const parts = rest.split(";");
  if (parts.length !== FFT_FIELDS.length) {
    throw new Error(`f: needs fields ${FFT_FIELDS.map((k) => k + "=").join(";")}`);
  }
  const v = {};
  parts.forEach((part, i) => {
    const key = FFT_FIELDS[i];
    if (!part.startsWith(key + "=")) throw new Error(`f: expected ${key}= here`);
    v[key] = part.slice(key.length + 1);
  });
  return fftComponent({
    fs: Frac.parse(v.fs), N: parseInt(v.N, 10), k: parseInt(v.k, 10),
    t0: Frac.parse(v.t0), A: ampFromHex(v.A),
    th: Frac.parse(v.th), q: Frac.parse(v.q),
  });
}

export function name(x) {
  if (x === NEVER || x?.type === "never") return "ic1:never";
  if (x === ALWAYS || x?.type === "always") return "ic1:always";
  if (x instanceof Instant) return `ic1:t:${x.t}`;
  if (x instanceof Span) return `ic1:s:${x.start};${x.end}`;
  if (x instanceof PhaseClass) return `ic1:c:w=${x.w};m=${x.m};phi=${x.phi}`;
  if (x instanceof PSet) {
    const arcs = x.arcs.map(({ s, w }) => `;a=${s}+${w}`).join("");
    return `ic1:u:P=${x.period}${arcs}`;
  }
  if (x?.type === "cell") return `ic1:g:${cellText(x)}`;
  if (x?.type === "cron") return cronName(x);
  if (x instanceof Windowed) {
    return `ic1:x:s:${x.support.start};${x.support.end}|${name(x.cls).slice(4)}`;
  }
  if (x?.type === "fftcomp") {
    return `ic1:f:fs=${x.fs};N=${x.N};k=${x.k};t0=${x.t0}`
      + `;A=${ampHex(x.A)};th=${x.th};q=${x.q}`;
  }
  throw new Error("cannot name this object");
}

export function parse(text) {
  const s = text.trim();
  if (!s.startsWith("ic1:")) throw new Error("names start with 'ic1:'");
  const body = s.slice(4);
  if (body === "never") return NEVER;
  if (body === "always") return ALWAYS;
  const tag = body.slice(0, 2);
  const rest = body.slice(2);
  if (tag === "t:") return new Instant(Frac.parse(rest));
  if (tag === "s:") {
    const [a, b] = rest.split(";");
    return new Span(Frac.parse(a), Frac.parse(b));
  }
  if (tag === "c:") {
    const kv = Object.fromEntries(rest.split(";").map((p) => p.split("=")));
    return phase(Frac.parse(kv.w), parseInt(kv.m, 10), { phi: Frac.parse(kv.phi) });
  }
  if (tag === "u:") {
    const parts = rest.split(";");
    const P = Frac.parse(parts[0].replace(/^P=/, ""));
    const arcs = parts.slice(1).map((p) => {
      const [a, w] = p.replace(/^a=/, "").split("+");
      return { s: Frac.parse(a), w: Frac.parse(w) };
    });
    return pset(P, arcs);
  }
  if (tag === "g:") return parseCell(rest);
  if (tag === "k:") return parseCronBody(rest);
  if (tag === "x:") {
    const bar = rest.indexOf("|");
    const spanPart = rest.slice(0, bar);
    if (!spanPart.startsWith("s:")) throw new Error("windowed needs an s: span");
    const [a, b] = spanPart.slice(2).split(";");
    const cls = parse("ic1:" + rest.slice(bar + 1));
    return windowed(new Span(Frac.parse(a), Frac.parse(b)), cls);
  }
  if (tag === "f:") return parseFftBody(rest);
  throw new Error(`unrecognized name ${s}`);
}
