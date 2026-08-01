// Local alias registry (localStorage): the browser twin of words.Registry.
// Aliases are one-way hashes of an unbounded ID space — resolution is
// registry-relative by design (PROTOCOL.md §7). This registry remembers
// every object this browser has named, so its aliases resolve here.

import { WORDS } from "./wordlist.js";
import { fullAlias } from "./words.js";

const KEY = "ic-alias-registry-v1";
const WORDSET = new Set(WORDS);

function load() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || {};
  } catch {
    return {};
  }
}

export function remember(x, nameStr) {
  try {
    const full = fullAlias(x).join("-");
    const reg = load();
    if (reg[full] !== nameStr) {
      reg[full] = nameStr;
      localStorage.setItem(KEY, JSON.stringify(reg));
    }
  } catch {
    /* storage unavailable (private mode etc.) — aliases just won't resolve */
  }
}

export function isAliasLike(s) {
  const ws = s.trim().toLowerCase().split("-");
  return ws.length >= 4 && ws.every((w) => WORDSET.has(w));
}

export function resolve(s) {
  const prefix = s.trim().toLowerCase();
  const reg = load();
  const hits = Object.entries(reg).filter(
    ([full]) => full === prefix || full.startsWith(prefix + "-"),
  );
  if (!hits.length) {
    throw new Error(
      "alias not in this browser's registry — aliases are one-way hashes " +
      "(PROTOCOL §7): open the object once by name/URL and its alias will " +
      "resolve here from then on",
    );
  }
  if (hits.length > 1) {
    throw new Error("alias is ambiguous in the local registry — add more words");
  }
  return hits[0][1];
}
