# intervalclock

The Python reference implementation of the [IntervalClock
protocol](https://github.com/CarterCole/intervalclock/blob/main/protocol/PROTOCOL.md)
— an "H3 for time": canonical, globally computable names for every interval
and every periodic phase class.

```bash
pip install -e '.[api,dev]'
```

```python
from fractions import Fraction as F
import intervalclock as ic

c = ic.phase(F(1, 3), 3, k=2)      # Φ[w=1/3s · m=3 · φ=2/3s] (state 2 of 3)
ic.name(c)                          # 'ic1:c:w=1/3;m=3;phi=2/3'
ic.from_cron("*/5 * * * *")         # equivalent crons share one canonical ID
ic.cell_span(ic.cell("day", 2016, 12, 31)).duration   # Fraction(86401, 1)

for pulse in ic.iter_ticks(c):      # events on the shared epoch-anchored lattice
    print(pulse)
```

CLI: `intervalclock now | name | parse | next | contains | alias`.
REST API: `uvicorn intervalclock.api:app` (needs the `[api]` extra).

See the [repository README](https://github.com/CarterCole/intervalclock)
for the full project — protocol, library, and site.
