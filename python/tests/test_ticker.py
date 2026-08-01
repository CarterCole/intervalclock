import asyncio
import threading
from fractions import Fraction as F

from intervalclock import Span, every, iter_ticks, phase, ticks, windowed, span, now


FAST = phase(F(1, 50), 2)  # period 1/25 s — quick to observe


def test_async_ticks_fire_on_boundaries():
    async def collect():
        out = []
        async for sp in ticks(FAST):
            out.append(sp)
            if len(out) == 2:
                break
        return out

    out = asyncio.run(collect())
    assert len(out) == 2
    # consecutive occurrences are exactly one period apart, on the lattice —
    # and never the same span twice (early-waking timers must not re-fire)
    assert out[1].start - out[0].start == F(1, 25)
    assert (out[0].start / F(1, 25)).denominator == 1  # epoch-anchored


def test_iter_ticks_sync_generator():
    gen = iter_ticks(FAST)
    a = next(gen)
    b = next(gen)
    assert isinstance(a, Span) and b.start - a.start == F(1, 25)


def test_every_callback_and_stop():
    got = []
    done = threading.Event()

    def cb(sp):
        got.append(sp)
        if len(got) >= 2:
            done.set()

    stop = every(FAST, cb)
    assert done.wait(timeout=2), "callback ticker did not fire twice in time"
    stop()
    n = len(got)
    assert n >= 2
    assert got[1].start - got[0].start == F(1, 25)


def test_windowed_ticker_terminates():
    t, _ = now()
    past = windowed(span(t.t - 10, t.t - 9), phase(F(1, 50), 2))

    async def collect():
        return [sp async for sp in ticks(past)]

    assert asyncio.run(collect()) == []  # support already over → ends
