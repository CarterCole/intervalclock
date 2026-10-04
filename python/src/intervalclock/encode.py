"""Canonical encodings: binary ID, text name, URL form.

Binary layout (fixed layout, variable-length tail — a fully fixed width is
impossible with unbounded rational denominators and no resolution floor):

    [1B header: version<<4 | type] [8B big-endian sort key] [LEB128 tail]

Types: 0x0 NEVER · 0x1 ALWAYS · 0x2 INSTANT · 0x3 SPAN · 0x4 PHASE ·
0x5 PSET · 0x6 CELL · 0x7 CRON · 0x8 FFTCOMP · 0x9 WINDOWED ·
0xA DURATION · 0xB CALDUR · 0xC CALSPAN · 0xD–0xF reserved.

Sort keys: instants/spans/cells order chronologically under plain byte
comparison; PHASE/PSET use float64(P) big-endian so classes cluster by
period (exact ties broken by the canonical tail bytes — deterministic,
approximately numeric). FFTCOMP keys on the capture start, so captures
sort chronologically and one capture's bins stay adjacent (a period key
would need an infinity case for DC).

The text grammar ("ic1:...") is the authoritative human-readable canonical
name; the pretty Φ[...] repr is display sugar. URL form: "IC1-" + Crockford
base32 of the binary ID.
"""

from __future__ import annotations

import re
import struct
from fractions import Fraction

from .calendar import KINDS, Cell
from .core import (
    ALWAYS,
    NEVER,
    Always,
    Never,
    PhaseClass,
    PSet,
    Span,
    Windowed,
    phase,
    pset,
    windowed,
)
from .cron import CronRecord, CronSchedule, _parse_field, record_text
from .dsp import FFTComponent, amp_from_hex, amp_hex
from .duration import CalDuration, CalSpan, Duration, caldur
from .rat import fmt, rat
from .timescale import Instant

__all__ = [
    "encode", "decode", "name", "parse", "to_url", "from_url",
    "ReservedTypeError", "VERSION",
]

VERSION = 1

TYPE_NEVER, TYPE_ALWAYS, TYPE_INSTANT, TYPE_SPAN = 0x0, 0x1, 0x2, 0x3
TYPE_PHASE, TYPE_PSET, TYPE_CELL, TYPE_CRON = 0x4, 0x5, 0x6, 0x7
TYPE_FFTCOMP, TYPE_WINDOWED = 0x8, 0x9
TYPE_DURATION, TYPE_CALDUR, TYPE_CALSPAN = 0xA, 0xB, 0xC


class ReservedTypeError(ValueError):
    """Decoded a type tag that is reserved for a future protocol version."""


# --- varints ----------------------------------------------------------------


def _leb(n: int) -> bytes:
    if n < 0:
        raise ValueError("LEB128 encodes non-negative integers")
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _zigzag(n: int) -> int:
    return (n << 1) ^ (n >> 63) if n < 0 else n << 1


def _unzigzag(z: int) -> int:
    return (z >> 1) ^ -(z & 1)


class _Reader:
    def __init__(self, b: bytes, pos: int = 0):
        self.b, self.pos = b, pos

    def leb(self) -> int:
        shift, out = 0, 0
        while True:
            byte = self.b[self.pos]
            self.pos += 1
            out |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return out
            shift += 7

    def take(self, n: int) -> bytes:
        out = self.b[self.pos:self.pos + n]
        if len(out) != n:
            raise ValueError("truncated ID")
        self.pos += n
        return out


def _frac_parts(q: Fraction) -> tuple[int, Fraction]:
    """q → (floor, fractional part in [0,1))."""
    fl = q // 1
    return int(fl), q - fl


def _sortkey_time(q: Fraction) -> bytes:
    fl, _ = _frac_parts(q)
    return (fl + 2**63).to_bytes(8, "big")


def _sortkey_period(P: Fraction) -> bytes:
    return struct.pack(">d", float(P))


def _hdr(t: int) -> bytes:
    return bytes([(VERSION << 4) | t])


# --- encode -----------------------------------------------------------------


def _caldur_tail(d: CalDuration) -> bytes:
    """months, days, exact tail — the whole of a nominal step."""
    return (_leb(_zigzag(d.months)) + _leb(_zigzag(d.days))
            + _leb(_zigzag(d.secs.numerator)) + _leb(d.secs.denominator))


