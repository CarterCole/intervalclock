#!/usr/bin/env python3
"""Regenerate golden.json from the Python reference implementation.

Run from python/:  .venv/bin/python ../web/test/gen_golden.py
The JS core must reproduce every byte of these vectors (web/test/golden.mjs).
"""

import json
from fractions import Fraction as F
from pathlib import Path

import intervalclock as ic

OUT = Path(__file__).resolve().parent / "golden.json"

objs = {
    "never": ic.NEVER,
    "always": ic.ALWAYS,
    "instant_third": ic.Instant(F(1, 3)),
    "instant_neg": ic.Instant(F(-987654321, 7)),
    "span": ic.span(F(-5, 3), F(22, 7)),
    "state2of3": ic.phase(F(1, 3), 3, k=2),
    "fft_bin": ic.phase(F(1, 15), 2, phi=F(7, 90)),
    "pset": ic.pset(1, [(0, F(1, 4)), (F(1, 3), F(1, 4))]),
    "windowed": ic.windowed(ic.span(0, 10), ic.phase(F(1, 3), 3, k=1)),
    "cron5": ic.from_cron("*/5 * * * *"),
    "cron_tue": ic.from_cron("0 9 * * 2", zone="America/Chicago"),
    "hour_cell": ic.cell("hour", 2026, 8, 1, 14),
    "isoweek": ic.cell("isoweek", 2026, 31),
    # FFT provenance records (§9). Fields are exact by construction — no
    # atan2 here, so these vectors don't depend on either side's libm.
    "fft_interior": ic.FFTComponent(F(10), 64, 3, F(0), 1.0, F(1, 6)),
    "fft_dc": ic.FFTComponent(F(10), 64, 0, F(-7, 3), -0.5, 0),
    "fft_nyquist": ic.FFTComponent(F(1, 3), 64, 32, F(10**9), 2.5, F(1, 2)),
    # Durations (§2.5): the physical step, the nominal step, and a nominal
    # step anchored to a spot in time.
    "step_5_2": ic.duration(F(5, 2)),
    "step_neg": ic.duration(-3),
    "step_day": ic.duration(86400),
    "cal_month": ic.caldur(months=1),
    "cal_mixed": ic.caldur(months=13, days=-2, seconds=F(1, 3)),
    "cal_anchored": ic.caldur(months=1).at(1662854437),
    "cal_anchored_zone": ic.caldur(months=1, seconds=30).at(
        1662854437, "America/Chicago"),
}

golden = {
    k: {
        "name": ic.name(o),
        "hex": ic.encode(o).hex(),
        "url": ic.to_url(o),
        "alias": ic.alias(o),
        "full_alias": ic.full_alias(o),
    }
    for k, o in objs.items()
}

# UTC cron occurrence parity: first N firings after a fixed TAI instant,
# including a leap-second minute (61 s) case.
def occurrences(expr: str, t0: F, n: int = 4):
    s = ic.from_cron(expr)
    out = []
    t = ic.Instant(t0)
    for _ in range(n):
        sp = ic.cron_next_after(s, t)
        out.append([str(sp.start), str(sp.end)])
        t = ic.Instant(sp.start)
    return {"expr": expr, "from": str(t0), "occurrences": out}

golden["_cron_next"] = [
    occurrences("*/5 * * * *", F(1785592837)),          # 2026-08-01T14:00 TAI
    occurrences("0 9 * * 2", F(1785592837)),            # Tuesdays 09:00 UTC
    occurrences("59 23 31 12 *", F(1482968437)),        # leap-second minute 2016
    occurrences("0 0 29 2 *", F(1785592837)),           # next Feb 29
]

# Nominal steps resolved through the UTC lens: months clamp, days absorb
# leap seconds. (Zoned resolution is library-side; the browser core is UTC.)
def resolved(step, anchor: F):
    return {"step": ic.name(step), "anchor": str(anchor),
            "end": str(step.resolve(anchor).t),
            "seconds": str(step.seconds_at(anchor))}


_SEP11 = F(1662854437)              # 2022-09-11T00:00:00Z
_LEAP_DAY = F(1483056037)           # 2016-12-31T00:00:00Z
golden["_cal_resolve"] = [
    resolved(ic.caldur(months=1), _SEP11),
    resolved(ic.caldur(months=-1), _SEP11),
    resolved(ic.caldur(months=17, days=3), _SEP11),
    resolved(ic.caldur(days=1), _LEAP_DAY),
    resolved(ic.caldur(days=1), _LEAP_DAY - 86400),
    resolved(ic.caldur(months=1), F(1675123237)),   # 2023-01-31 → Feb 28
    resolved(ic.caldur(days=90, seconds=F(1, 3)), _SEP11),
]

OUT.write_text(json.dumps(golden, indent=1))
print(f"wrote {OUT} ({len(golden) - 1} object vectors + cron_next)")
