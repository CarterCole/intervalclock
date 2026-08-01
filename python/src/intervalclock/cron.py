"""Canonical cron: equivalent expressions get the same ID.

Pipeline: parse the 5-field expression → per-field *bitsets* → normalize the
Vixie dom/dow OR quirk into a disjunction of pure-AND records → prune
impossible records (0 0 31 2 * → NEVER) and records subsumed by others →
dedupe → sort by encoded bytes. The bitmask IS the canonical form; the text
rendering is a deterministic greedy projection of it, so '*/5 * * * *',
'0-59/5' and the explicit list all share one ID.

Cron names are symbolic (Layer B): resolving occurrences to physical time
goes through the civil lens with the DST policy — spring-forward
occurrences are skipped (Vixie behavior), fall-back times fire on the first
occurrence only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fractions import Fraction

from .calendar import NonexistentTime, _aware, _tz, _unix
from .core import NEVER, Span
from .timescale import Instant, tai_from_unix, unix_from_tai

__all__ = ["CronRecord", "CronSchedule", "from_cron", "to_cron", "cron_next_after"]

# (lo, hi) inclusive value range per field.
_RANGES = {"minute": (0, 59), "hour": (0, 23), "dom": (1, 31),
           "month": (1, 12), "dow": (0, 6)}
_MONTH_NAMES = {n: i + 1 for i, n in enumerate(
    "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}
_DOW_NAMES = {n: i for i, n in enumerate(
    "SUN MON TUE WED THU FRI SAT".split())}
_DAYS_IN_MONTH = {1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30,
                  7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def _full(field: str) -> int:
    lo, hi = _RANGES[field]
    return ((1 << (hi + 1)) - 1) & ~((1 << lo) - 1)


_FULL = {f: _full(f) for f in _RANGES}


@dataclass(frozen=True)
class CronRecord:
    """One pure-AND conjunct: five bitsets (bit index = field value)."""

    minute: int
    hour: int
    dom: int
    month: int
    dow: int

    def to_bytes(self) -> bytes:
        return (self.minute.to_bytes(8, "big") + self.hour.to_bytes(3, "big")
                + self.dom.to_bytes(4, "big") + self.month.to_bytes(2, "big")
                + self.dow.to_bytes(1, "big"))

    @classmethod
    def from_bytes(cls, b: bytes) -> "CronRecord":
        if len(b) != 18:
            raise ValueError("cron record must be 18 bytes")
        return cls(int.from_bytes(b[0:8], "big"), int.from_bytes(b[8:11], "big"),
                   int.from_bytes(b[11:15], "big"), int.from_bytes(b[15:17], "big"),
                   int.from_bytes(b[17:18], "big"))

    def subsumes(self, other: "CronRecord") -> bool:
        return all(
            getattr(other, f) & ~getattr(self, f) == 0
            for f in ("minute", "hour", "dom", "month", "dow")
        )


@dataclass(frozen=True)
class CronSchedule:
    """A canonical disjunction of CronRecords in an IANA zone."""

    records: tuple[CronRecord, ...]
    zone: str = "UTC"

    def contains_local(self, dt: datetime) -> bool:
        for r in self.records:
            if (r.minute >> dt.minute & 1 and r.hour >> dt.hour & 1
                    and r.month >> dt.month & 1
                    and r.dom >> dt.day & 1
                    and r.dow >> ((dt.weekday() + 1) % 7) & 1):
                return True
        return False

    def __repr__(self):
        return f"Cron[{to_cron(self)}]"


def _parse_field(text: str, field: str) -> int:
    lo, hi = _RANGES[field]
    names = _MONTH_NAMES if field == "month" else _DOW_NAMES if field == "dow" else {}

    def value(tok: str) -> int:
        t = tok.upper()
        if t in names:
            return names[t]
        v = int(tok)
        if field == "dow" and v == 7:
            v = 0
        if not lo <= v <= hi:
            raise ValueError(f"{field} value {tok} out of range {lo}-{hi}")
        return v

    mask = 0
    for term in text.split(","):
        if not term:
            raise ValueError(f"empty term in {field} field")
        step = 1
        if "/" in term:
            term, s = term.split("/", 1)
            step = int(s)
            if step < 1:
                raise ValueError("step must be ≥ 1")
        if term == "*":
            a, b = lo, hi
        elif "-" in term and not term.lstrip("-").isdigit():
            a_s, b_s = term.split("-", 1)
            a, b = value(a_s), value(b_s)
            if b < a:
                raise ValueError(f"inverted range {term} in {field}")
        else:
            a = value(term)
            b = hi if step > 1 else a  # "N/step" extends to the top, Vixie-style
        for v in range(a, b + 1, step):
            mask |= 1 << v
    return mask


def _record_possible(r: CronRecord) -> bool:
    """Is there any (month, day) the record can ever fire on?"""
    if r.minute == 0 or r.hour == 0 or r.month == 0 or r.dom == 0 or r.dow == 0:
        return False
    if r.dow != _FULL["dow"]:
        return True  # dow-restricted records fire whenever the weekday comes up
    for mo in range(1, 13):
        if not r.month >> mo & 1:
            continue
        for d in range(1, _DAYS_IN_MONTH[mo] + 1):
            if r.dom >> d & 1:
                return True
    return False


def from_cron(expr: str, zone: str = "UTC"):
    """Parse + canonicalize. Returns a CronSchedule, or NEVER if impossible."""
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError("cron expression must have 5 fields (min hr dom mon dow)")
    minute = _parse_field(fields[0], "minute")
    hour = _parse_field(fields[1], "hour")
    dom = _parse_field(fields[2], "dom")
    month = _parse_field(fields[3], "month")
    dow = _parse_field(fields[4], "dow")

    dom_restricted = fields[2] != "*" and dom != _FULL["dom"]
    dow_restricted = fields[4] != "*" and dow != _FULL["dow"]
    if dom_restricted and dow_restricted:
        # Vixie quirk: restricted dom AND restricted dow means OR.
        records = [
            CronRecord(minute, hour, dom, month, _FULL["dow"]),
            CronRecord(minute, hour, _FULL["dom"], month, dow),
        ]
    else:
        records = [CronRecord(minute, hour, dom, month, dow)]

    records = [r for r in records if _record_possible(r)]
    # Drop records subsumed by another (bitset-wise ⊆ across all five fields).
    kept: list[CronRecord] = []
    for r in records:
        if any(o.subsumes(r) for o in records if o != r) and not any(
            r.subsumes(o) and r != o for o in records
        ):
            continue
        if r not in kept:
            kept.append(r)
    # Mutual subsumption (equal records) already deduped by `not in kept`.
    if not kept:
        return NEVER
    kept.sort(key=lambda r: r.to_bytes())
    return CronSchedule(tuple(kept), zone)


# --- canonical text projection ---------------------------------------------


def _render_field(mask: int, field: str) -> str:
    lo, hi = _RANGES[field]
    if mask == _FULL[field]:
        return "*"
    elems = [v for v in range(lo, hi + 1) if mask >> v & 1]
    covered: set[int] = set()
    parts: list[str] = []
    for e in elems:
        if e in covered:
            continue
        # Maximal-length arithmetic progression from e within the mask;
        # ties broken by smallest step. Progressions shorter than 3 render
        # as a plain range (step 1) or singletons.
        best_len, best_step = 1, 1
        for step in range(1, hi - e + 1):
            n, v = 1, e + step
            while v <= hi and mask >> v & 1:
                n += 1
                v += step
            if n > best_len:
                best_len, best_step = n, step
        run = [e + i * best_step for i in range(best_len)]
        if best_len == 1:
            parts.append(str(e))
        elif best_step == 1:
            parts.append(f"{run[0]}-{run[-1]}")
        elif best_len >= 3:
            parts.append(f"{run[0]}-{run[-1]}/{best_step}")
        else:
            parts.append(str(e))
            run = [e]
        covered.update(run)
    return ",".join(parts)


def record_text(r: CronRecord) -> str:
    return "|".join([
        _render_field(r.minute, "minute"), _render_field(r.hour, "hour"),
        _render_field(r.dom, "dom"), _render_field(r.month, "month"),
        _render_field(r.dow, "dow"),
    ])


def to_cron(s: CronSchedule) -> str:
    """Minimal standard cron text when one record round-trips; else the
    multi-record canonical text (records joined by ' + ')."""
    texts = [record_text(r).replace("|", " ") for r in s.records]
    return " + ".join(texts)


# --- occurrences through the civil lens ------------------------------------


def cron_next_after(s: CronSchedule, t: Instant | Fraction) -> Span | None:
    """Next firing strictly after t, as the physical span of its minute.

    DST: nonexistent local minutes are skipped; ambiguous ones fire on the
    first (fold=0) occurrence only. Search is bounded at ~5 years.
    """
    q = t.t if isinstance(t, Instant) else Fraction(t)
    unix, _ = unix_from_tai(q)
    tz = _tz(s.zone)
    dt = (datetime(1970, 1, 1, tzinfo=timezone.utc)
          + timedelta(seconds=int(unix // 1))).astimezone(tz)
    local = dt.replace(second=0, microsecond=0, tzinfo=None)
    limit = local + timedelta(days=366 * 5)
    local += timedelta(minutes=1)
    while local < limit:
        # Fast-forward over non-matching months/days/hours.
        month_ok = any(r.month >> local.month & 1 for r in s.records)
        if not month_ok:
            nxt = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
            local = datetime(*nxt, 1)
            continue
        cdow = (local.weekday() + 1) % 7
        day_ok = any(
            (r.month >> local.month & 1)
            and (r.dom >> local.day & 1) and (r.dow >> cdow & 1)
            for r in s.records
        )
        if not day_ok:
            local = (local + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        hour_ok = any(
            (r.month >> local.month & 1) and (r.dom >> local.day & 1)
            and (r.dow >> cdow & 1) and (r.hour >> local.hour & 1)
            for r in s.records
        )
        if not hour_ok:
            local = (local + timedelta(hours=1)).replace(minute=0)
            continue
        if s.contains_local(local):
            try:
                aware = _aware(local, s.zone, fold=0)
            except NonexistentTime:
                local += timedelta(minutes=1)
                continue
            start = tai_from_unix(_unix(aware))
            if start.t > q:
                end = tai_from_unix(_unix(aware) + 60)
                return Span(start.t, end.t)
        local += timedelta(minutes=1)
    return None
