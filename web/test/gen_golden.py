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

OUT.write_text(json.dumps(golden, indent=1))
print(f"wrote {OUT} ({len(golden) - 1} object vectors + cron_next)")
