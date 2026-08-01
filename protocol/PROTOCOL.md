# The IntervalClock Protocol, v1

**A canonical, globally computable name for every interval and every periodic
phase class on a shared timeline — an H3 for time.**

H3 gives every hexagon on Earth a canonical hierarchical ID at every
resolution. This protocol does the same for time: calendar units (hours,
days, ISO weeks), every possible cron schedule, arbitrary rational periods
("every 1/3 second", any Hz), and pure periodic signal components — each gets
exactly one name, computable by anyone, with no registry and no clock.

Names are pure functions of their parameters. Two implementations on
opposite sides of the planet compute identical names for identical inputs;
NTP-style synchronization is needed only to answer "which state are we in
*right now*."

This document is the normative spec. The reference implementation is the
`intervalclock` Python package in this repository; the browser core in
`web/ts-core` implements the same encodings byte-for-byte.

---

## 1. The timeline

- **Timescale**: TAI — leap-second free and monotone. Civil time (UTC,
  zones, calendars) is a *lens* over this timeline (§5), never the substrate.
- **Epoch**: `1970-01-01T00:00:00 TAI` (the IEEE 1588 / PTP epoch).
- **Instants** are exact rational numbers of SI seconds since the epoch.
  There is **no resolution floor**: 1/3 s is exact, any rational frequency is
  exact. Irrational periods are *rejected, never silently approximated* —
  callers approximate explicitly (e.g. `limit_denominator`) if they want to.
- **Range**: the integer part of any instant must lie in `[−2^63, 2^63)`
  seconds (≈ ±292 Gyr; the product intent is ±20 Gyr — Big Bang to far
  future). Denominators are unbounded.
- **Planck time** (~5.39×10⁻⁴⁴ s) is a physical footnote, not a mechanism:
  it is an empirically measured constant with error bars, so a Planck-based
  tick could be neither exact nor stable across CODATA revisions. Pure ℚ
  over the *defined* SI second is exact forever.
- Nyquist limits are **per-signal**: a capture sampled at rate f_s can
  honestly name frequency content only up to f_s/2 (§9). There is no global
  ceiling because there is no global tick.

## 2. Objects and canonical forms

Every nameable set of time is exactly one of:

| Type | Meaning |
|---|---|
| `NEVER` | the empty set |
| `ALWAYS` | all of time (the root of every hierarchy) |
| `Instant(t)` | one rational point |
| `Span(a, b)` | one half-open interval `[a, b)`, `a < b` |
| `Φ(w, m, φ)` | **the atom**: one pulse of width `w` per period `P = w·m`, forever |
| `PSet(P, arcs)` | closure under boolean ops: disjoint arcs on the circle ℝ/P |
| `Cell` | a symbolic calendar name (§5) |
| `Cron` | a canonical cron disjunction (§6) |
| `Windowed(S, C)` | support × class: a phase class restricted to a span (§2.4) |

### 2.1 The atom Φ(w, m, φ)

> **Φ(w, m, φ) = ⋃ₙ∈ℤ [φ + nP, φ + nP + w)**, with `w ∈ ℚ>0`, `m ∈ ℤ≥2`,
> `P = w·m`, `φ ∈ [0, P)`, all rationals in lowest terms.

User-facing constructions may use `(w, m, state k, offset δ)`. Two
identities make the canonical reduction:

1. **k absorbs into φ**: `L(w, m, k, δ) = L(w, m, 0, δ + k·w)`.
2. **φ wraps**: offsets are meaningful only mod P.

So `φ = (δ + k·w) mod P`, and *offsets that exceed the period are a
non-issue by construction*. "State 2 of 3" is display sugar, recoverable as
`k = φ/w` exactly when φ lies on the w-grid.

**Uniqueness**: for `m ≥ 2` the point-set determines the parameters — w is
the length of any maximal component interval, P the spacing of consecutive
component starts, φ the unique start in `[0, P)`. Distinct canonical triples
⇒ distinct sets ⇒ one name per class.

**Mandatory normalizations**: `m = 1` (or any construction whose pulse
covers the whole period) → `ALWAYS`. Empty constructions → `NEVER`.

