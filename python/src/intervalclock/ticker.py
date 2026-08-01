"""Emit events on a named class's occurrences.

Epoch-anchored: each wait is computed fresh from the shared timeline
(next_after of the *current* clock reading), so there is no accumulated
drift, and two NTP-disciplined machines running the same name fire in
lockstep to within their sync error. Works for phase classes, PSets,
windowed classes, and cron schedules alike — anything with a next
occurrence.

    import asyncio, intervalclock as ic

    async def main():
        async for span in ic.ticks(ic.phase(ic.rat("1/3"), 3, k=2)):
            print("pulse", span)          # fires every 1 s, at state 2

    asyncio.run(main())

or with a callback:

    stop = ic.every("*/5 * * * *", lambda span: print("cron fired", span))
"""

from __future__ import annotations

import asyncio
import threading
from typing import AsyncIterator, Callable, Optional

from .core import Span, next_after
from .cron import CronSchedule, cron_next_after
from .timescale import Instant, now


def _next(x, t):
    if isinstance(x, CronSchedule):
        return cron_next_after(x, t)
    return next_after(x, t)


async def ticks(x, *, lead: float = 0.0) -> AsyncIterator[Span]:
    """Async-iterate the occurrences of x as they happen.

    Yields each occurrence Span at (its start − lead) seconds. Ends when the
    class has no further occurrences (e.g. a windowed class past its
    support).
    """
    last = None  # timers can wake early; never yield the same span twice
    while True:
        t, _ = now()
        q = t if last is None or last <= t.t else Instant(last)
        nxt = _next(x, q)
        if nxt is None:
            return
        delay = float(nxt.start - t.t) - lead
        if delay > 0:
            await asyncio.sleep(delay)
        last = nxt.start
        yield nxt


def iter_ticks(x, *, lead: float = 0.0):
    """Plain blocking generator — `for span in iter_ticks(cls): ...`.

    The synchronous twin of ticks() for scripts and REPLs: sleeps until each
    occurrence and yields it.
    """
    import time as _time

    last = None
    while True:
        t, _ = now()
        q = t if last is None or last <= t.t else Instant(last)
        nxt = _next(x, q)
        if nxt is None:
            return
        delay = float(nxt.start - t.t) - lead
        if delay > 0:
            _time.sleep(delay)
        last = nxt.start
        yield nxt


def every(x, callback: Callable[[Span], None], *, daemon: bool = True) -> Callable[[], None]:
    """Fire callback(span) on each occurrence of x from a background thread.

    Returns a zero-argument stop function. The wait is re-derived from the
    clock before every firing (epoch-anchored, drift-free).
    """
    stop_event = threading.Event()

    def loop():
        last = None
        while not stop_event.is_set():
            t, _ = now()
            q = t if last is None or last <= t.t else Instant(last)
            nxt = _next(x, q)
            if nxt is None:
                return
            delay = float(nxt.start - t.t)
            if stop_event.wait(timeout=max(delay, 0.0)):
                return
            last = nxt.start
            callback(nxt)

    thread = threading.Thread(target=loop, daemon=daemon, name="intervalclock-ticker")
    thread.start()

    def stop():
        stop_event.set()
        thread.join(timeout=1)

    return stop
