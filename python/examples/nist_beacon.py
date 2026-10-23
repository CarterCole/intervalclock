"""Name the NIST Randomness Beacon from its publication times.

The beacon (https://beacon.nist.gov) publishes one 512-bit pulse a minute
and has since 2013-09-05. This pulls its recent pulses, runs infer() over
them, and then checks the inferred class against samples from every
leap-second era the beacon has lived through — which is where it gets
interesting, because the beacon is locked to UTC and the physical timeline
is TAI.

    python3 examples/nist_beacon.py                 # ~130 requests
    python3 examples/nist_beacon.py --pulses 30     # fewer
    python3 examples/nist_beacon.py --dump | intervalclock infer - --unix

Stdlib only; fetched pulses are cached under --cache so re-runs are free.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import urllib.request
from fractions import Fraction as F
from pathlib import Path

import intervalclock as ic

V2 = "https://beacon.nist.gov/beacon/2.0"
V1 = "https://beacon.nist.gov/rest/record"

# One probe per TAI−UTC era the beacon has published in. The v1.0 XML API
# (2013–2018) still answers and returns the record at or after the second
# asked for; v2 chain 1 began 2018-07-23, chain 2 on 2022-09-21.
PROBES = [
    ("v1.0", "2014-01-01 (TAI−UTC = 35)", ("v1", 1388534400)),
    ("v1.0", "2016-01-01 (TAI−UTC = 36)", ("v1", 1451606400)),
    ("v1.0", "2018-01-01 (TAI−UTC = 37)", ("v1", 1514764800)),
    ("v2 chain 1", "pulse 1", ("v2", 1, 1)),
    ("v2 chain 2", "pulse 1", ("v2", 2, 1)),
]


def _get(url: str, cache: Path) -> str:
    key = re.sub(r"[^A-Za-z0-9._-]+", "_", url.split("//", 1)[1])
    path = cache / key
    if path.exists():
        return path.read_text()
    # The v1.0 endpoint answers 403 to urllib's default User-Agent.
    req = urllib.request.Request(url, headers={"User-Agent": "intervalclock-example"})
    with urllib.request.urlopen(req, timeout=30) as r:
        text = r.read().decode()
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return text


def v2_pulse(cache: Path, chain, index) -> tuple[F, int, int]:
    """(unix seconds, chainIndex, pulseIndex) of one v2 pulse."""
    p = json.loads(_get(f"{V2}/chain/{chain}/pulse/{index}", cache))["pulse"]
    t = dt.datetime.fromisoformat(p["timeStamp"].replace("Z", "+00:00"))
    return F(int(t.timestamp())) + F(t.microsecond, 10**6), p["chainIndex"], p["pulseIndex"]


def v1_record(cache: Path, unix: int) -> F:
    """Unix seconds of the v1.0 record at or after `unix`."""
    xml = _get(f"{V1}/{unix}", cache)
    return F(int(re.search(r"<timeStamp>(\d+)</timeStamp>", xml).group(1)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pulses", type=int, default=120,
                    help="how many consecutive recent pulses to fold (default 120)")
    ap.add_argument("--resolution", default="1",
                    help="min_resolution in seconds (default 1)")
    ap.add_argument("--cache", default=".nist-beacon-cache",
                    help="directory for fetched pulses")
    ap.add_argument("--dump", action="store_true",
                    help="print the recent pulse times as unix seconds and stop")
    args = ap.parse_args(argv)
    cache = Path(args.cache)

    _, chain, last = v2_pulse(cache, "last", "last")
    recent = [v2_pulse(cache, chain, i)[0]
              for i in range(max(1, last - args.pulses + 1), last + 1)]
    if args.dump:
        print("\n".join(str(u) for u in recent))
        return 0

    tai = [ic.tai_from_unix(u).t for u in recent]
    res = ic.rat(args.resolution)
    results = ic.infer(tai, min_resolution=res, top_k=3)
    print(f"{len(tai)} pulses, chain {chain} #{last - len(tai) + 1}–#{last}, "
          f"min_resolution={res} s\n")
    if not results:
        print("no schedule beats chance")
        return 1
    for r in results:
        print(f"{r.human()}")
        print(f"  name:   {r.cron_text or ic.name(r.cls)}")
        if r.cron_text is None:
            print(f"  url:    {ic.to_url(r.cls)}")
            print(f"  alias:  {ic.alias(r.cls)}")
            print(f"  phase:  φ = {r.cls.phi} s, pulse centre at TAI ≡ "
                  f"{r.detail['offset']} (mod {r.period})")
        print(f"  fit:    R̄={r.score:.6f}  p={r.p_value:.2e}  "
              f"matched={float(r.matched_fraction):.0%}  "
              f"jitter=±{r.phase_jitter:.2g}s")
    top = results[0]
    if top.cron_text is not None:
        return 0

    # Now the history. unix % 60 is 0 for every pulse ever published, so in
    # TAI the pulse sits at a different residue in each leap-second era, and
    # the class above is a Layer-A name that only holds for the current one.
    cls = top.cls
    print(f"\n{'probe':<12} {'':<28} {'UTC':<20} {'unix%60':>7} "
          f"{'TAI−UTC':>8} {'TAI%60':>7}  in {ic.name(cls)}?")
    for src, label, spec in PROBES:
        u = v1_record(cache, spec[1]) if spec[0] == "v1" else v2_pulse(cache, *spec[1:])[0]
        t = ic.tai_from_unix(u).t
        when = dt.datetime.fromtimestamp(int(u), dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{src:<12} {label:<28} {when:<20} {int(u % 60):>7} "
              f"{int(t - u):>8} {int(t % 60):>7}  "
              f"{'inside' if cls.contains(t) else 'OUTSIDE'}")
    print(f"\nThe name that survives leap seconds is the civil one: "
          f"{ic.name(ic.from_cron('* * * * *'))}  (cron '* * * * *', UTC lens)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