def _read_caldur(r: "_Reader") -> CalDuration:
    step = caldur(months=_unzigzag(r.leb()), days=_unzigzag(r.leb()),
                  seconds=Fraction(_unzigzag(r.leb()), r.leb()))
    if not isinstance(step, CalDuration):
        # months=days=0 reduces to a physical step, which has its own type.
        raise ValueError("non-canonical nominal step: encode it as 0xA")
    return step


def encode(x) -> bytes:
    """Canonical binary ID. Equal sets ⇒ identical bytes.

    Also encodes an FFTComponent, which is a provenance record rather than
    a set of time (§9); its equality includes the amplitude it measured.
    """
    if isinstance(x, Never):
        return _hdr(TYPE_NEVER)
    if isinstance(x, Always):
        return _hdr(TYPE_ALWAYS)
    if isinstance(x, Instant):
        fl, fr = _frac_parts(x.t)
        return (_hdr(TYPE_INSTANT) + _sortkey_time(x.t)
                + _leb(fr.numerator) + _leb(fr.denominator))
    if isinstance(x, Span):
        fl, fr = _frac_parts(x.start)
        d = x.duration
        return (_hdr(TYPE_SPAN) + _sortkey_time(x.start)
                + _leb(fr.numerator) + _leb(fr.denominator)
                + _leb(d.numerator) + _leb(d.denominator))
    if isinstance(x, PhaseClass):
        return (_hdr(TYPE_PHASE) + _sortkey_period(x.period)
                + _leb(x.w.numerator) + _leb(x.w.denominator) + _leb(x.m)
                + _leb(x.phi.numerator) + _leb(x.phi.denominator))
    if isinstance(x, PSet):
        out = (_hdr(TYPE_PSET) + _sortkey_period(x.period)
               + _leb(x.period.numerator) + _leb(x.period.denominator)
               + _leb(len(x.arcs)))
        for s, wd in x.arcs:
            out += (_leb(s.numerator) + _leb(s.denominator)
                    + _leb(wd.numerator) + _leb(wd.denominator))
        return out
    if isinstance(x, Cell):
        kind_i = KINDS.index(x.kind)
        zone_b = x.zone.encode()
        y = x.fields[0]
        # Chronological-ish sort key: year in the top bytes, then the
        # remaining fields packed low.
        packed = 0
        for f in x.fields[1:]:
            packed = packed * 64 + f
        key = ((y + 2**31) << 32 | (kind_i << 28) | (packed & 0x0FFFFFFF))
        out = (_hdr(TYPE_CELL) + key.to_bytes(8, "big")
               + bytes([kind_i, len(zone_b)]) + zone_b
               + _leb(_zigzag(y)))
        for f in x.fields[1:]:
            out += _leb(f)
        return out
    if isinstance(x, CronSchedule):
        zone_b = x.zone.encode()
        out = (_hdr(TYPE_CRON) + bytes(8)
               + bytes([len(zone_b)]) + zone_b + bytes([len(x.records)]))
        for r in x.records:
            out += r.to_bytes()
        return out
    if isinstance(x, FFTComponent):
        fl, fr = _frac_parts(x.t0)
        return (_hdr(TYPE_FFTCOMP) + _sortkey_time(x.t0)
                + _leb(fr.numerator) + _leb(fr.denominator)
                + _leb(x.fs.numerator) + _leb(x.fs.denominator)
                + _leb(x.N) + _leb(x.k)
                + struct.pack(">d", x.A)
                + _leb(x.theta_turns.numerator) + _leb(x.theta_turns.denominator)
                + _leb(x.quantum.numerator) + _leb(x.quantum.denominator))
    if isinstance(x, Duration):
        # A measure, not a set of time (§2.5): the key is the step length,
        # so byte order sorts short steps before long ones.
        fl, fr = _frac_parts(x.seconds)
        return (_hdr(TYPE_DURATION) + _sortkey_time(x.seconds)
                + _leb(fr.numerator) + _leb(fr.denominator))
    if isinstance(x, CalDuration):
        return (_hdr(TYPE_CALDUR) + bytes(8) + _caldur_tail(x))
    if isinstance(x, CalSpan):
        fl, fr = _frac_parts(x.anchor)
        zone_b = x.zone.encode()
        return (_hdr(TYPE_CALSPAN) + _sortkey_time(x.anchor)
                + _leb(fr.numerator) + _leb(fr.denominator)
                + bytes([len(zone_b)]) + zone_b + _caldur_tail(x.step))
    if isinstance(x, Windowed):
        sp = x.support
        fl, fr = _frac_parts(sp.start)
        d = sp.duration
        return (_hdr(TYPE_WINDOWED) + _sortkey_time(sp.start)
                + _leb(fr.numerator) + _leb(fr.denominator)
                + _leb(d.numerator) + _leb(d.denominator)
                + encode(x.cls))
    raise TypeError(f"cannot encode {x!r}")