**Partition property (the H3-ness)**: the m siblings `Φ(w, m, k·w)` for
`k = 0…m−1` partition all of time. At `w = 1/3 s, m = 3` these are the three
states of a 1/3-second clock — modulo math, with φ carrying the phase.

### 2.2 The closure PSet(P, arcs)

Phase classes are not closed under ∪/∩/¬. The closure is a period `P ∈ ℚ>0`
plus disjoint, non-adjacent arcs `(start ∈ [0, P), width ∈ (0, P])` on the
circle ℝ/P, sorted by start (an arc may wrap through 0; adjacent arcs are
merged).

Canonical reduction (in order):
1. Merge/normalize arcs, including wraparound merging.
2. **Minimize the period**: replace P with the smallest `P′ | P` under which
   the arc pattern is shift-invariant.
3. Full circle → `ALWAYS`; no arcs → `NEVER`; a single arc with
   `P′/w ∈ ℤ≥2` → the `Φ` it equals. A single-arc PSet with non-integral
   `P′/w` is legal and canonical as PSet.

**Boolean algebra**: to combine periods P₁, P₂, lift both to
`L = lcm(P₁, P₂)` using rational lcm `lcm(a/b, c/d) = lcm(a,c)/gcd(b,d)`,
unroll arcs, operate on circular interval sets, re-reduce. Exact and
terminating. *Cost warning*: L blows up for unrelated periods —
implementations should expose a complexity measure.

### 2.3 Containment: the divisibility lattice

Exact subset predicate for `A = Φ(w₁,m₁,φ₁)`, `B = Φ(w₂,m₂,φ₂)`: let
`g = gcd(P₁, P₂)` (rational gcd `gcd(a/b, c/d) = gcd(ad, cb)/bd`); the
starts of A's pulses taken mod P₂ form the finite orbit
`O = { (φ₁ + j·g) mod P₂ : j = 0 … P₂/g − 1 }`. Then

> **A ⊆ B ⟺ w₁ ≤ w₂ and ∀ r ∈ O: (r − φ₂) mod P₂ ≤ w₂ − w₁.**

When `P₂ | P₁` the orbit is one point and this is the familiar
"divisibility + compatible offset" rule; the general form also decides
non-divisible cases exactly. General PSet containment: `A∩¬B = ∅`.

**Hierarchy axes** (both partition the parent — children tile the parent):
- **decimate** (period × c): children `Φ(w, mc, φ + iP)`, i = 0…c−1 —
  "every c-th occurrence".
- **duty** (slot ÷ c): children `Φ(w/c, mc, φ + i·w/c)` — "the c slices of
  each pulse".

`harmonic n` of Φ (defined when `n | m`) is `Φ(w, m/n, φ mod P/n)` — same
pulse width, n× frequency, and an **ancestor** (superset). Subharmonics are
the decimation children.

Time has no privileged branching factor (7-day weeks vs decimal vs dyadic):
**the lattice is the invariant; hierarchies are named chains through it.**
Implementations ship the decimal grid (w = 10^k s, factor-10 subdivision)
and the calendar lens; other grids are user-definable.

### 2.4 Windowed classes: support × phase

> A time range + an interval describes a pure sinusoid perfectly.

`Windowed(S, C)` = `S ∩ C` for a Span S and periodic class C: C fixes the
period and phase alignment (eternal); S fixes the support. **Amplitude is
measurement data, not identity — it never enters a name.** A pure tone is
one windowed class plus an amplitude scalar; a sampled signal decomposes
into windowed classes sharing one support (the capture window) with
per-class amplitudes; "extend the signal forever" = drop the span.

Containment is componentwise: `(S₁,C₁) ⊆ (S₂,C₂) ⟺ S₁⊆S₂ ∧ C₁⊆C₂`; an
eternal class is the degenerate unbounded-support case. A windowed class no
pulse of which intersects its support reduces to `NEVER`.

## 3. Canonical text grammar

The structured text name is the authoritative, registry-free canonical form.
Pretty forms (`Φ[w=1/3 s · m=3 · φ=2/3 s] (state 2 of 3)`) are display-only.

