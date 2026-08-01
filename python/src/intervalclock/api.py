"""The hosted REST API: a thin FastAPI wrapper over the library.

Run anywhere:  uvicorn intervalclock.api:app
Requires the [api] extra:  pip install 'intervalclock[api]'

Endpoints (all GET, all return JSON):
    /v1/now?zone=Z
    /v1/name?cron=...&zone=Z | ?period=1/3&states=3&state=2 | ?hz=15/2 | ?cell=2026-08-01T14
    /v1/parse?name=ic1:...
    /v1/decode/{IC1-...}
    /v1/next?name=...&n=5&from_t=...
    /v1/contains?name=...&t=...
    /v1/alias?name=...&words=4
"""

from __future__ import annotations

from fractions import Fraction

try:
    from fastapi import FastAPI, HTTPException, Query
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "the REST API needs the [api] extra: pip install 'intervalclock[api]'"
    ) from e

from . import (
    CronSchedule,
    Instant,
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
    resolution_versions,
    to_url,
)
from .calendar import Cell
from .encode import _parse_cell

app = FastAPI(
    title="intervalclock",
    description="H3 for time: canonical names for intervals and phase classes.",
    version="0.1.0",
)


def _load(text: str):
    text = text.strip()
    if text.upper().startswith("IC1-"):
        return from_url(text)
    if text.startswith("ic1:"):
        return parse(text)
    return _parse_cell(text)


def _payload(x) -> dict:
    out = {"name": name(x), "url": to_url(x), "alias": alias(x), "repr": repr(x)}
    if isinstance(x, Cell):
        sp = cell_span(x)
        out["span"] = {"name": name(sp), "start": str(sp.start), "end": str(sp.end)}
        out["resolution_versions"] = resolution_versions()
    return out


def _err(e: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(e))


@app.get("/v1/now")
def v1_now(zone: str = "UTC"):
    t, err = now()
    return {
        "tai_seconds": str(t.t),
        "uncertainty_seconds": str(err),
        "civil": civil(t, zone).text(),
        "zone": zone,
    }


@app.get("/v1/name")
def v1_name(
    cron: str | None = None,
    period: str | None = None,
    states: int | None = None,
    state: int = 0,
    delta: str = "0",
    hz: str | None = None,
    cell: str | None = None,
    zone: str = "UTC",
):
    try:
        if cron:
            x = from_cron(cron, zone=zone)
        elif period:
            x = phase(rat(period), states or 2, k=state, delta=rat(delta))
        elif hz:
            x = from_frequency(rat(hz))
        elif cell:
            x = _parse_cell(cell if zone == "UTC" else f"{cell}!{zone}")
        else:
            raise ValueError("pass one of cron, period, hz, cell")
        return _payload(x)
    except (ValueError, KeyError) as e:
        raise _err(e)


@app.get("/v1/parse")
def v1_parse(name_: str = Query(alias="name")):
    try:
        return _payload(parse(name_))
    except (ValueError, KeyError) as e:
        raise _err(e)


@app.get("/v1/decode/{url_id}")
def v1_decode(url_id: str):
    try:
        return _payload(from_url(url_id))
    except (ValueError, KeyError) as e:
        raise _err(e)


@app.get("/v1/next")
def v1_next(name_: str = Query(alias="name"), n: int = 1, from_t: str | None = None):
    try:
        x = _load(name_)
        t = Instant(rat(from_t)) if from_t else now()[0]
        out = []
        for _ in range(min(n, 1000)):
            nxt = (cron_next_after(x, t) if isinstance(x, CronSchedule)
                   else next_after(x, t))
            if nxt is None:
                break
            out.append({"start": str(nxt.start), "end": str(nxt.end)})
            t = Instant(nxt.start)
        return {"occurrences": out}
    except (ValueError, KeyError) as e:
        raise _err(e)


@app.get("/v1/contains")
def v1_contains(name_: str = Query(alias="name"), t: str = "0"):
    try:
        return {"contains": _load(name_).contains(rat(t))}
    except (ValueError, KeyError) as e:
        raise _err(e)


@app.get("/v1/alias")
def v1_alias(name_: str = Query(alias="name"), words: int = 4):
    try:
        return {"alias": alias(_load(name_), words=words)}
    except (ValueError, KeyError) as e:
        raise _err(e)