def decode(b: bytes):
    if not b:
        raise ValueError("empty ID")
    ver, typ = b[0] >> 4, b[0] & 0x0F
    if ver != VERSION:
        raise ValueError(f"unsupported ID version {ver}")
    if typ == TYPE_NEVER:
        return NEVER
    if typ == TYPE_ALWAYS:
        return ALWAYS
    r = _Reader(b, 1)
    if typ == TYPE_INSTANT:
        fl = int.from_bytes(r.take(8), "big") - 2**63
        return Instant(fl + Fraction(r.leb(), r.leb()))
    if typ == TYPE_SPAN:
        fl = int.from_bytes(r.take(8), "big") - 2**63
        start = fl + Fraction(r.leb(), r.leb())
        dur = Fraction(r.leb(), r.leb())
        return Span(start, start + dur)
    if typ == TYPE_PHASE:
        r.take(8)
        w = Fraction(r.leb(), r.leb())
        m = r.leb()
        phi = Fraction(r.leb(), r.leb())
        return phase(w, m, phi=phi)
    if typ == TYPE_PSET:
        r.take(8)
        P = Fraction(r.leb(), r.leb())
        arcs = []
        for _ in range(r.leb()):
            arcs.append((Fraction(r.leb(), r.leb()), Fraction(r.leb(), r.leb())))
        return pset(P, arcs)
    if typ == TYPE_CELL:
        r.take(8)
        kind_i, zlen = r.take(1)[0], r.take(1)[0]
        zone = r.take(zlen).decode()
        y = _unzigzag(r.leb())
        kind = KINDS[kind_i]
        n_extra = {"year": 0, "month": 1, "day": 2, "hour": 3,
                   "minute": 4, "second": 5, "isoweek": 1}[kind]
        fields = (y, *[r.leb() for _ in range(n_extra)])
        return Cell(kind, fields, zone)
    if typ == TYPE_CRON:
        r.take(8)
        zlen = r.take(1)[0]
        zone = r.take(zlen).decode()
        n = r.take(1)[0]
        recs = tuple(CronRecord.from_bytes(r.take(18)) for _ in range(n))
        if not recs:
            return NEVER
        return CronSchedule(recs, zone)
    if typ == TYPE_FFTCOMP:
        fl = int.from_bytes(r.take(8), "big") - 2**63
        t0 = fl + Fraction(r.leb(), r.leb())
        fs = Fraction(r.leb(), r.leb())
        N, k = r.leb(), r.leb()
        A = struct.unpack(">d", r.take(8))[0]
        th = Fraction(r.leb(), r.leb())
        q = Fraction(r.leb(), r.leb())
        return FFTComponent(fs, N, k, t0, A, th, q)
    if typ == TYPE_DURATION:
        fl = int.from_bytes(r.take(8), "big") - 2**63
        return Duration(fl + Fraction(r.leb(), r.leb()))
    if typ == TYPE_CALDUR:
        r.take(8)
        return _read_caldur(r)
    if typ == TYPE_CALSPAN:
        fl = int.from_bytes(r.take(8), "big") - 2**63
        anchor = fl + Fraction(r.leb(), r.leb())
        zone = r.take(r.take(1)[0]).decode()
        return CalSpan(anchor, _read_caldur(r), zone)
    if typ == TYPE_WINDOWED:
        fl = int.from_bytes(r.take(8), "big") - 2**63
        start = fl + Fraction(r.leb(), r.leb())
        dur = Fraction(r.leb(), r.leb())
        cls = decode(r.b[r.pos:])
        return windowed(Span(start, start + dur), cls)
    raise ReservedTypeError(f"type {typ:#x} is reserved")


# --- text grammar -----------------------------------------------------------


