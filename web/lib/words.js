// Word aliases (twin of words.py): BLAKE2b-128(id, person="ic-alias-v1")
// → top 121 bits → 11 BIP-39 words; shareable prefix ≥ 4 words.

import { blake2b } from "./blake2b.js";
import { encode } from "./encode.js";
import { WORDS } from "./wordlist.js";

const PERSON = new TextEncoder().encode("ic-alias-v1");
const TOTAL = 11;

export function fullAlias(x) {
  const h = blake2b(encode(x), 16, PERSON);
  let n = 0n;
  for (const b of h) n = (n << 8n) | BigInt(b);
  n >>= BigInt(128 - TOTAL * 11);
  const out = [];
  for (let i = 0; i < TOTAL; i++) {
    const shift = BigInt((TOTAL - 1 - i) * 11);
    out.push(WORDS[Number((n >> shift) & 0x7ffn)]);
  }
  return out;
}

export function alias(x, words = 4) {
  return fullAlias(x).slice(0, words).join("-");
}