```ebnf
id      := "ic1:" body
body    := "never" | "always"
         | "t:" rat                                  (* instant, TAI s since epoch *)
         | "s:" rat ";" rat                          (* span start;end *)
         | "c:" "w=" rat ";m=" posint ";phi=" rat    (* phase class *)
         | "u:" "P=" rat (";a=" rat "+" rat)+        (* pset: arcs start+width *)
         | "g:" cell ["!" zone]                      (* calendar cell, default UTC *)
         | "k:" cronrec ("+" cronrec)* ["!" zone]    (* cron; "+" joins records *)
         | "x:" "s:" rat ";" rat "|" clsbody         (* windowed: span | class *)
         | "f:" …                                    (* reserved: FFT provenance, v2 *)
clsbody := ("c:" | "u:") …                           (* as above, without "ic1:" *)
rat     := ["-"] int ["/" posint]                    (* lowest terms, den > 0 *)
cell    := yyyy | yyyy"-"mm | yyyy"-"mm"-"dd
         | yyyy"-"mm"-"dd"T"hh [":"mm [":"ss]] | yyyy"-W"ww
cronrec := field "|" field "|" field "|" field "|" field   (* min|hr|dom|mon|dow *)
field   := "*" | term ("," term)*
term    := int | int"-"int | int"-"int"/"posint
```

Baked-in canonicalization: rationals in lowest terms with positive
denominators; `phi ∈ [0, P)`; no whitespace; cron month/dow names and
7-as-Sunday normalized to numbers at parse; cron field text is the
deterministic greedy projection of the bitmask (§6).

Worked examples (all verified by the reference implementation):

| Thing | Canonical name |
|---|---|
| The hour 14:00–15:00 UTC, 2026-08-01 | `ic1:g:2026-08-01T14` → resolves to `ic1:s:1785592837;1785596437` (UTC−TAI = −37 s) |
| ISO week 31 of 2026 | `ic1:g:2026-W31` → `ic1:s:1785110437;1785715237` |
| "Every 1/3 s, state 2" (w=1/3, m=3, k=2, δ=0) | `ic1:c:w=1/3;m=3;phi=2/3` |
| cron `*/5 * * * *` (≡ `0-59/5` ≡ explicit list) | `ic1:k:0-55/5\|*\|*\|*\|*` |
| FFT bin at 7.5 Hz, phase π/3, t₀ = epoch | `ic1:c:w=1/15;m=2;phi=7/90` |

## 4. Binary encoding

A fully fixed-width ID is impossible with unbounded denominators and no
floor. The layout is **fixed with a variable-length exact tail**:

```
[1 byte header: version<<4 | type] [8 bytes big-endian sort key] [LEB128 tail]

types: 0x0 NEVER   0x1 ALWAYS  0x2 INSTANT  0x3 SPAN   0x4 PHASE
       0x5 PSET    0x6 CELL    0x7 CRON     0x8 FFTCOMP (reserved, v2)
       0x9 WINDOWED             0xA–0xF reserved
```

All varints are unsigned LEB128; signed values use zigzag. Rationals are
`num, den` pairs in lowest terms.

- **INSTANT**: key = `uint64be(floor(t) + 2^63)` (offset-binary → byte sort
  is chronological); tail = fractional part `num, den`.
- **SPAN**: key from start as above; tail = start-frac `num, den`, duration
  `num, den`.
- **PHASE**: key = IEEE-754 float64 big-endian of P (positive floats byte-
  compare correctly → classes cluster by period; exact ties break on the
  canonical tail, deterministically); tail = `w.num, w.den, m, φ.num, φ.den`.
- **PSET**: key = f64be(P); tail = `P.num, P.den, arc-count`, then per arc
  `start.num, start.den, width.num, width.den`.
- **CELL**: key = `(year+2^31)<<32 | kind<<28 | packed-fields` (chronological
  within kind+zone); body = `[1B kind][1B zone-len][zone utf8]`,
  `zigzag(year)`, then the remaining fields. Kinds: 0 year, 1 month, 2 day,
  3 hour, 4 minute, 5 second, 6 isoweek.
- **CRON**: key = zeros (symbolic); body = `[1B zone-len][zone]
  [1B record-count]`, then per record 18 bytes: minute bitmask 8B, hour 3B,
  dom 4B, month 2B, dow 1B (big-endian, bit index = field value), records
  sorted by their bytes.
