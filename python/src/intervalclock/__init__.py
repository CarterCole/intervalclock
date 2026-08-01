"""intervalclock — H3 for time.

Canonical, globally computable names for every interval and periodic phase
class on a shared timeline: calendar cells, any cron schedule, any rational
period ("every 1/3 second", any Hz), and — in the protocol, implemented in
v2 — FFT components extended forever. See protocol/PROTOCOL.md.
"""

from .calendar import (  # noqa: F401
    Cell,
    NonexistentTime,
    cell,
    cell_span,
    civil,
    resolution_versions,
)
from .core import (  # noqa: F401
    ALWAYS,
    NEVER,
    PhaseClass,
    PSet,
    Span,
    Windowed,
    complement,
    complexity,
    contains,
    from_frequency,
    intersect,
    next_after,
    occurrences,
    phase,
    prev_before,
    pset,
    reduce,
    span,
    state_at,
    subset,
    union,
    windowed,
)
from .cron import CronSchedule, cron_next_after, from_cron, to_cron  # noqa: F401
from .encode import (  # noqa: F401
    ReservedTypeError,
    decode,
    encode,
    from_url,
    name,
    parse,
    to_url,
)
from .lattice import (  # noqa: F401
    children,
    decimal_grid_class,
    decimal_states,
    harmonics,
    parent,
    subharmonics,
)
from .rat import hz_of_period, period_of_hz, rat  # noqa: F401
from .timescale import (  # noqa: F401
    Instant,
    RangeError,
    now,
    tai_from_unix,
    unix_from_tai,
)
from .ticker import every, iter_ticks, ticks  # noqa: F401
from .words import Registry, alias, full_alias  # noqa: F401

__version__ = "0.1.0"
