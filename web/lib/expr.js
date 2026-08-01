// The "paste anything" expression language, as a reusable module:
// ic1: names · IC1- urls · cron · '1/3 x3 @2 [+ δ]' grids · '7.5hz' · cells,
// mixed with '&' (intersection, binds tighter) and '|' (union).

import { Frac, F, ZERO } from "./rat.js";
import { PhaseClass, PSet, Windowed, phase, intersect, union } from "./core.js";
import { parse } from "./names.js";
import { fromUrl } from "./encode.js";
import { fromCron } from "./cron.js";
import { cellSpan } from "./cells.js";

export function atom(raw) {
  const s = raw.trim();
  if (!s) throw new Error("empty expression");
  if (s.toUpperCase().startsWith("IC1-")) return fromUrl(s);
  if (s.startsWith("ic1:")) return parse(s);
  const hz = /^(\d+(?:\.\d+)?|\d+\/\d+)\s*hz$/i.exec(s);
  if (hz) {
    const P = F(1n).div(Frac.parse(hz[1]));
    return phase(P.div(F(2n)), 2, {});
  }
  const grid = /^(-?[\d./]+)\s*x\s*(\d+)(?:\s*@\s*(\d+))?(?:\s*\+\s*(-?[\d./]+))?$/.exec(s);
  if (grid) {
    return phase(Frac.parse(grid[1]), parseInt(grid[2], 10),
      { k: grid[3] ? parseInt(grid[3], 10) : 0,
        delta: grid[4] ? Frac.parse(grid[4]) : ZERO });
  }
  if (/^\d{4}(-|$)/.test(s)) return parse("ic1:g:" + s);
  if (s.split(/\s+/).length === 5) return fromCron(s);
  throw new Error(
    "could not interpret input — try an ic1: name, a cron, '1/3 x3 @2', '7.5hz', a cell, or mix with & and |");
}

// A cell is symbolic; to mix it, resolve to its physical span (UTC lens).
export function physical(x) {
  if (x?.type === "cell") return cellSpan(x);
  if (x?.type === "cron") {
    throw new Error("cron is symbolic (civil layer) — mix physical classes");
  }
  return x;
}

export function interpret(raw) {
  if (raw.includes("|") && raw.trim().startsWith("ic1:")) return atom(raw);
  const unionParts = raw.split("|").map((p) => p.trim()).filter(Boolean);
  const evalAnd = (part) => {
    const vals = part.split("&").map((q) => q.trim()).filter(Boolean).map(atom);
    if (vals.length === 1) return vals[0];
    return vals.map(physical).reduce((acc, x) => intersect(acc, x));
  };
  if (unionParts.length === 1) return evalAnd(unionParts[0]);
  return unionParts.map(evalAnd).map(physical).reduce((acc, x) => union(acc, x));
}