- **WINDOWED**: span layout (key + start-frac + duration) followed by the
  embedded class encoding verbatim.
- Decoders MUST reject 0x8 and unknown types with a "reserved" error, and
  reject unknown versions.

**URL form**: `IC1-` + Crockford base32 of the binary ID (left-aligned to a
5-bit boundary; decoding accepts lowercase and the o/i/l confusables).

## 5. The civil lens (two layers, forced)

Calendar units are not fixed-length in physical time: leap-second days are
86 401 s, DST days 23/25 h, months vary. Worse, **future leap seconds are
not computable** (IERS announces ~6 months ahead) and tzdata is political.
Therefore "cron as a TAI phase class" is impossible *in principle*, and the
protocol has two layers:

- **Layer A (physical)**: Instant/Span/Φ/PSet/Windowed on rational TAI.
  Eternal, version-free, pure.
- **Layer B (civil)**: Cell and Cron are canonical **symbolic** names.
  *Resolving* one to a physical Span is a function stamped with
  `(leap-table version, tzdata version)`. Same name everywhere; same
  resolution given the same tables.

Policies (normative):
- Leap seconds: exact table from 1972 (Layer A conversion); proleptic 10 s
  offset before 1972 (the 1958–72 rubber-second era is not modeled). The
  UTC lens maps 23:59:60 into its day's 86 401-s span.
- DST spring-forward: nonexistent wall times **raise**; cron occurrences in
  the gap are **skipped** (Vixie behavior).
- DST fall-back: ambiguous wall times take the requested fold (PEP 495,
  default first); cron fires on the **first** occurrence only.
- ISO weeks: ISO-8601, Monday start, weeks 1–52/53.

## 6. Cron canonicalization

Equivalent cron expressions MUST produce identical IDs.

1. Parse the five fields (minute, hour, day-of-month, month, day-of-week);
   fold names (`JAN`, `MON`), map dow 7→0; expand `*`, ranges, lists,
   `/step` (a bare `N/step` extends to the field top, Vixie-style) into
   per-field **bitsets** (bit index = value).
2. **Vixie dom/dow quirk**: when both dom and dow are restricted, semantics
   are OR. Normalize to a disjunction of pure-AND records:
   `(dom restricted, dow=*) ∪ (dom=*, dow restricted)`.
3. Prune impossible records (e.g. dom ⊆ {30, 31} with month = {2}; Feb 29
   is possible — leap years exist). All records pruned → `NEVER`.
4. Drop records bitset-subsumed by others; dedupe; sort records by their
   18-byte encoding. **The sorted bitmask list + zone is the identity.**
5. Text projection (deterministic greedy per field): full range → `*`;
   otherwise repeatedly take the smallest uncovered element and emit the
   maximal-length arithmetic progression from it within the mask (ties →
   smallest step; progressions shorter than 3 render as ranges or
   singletons). `*/5` in minutes renders `0-55/5`.

## 7. Word aliases

For speech and sharing, not ground truth (a hash of an unbounded ID space
into fixed tuples cannot be injective).

- Wordlist: the frozen **BIP-39 English list** (2048 words, 11 bits/word,
  first-four-letters unique), versioned `bip39-english-v1`.
- Derivation: `BLAKE2b(binary ID, digest_size=16, person="ic-alias-v1")`
  → top 121 bits → **11 words**, hyphen-joined.
- The shareable alias is the shortest prefix (≥ 4 words ≈ 44 bits) unique in
  a **registry** (reference: local SQLite; the row format —
  `full_alias, id_bytes, prefix_len, wordlist` — is deliberately simple so
  registries can federate). Minting is git-short-hash style: a later
  collision gives the newcomer a longer prefix; **existing aliases never
  change**, and a previously minted alias keeps resolving to its entry.
  Expected first 4-word collision ≈ 2^22 ≈ 4M entries per registry.

## 8. The clock

`now()` returns `(Instant, uncertainty)`. The system clock is assumed
NTP-disciplined; the default uncertainty bound is a conservative 100 ms.
Near a slot boundary the current state is *genuinely ambiguous* within the
sync error: `state_at(w, m, t, err)` returns one state, or two when t is
within err of a boundary. The ambiguity is surfaced, never hidden.