def name(x) -> str:
    """The canonical structured text name (authoritative, registry-free)."""
    if isinstance(x, Never):
        return "ic1:never"
    if isinstance(x, Always):
        return "ic1:always"
    if isinstance(x, Instant):
        return f"ic1:t:{fmt(x.t)}"
    if isinstance(x, Span):
        return f"ic1:s:{fmt(x.start)};{fmt(x.end)}"
    if isinstance(x, PhaseClass):
        return f"ic1:c:w={fmt(x.w)};m={x.m};phi={fmt(x.phi)}"
    if isinstance(x, PSet):
        arcs = "".join(f";a={fmt(s)}+{fmt(w)}" for s, w in x.arcs)
        return f"ic1:u:P={fmt(x.period)}{arcs}"
    if isinstance(x, Cell):
        return f"ic1:g:{x.text()}"
    if isinstance(x, CronSchedule):
        body = "+".join(record_text(r) for r in x.records)
        suffix = "" if x.zone == "UTC" else f"!{x.zone}"
        return f"ic1:k:{body}{suffix}"
    if isinstance(x, Duration):
        return f"ic1:d:{fmt(x.seconds)}"
    if isinstance(x, CalDuration):
        return f"ic1:n:{x.text()}"
    if isinstance(x, CalSpan):
        return f"ic1:n:{x.text()}"
    if isinstance(x, Windowed):
        inner = name(x.cls)[len("ic1:"):]
        return f"ic1:x:s:{fmt(x.support.start)};{fmt(x.support.end)}|{inner}"
    if isinstance(x, FFTComponent):
        return (f"ic1:f:fs={fmt(x.fs)};N={x.N};k={x.k};t0={fmt(x.t0)}"
                f";A={amp_hex(x.A)};th={fmt(x.theta_turns)}"
                f";q={fmt(x.quantum)}")
    raise TypeError(f"cannot name {x!r}")


_CELL_RE = re.compile(
    r"^(\d{4})(?:-W(\d{2})|(?:-(\d{2})(?:-(\d{2})"
    r"(?:T(\d{2})(?::(\d{2})(?::(\d{2}))?)?)?)?)?)?$"
)


def _parse_cell(body: str) -> Cell:
    zone = "UTC"
    if "!" in body:
        body, zone = body.split("!", 1)
    m = _CELL_RE.match(body)
    if not m:
        raise ValueError(f"bad cell name {body!r}")
    y, wk, mo, d, h, mi, s = m.groups()
    y = int(y)
    if wk is not None:
        return Cell("isoweek", (y, int(wk)), zone)
    fields = [y]
    kind = "year"
    for val, k in ((mo, "month"), (d, "day"), (h, "hour"),
                   (mi, "minute"), (s, "second")):
        if val is None:
            break
        fields.append(int(val))
        kind = k
    return Cell(kind, tuple(fields), zone)


def _parse_cron_body(body: str) -> CronSchedule:
    zone = "UTC"
    if "!" in body:
        body, zone = body.split("!", 1)
    recs = []
    for rec in body.split("+"):
        f = rec.split("|")
        if len(f) != 5:
            raise ValueError(f"cron record needs 5 fields: {rec!r}")
        recs.append(CronRecord(
            _parse_field(f[0], "minute"), _parse_field(f[1], "hour"),
            _parse_field(f[2], "dom"), _parse_field(f[3], "month"),
            _parse_field(f[4], "dow"),
        ))
    return CronSchedule(tuple(sorted(recs, key=lambda r: r.to_bytes())), zone)


_FFT_FIELDS = ("fs", "N", "k", "t0", "A", "th", "q")


def _parse_fft_body(body: str) -> FFTComponent:
    """Parse an f: provenance record. Field order is canonical, not optional.

    (Unlike c:, which tolerates reordering, an f: record has one spelling —
    otherwise two "canonical" strings would name the same record.)
    """
    parts = body.split(";")
    if len(parts) != len(_FFT_FIELDS):
        raise ValueError(
            f"f: needs fields {';'.join(k + '=' for k in _FFT_FIELDS)}"
        )
    v = {}
    for part, key in zip(parts, _FFT_FIELDS):
        if not part.startswith(key + "="):
            raise ValueError(f"f: expected {key}= here, got {part!r}")
        v[key] = part[len(key) + 1:]
    return FFTComponent(rat(v["fs"]), int(v["N"]), int(v["k"]), rat(v["t0"]),
                        amp_from_hex(v["A"]), rat(v["th"]), rat(v["q"]))


