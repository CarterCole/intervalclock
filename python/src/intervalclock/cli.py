"""The intervalclock CLI.

    intervalclock now [--zone Z] [--of NAME]     current instant, cells, states
    intervalclock name --cron '*/5 * * * *'      canonicalize a cron
    intervalclock name --period 1/3 --states 3 --state 2
    intervalclock name --hz 15/2
    intervalclock name 2026-08-01T14 [--zone Z]  a calendar cell
    intervalclock parse NAME|IC1-URL             decode and describe
    intervalclock next NAME [-n N] [--from T]    upcoming occurrences
    intervalclock contains NAME T                membership test
    intervalclock alias NAME [--words N]         word alias
"""

from __future__ import annotations

import argparse
import sys
from fractions import Fraction

from . import (
    ALWAYS,
    NEVER,
    CronSchedule,
    Instant,
    PhaseClass,
    alias,
    cell_span,
    civil,
    cron_next_after,
    from_cron,
    from_frequency,
    from_url,
    name,
    next_after,
    now,
    parse,
    phase,
    rat,
    state_at,
    to_url,
)
from .calendar import Cell
from .encode import _parse_cell


def _load(text: str):
    text = text.strip()
    if text.upper().startswith("IC1-"):
        return from_url(text)
    if text.startswith("ic1:"):
        return parse(text)
    return _parse_cell(text)  # bare cell like 2026-08-01T14


def _describe(x) -> str:
    lines = [f"name:  {name(x)}", f"url:   {to_url(x)}",
             f"alias: {alias(x)}", f"repr:  {x!r}"]
    return "\n".join(lines)


def cmd_now(args) -> int:
    t, err = now()
    print(f"tai:   {t.t} s since epoch (±{float(err)} s NTP assumption)")
    c = civil(t, args.zone)
    print(f"civil: {c.text()}")
    if args.of:
        x = _load(args.of)
        inside = x.contains(t)
        print(f"of:    {name(x)}")
        print(f"state: {'inside' if inside else 'outside'} now")
        if isinstance(x, PhaseClass):
            states = state_at(x.w, x.m, t, err=err)
            label = " or ".join(str(s) for s in states)
            note = " (boundary within sync error)" if len(states) > 1 else ""
            print(f"grid:  state {label} of {x.m}{note}")
        nxt = next_after(x, t) if not isinstance(x, CronSchedule) else cron_next_after(x, t)
        if nxt:
            print(f"next:  [{nxt.start}, {nxt.end}) in {float(nxt.start - t.t):.3f}s")
    return 0


def cmd_name(args) -> int:
    if args.cron:
        x = from_cron(args.cron, zone=args.zone)
    elif args.period:
        w = rat(args.period)
        m = args.states or 2
        x = phase(w, m, k=args.state or 0, delta=rat(args.delta or 0))
    elif args.hz:
        x = from_frequency(rat(args.hz))
    elif args.cell:
        x = _parse_cell(args.cell if args.zone == "UTC"
                        else f"{args.cell}!{args.zone}")
    else:
        print("nothing to name: pass --cron, --period, --hz, or a cell", file=sys.stderr)
        return 2
    print(_describe(x))
    return 0


def cmd_parse(args) -> int:
    x = _load(args.name)
    print(_describe(x))
    if isinstance(x, Cell):
        sp = cell_span(x)
        print(f"span:  {name(sp)} ({float(sp.duration)} s)")
    return 0


def cmd_next(args) -> int:
    x = _load(args.name)
    t = Instant(rat(args.from_t)) if args.from_t else now()[0]
    for _ in range(args.n):
        nxt = cron_next_after(x, t) if isinstance(x, CronSchedule) else next_after(x, t)
        if nxt is None:
            print("(no further occurrences)")
            return 0
        print(f"[{nxt.start}, {nxt.end})")
        t = Instant(nxt.start)
    return 0


def cmd_contains(args) -> int:
    x = _load(args.name)
    t = rat(args.time)
    inside = x.contains(t)
    print("inside" if inside else "outside")
    return 0 if inside else 1


def cmd_alias(args) -> int:
    print(alias(_load(args.name), words=args.words))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="intervalclock", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("now", help="current instant and its names")
    sp.add_argument("--zone", default="UTC")
    sp.add_argument("--of", help="a name/URL to locate 'now' within")
    sp.set_defaults(fn=cmd_now)

    sp = sub.add_parser("name", help="canonicalize a schedule/period/cell")
    sp.add_argument("cell", nargs="?", help="calendar cell like 2026-08-01T14")
    sp.add_argument("--cron")
    sp.add_argument("--period", help="slot width in seconds, e.g. 1/3")
    sp.add_argument("--states", type=int, help="modulus m")
    sp.add_argument("--state", type=int, help="state k")
    sp.add_argument("--delta", help="anchor offset δ in seconds")
    sp.add_argument("--hz", help="frequency (period = 1/hz)")
    sp.add_argument("--zone", default="UTC")
    sp.set_defaults(fn=cmd_name)

    sp = sub.add_parser("parse", help="decode a name or IC1- URL")
    sp.add_argument("name")
    sp.set_defaults(fn=cmd_parse)

    sp = sub.add_parser("next", help="upcoming occurrences")
    sp.add_argument("name")
    sp.add_argument("-n", type=int, default=1)
    sp.add_argument("--from", dest="from_t", help="TAI seconds since epoch")
    sp.set_defaults(fn=cmd_next)

    sp = sub.add_parser("contains", help="is time T inside the set?")
    sp.add_argument("name")
    sp.add_argument("time", help="TAI seconds since epoch (rational)")
    sp.set_defaults(fn=cmd_contains)

    sp = sub.add_parser("alias", help="word alias of a name")
    sp.add_argument("name")
    sp.add_argument("--words", type=int, default=4)
    sp.set_defaults(fn=cmd_alias)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except (ValueError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