## 9. FFT layer (normative here; implemented in v2)

The mapping is frozen now so implementations slot in without breaking IDs.

- Bin k of an N-sample capture at rate f_s (rational) starting at t₀ has
  exact frequency `f_k = k·f_s/N` and period `P = N/(k·f_s)`. Its eternal
  identity is the **positive-half-cycle class**
  `{ t : cos(2πf_k(t−t₀)+θ) > 0 }`, which is always exactly

  > **Φ(w = P/2, m = 2, φ = (t₀ − (θ/2π)·P − P/4) mod P)**

  — "the pulse centered on every peak, as if it continued forever."
  (A slot width of 1/f_s fails whenever k ∤ N; the half-cycle form never
  does.) The §3 example: 7.5 Hz, θ = π/3, t₀ = 0 → `ic1:c:w=1/15;m=2;phi=7/90`,
  and `cos(2π·7.5·t + π/3) = 1` exactly at pulse centers (t = 1/9 + n·2/15).
- Windowed identity: the capture's component is `Windowed(capture span, Φ)`;
  amplitude rides alongside as data. The reserved `f:` text form and 0x8
  binary type carry provenance `(f_s, N, k, t₀, A, θ)`.
- Phases estimated as floats are snapped to a declared quantum
  (`phase_quantum_turns`, default 1/2²⁴ turn) — deterministic and part of
  the provenance. Exact-bin tones only; a non-bin tone leaks across bins,
  and each bin's name describes *the analysis frame's component*, not the
  underlying tone.
- Edge cases: k = 0 (DC) → `ALWAYS` + amplitude; k = N/2 → θ ∈ {0, π}.
- **Nyquist/aliasing** (exact in ℚ): the ceiling is per-signal f_s/2. For
  f above it, `r = f − f_s·round(f/f_s)` (half-even), alias frequency
  `|r|`, conjugate phase when r < 0. Example: 15/2 Hz sampled at 10 Hz →
  5/2 Hz, conjugated.

## 10. Schedule inference (normative sketch; implemented in v2)

The inverse operation: names → time sets is the forward direction; this is
observed time sets → names.

`infer(timestamps, min_resolution, top_k, candidates=auto)` → ranked
`(class, score, matched_fraction, phase_jitter)`.

- Events are sparse point processes: fold events over a candidate period
  lattice (rational periods from min_resolution up to ~span/3) **and over
  calendar cycles through the lens** (day, ISO week, month, year — months
  are irregular, so calendar folding must go through Layer B).
- Score by circular concentration (Rayleigh test); phase = circular mean,
  quantized to min_resolution. Winners that are calendar cycles emit
  calendar/cron names (`"every Tuesday ~09:00"`); others emit Φ classes.
- Confidence bounds are normative: min_resolution caps phase precision;
  observation span and event count cap the longest detectable period and
  significance. (You cannot claim finer phase than your resolution — the
  sampling theorem again.)

## 11. Honest limits

1. **Countability**: real-parameter intervals are uncountable; any naming
   scheme is countable. This protocol names exactly the ℚ-parameterized
   sets — dense in everything, exact for everything a computer, a cron
   daemon, or an FFT bin can specify — and rejects irrational periods
   rather than approximating silently.
2. **Cron ≠ phase class**: future leap seconds are not computable; the
   two-layer split is forced, not chosen. (An optional idealized
   "proleptic-UTC" lens, under which any UTC cron is periodic with the
   400-year Gregorian period of 12 622 780 800 s, may compile cron → PSet
   in v2 for users who accept the idealization.)
3. **Fixed width vs exact ℚ**: pick two of {fixed width, exact rationals,
   no floor}. The encoding keeps exactness and the fixed 9-byte sortable
   prefix; the tail varies.
4. **Aliases can't be injective**: registry-relative prefixes, one-way by
   design.
5. **Simultaneity**: NTP error makes "the current state" ambiguous within
   ±err of boundaries; the API surfaces both candidates.

## 12. Versioning

- Protocol version: the `ic1:`/`IC1-` prefix and the header nibble. Breaking
  changes bump to `ic2:`.
- Wordlist: `bip39-english-v1`, frozen.
- Leap table and tzdata versions stamp every civil resolution
  (`resolution_versions()`).