_NOMINAL_KEYS = {"mo": "months", "d": "days", "s": "seconds"}


def _parse_nominal_body(body: str):
    """n: a nominal step, optionally anchored (@t) in a zone (!zone)."""
    zone = "UTC"
    if "!" in body:
        body, zone = body.split("!", 1)
    anchor = None
    if "@" in body:
        body, anchor_text = body.split("@", 1)
        anchor = rat(anchor_text)
    kw = {}
    for part in body.split(";"):
        if not part:
            raise ValueError("n: needs at least one of mo=, d=, s=")
        key, _, val = part.partition("=")
        if key not in _NOMINAL_KEYS:
            raise ValueError(f"unknown nominal field {key!r}")
        kw[_NOMINAL_KEYS[key]] = rat(val)
    step = caldur(months=int(kw.get("months", 0)), days=int(kw.get("days", 0)),
                  seconds=kw.get("seconds", 0))
    if anchor is None:
        return step
    if not isinstance(step, CalDuration):
        raise ValueError("an anchored exact step is a span — use ic1:s:")
    return CalSpan(anchor, step, zone)


def parse(s: str):
    """Parse a canonical text name back to its TimeSet (or f: record)."""
    s = s.strip()
    if not s.startswith("ic1:"):
        raise ValueError("names start with 'ic1:'")
    body = s[4:]
    if body == "never":
        return NEVER
    if body == "always":
        return ALWAYS
    if body.startswith("t:"):
        return Instant(rat(body[2:]))
    if body.startswith("s:"):
        a, b = body[2:].split(";")
        return Span(rat(a), rat(b))
    if body.startswith("c:"):
        kv = dict(p.split("=", 1) for p in body[2:].split(";"))
        return phase(rat(kv["w"]), int(kv["m"]), phi=rat(kv["phi"]))
    if body.startswith("u:"):
        parts = body[2:].split(";")
        P = rat(parts[0].removeprefix("P="))
        arcs = []
        for p in parts[1:]:
            sp, wd = p.removeprefix("a=").split("+")
            arcs.append((rat(sp), rat(wd)))
        return pset(P, arcs)
    if body.startswith("g:"):
        return _parse_cell(body[2:])
    if body.startswith("k:"):
        return _parse_cron_body(body[2:])
    if body.startswith("x:"):
        span_part, cls_part = body[2:].split("|", 1)
        if not span_part.startswith("s:"):
            raise ValueError("windowed name needs an s: span part")
        a, b = span_part[2:].split(";")
        cls = parse("ic1:" + cls_part)
        return windowed(Span(rat(a), rat(b)), cls)
    if body.startswith("d:"):
        return Duration(rat(body[2:]))
    if body.startswith("n:"):
        return _parse_nominal_body(body[2:])
    if body.startswith("f:"):
        return _parse_fft_body(body[2:])
    raise ValueError(f"unrecognized name {s!r}")


# --- URL form ---------------------------------------------------------------

_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_B32_REV = {c: i for i, c in enumerate(_B32)}
for _c in "abcdefghjkmnpqrstvwxyz":
    _B32_REV[_c] = _B32_REV[_c.upper()]
_B32_REV.update({"O": 0, "o": 0, "I": 1, "i": 1, "L": 1, "l": 1})


def to_url(x) -> str:
    """'IC1-' + Crockford base32 of the binary ID."""
    b = encode(x)
    bits = len(b) * 8
    chars = (bits + 4) // 5
    n = int.from_bytes(b, "big") << (chars * 5 - bits)  # left-align
    digits = ""
    for _ in range(chars):
        digits = _B32[n & 31] + digits
        n >>= 5
    return "IC1-" + digits


def from_url(s: str):
    s = s.strip()
    if not s.upper().startswith("IC1-"):
        raise ValueError("URL IDs start with 'IC1-'")
    digits = s[4:]
    n = 0
    for c in digits:
        if c == "-":
            continue
        n = (n << 5) | _B32_REV[c]
    bits = len([c for c in digits if c != "-"]) * 5
    nbytes = bits // 8
    n >>= bits - nbytes * 8
    return decode(n.to_bytes(nbytes, "big"))
