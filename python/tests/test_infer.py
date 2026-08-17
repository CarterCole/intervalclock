import datetime as dt
import random
from datetime import datetime, timezone
from fractions import Fraction as F
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from intervalclock import (
    CronSchedule,
    PhaseClass,
    from_cron,
    infer,
    phase,
    tai_from_unix,
    to_cron,
)


def _tai(local: datetime) -> F:
    """A local wall-clock datetime → TAI seconds since epoch."""
    return tai_from_unix(F(int(local.timestamp()))).t


def _weekly(zone: str, n: int, start=datetime(2026, 1, 6, 9, 0)) -> list[F]:
    """n consecutive Tuesdays at 09:00 local — crosses the March DST change."""
    tz = ZoneInfo(zone)
    return [_tai((start.replace(tzinfo=tz) + dt.timedelta(weeks=i)).astimezone(tz))
            for i in range(n)]


# --- rational schedules -----------------------------------------------------


def test_finds_a_twenty_minute_grid_through_jitter():
    rnd = random.Random(0)
    ts = [F(k * 1200 + rnd.randint(-30, 30)) for k in range(50)]
    top = infer(ts, min_resolution=60)[0]
    assert isinstance(top.cls, PhaseClass)
    assert top.period == 1200
    assert top.matched_fraction >= F(9, 10)
    assert top.human().startswith("every 20 min")


def test_the_named_phase_lands_on_the_resolution_grid():
    ts = [F(k * 1200 + 300) for k in range(30)]
    top = infer(ts, min_resolution=60)[0]
    # The *center* of the pulse is what the resolution constrains; the pulse
    # is one quantum wide and centered on it.
    center = (top.cls.phi + top.cls.w / 2) % top.cls.period
    assert (center / 60).denominator == 1
    assert center == 300


def test_subharmonics_of_the_fundamental_are_suppressed():
    ts = [F(k * 1200) for k in range(40)]
    periods = [r.period for r in infer(ts, min_resolution=60, top_k=10)]
    assert 1200 in periods
    # Folding at 600 or 400 concentrates just as tightly, but leaves half or
    # two-thirds of the slots empty.
    assert 600 not in periods and 400 not in periods


def test_an_exact_period_is_named_exactly():
    ts = [F(k) * F(1, 3) for k in range(60)]
    top = infer(ts, min_resolution=F(1, 12))[0]
    assert top.period == F(1, 3)


def test_scan_finds_a_period_no_human_would_pick():
    # 777 s is in neither the nice lattice nor anyone's crontab. The scan
    # must land on the fundamental, not on one of its divisors — each of
    # which folds these events just as perfectly.
    ts = [F(k * 777) for k in range(30)]
    top = infer(ts, min_resolution=60, candidates="scan")[0]
    assert top.period == 777
    assert infer(ts, min_resolution=60)[0].period == 777


def test_explicit_candidates_bypass_the_lattice():
    ts = [F(k * 7) for k in range(40)]
    top = infer(ts, min_resolution=1, candidates=[7, 11, 13])[0]
    assert top.period == 7


# --- calendar schedules -----------------------------------------------------


def test_weekly_local_schedule_survives_a_dst_transition():
    zone = "America/New_York"
    results = infer(_weekly(zone, 20), min_resolution=60, zone=zone)
    top = results[0]
    assert isinstance(top.cls, CronSchedule)
    assert top.cls == from_cron("0 9 * * 2", zone=zone)
    assert to_cron(top.cls) == "0 9 * * 2"
    assert top.human() == "every Tuesday 09:00"
    assert top.matched_fraction == 1


def test_a_tai_anchored_weekly_rhythm_stays_a_phase_class():
    # Exactly 604800 s apart in TAI, so it drifts against local clocks. The
    # civil fold smears; the rational one is the truer name.
    ts = [F(1785592800 + k * 604800) for k in range(20)]
    top = infer(ts, min_resolution=60, zone="America/New_York")[0]
    assert isinstance(top.cls, PhaseClass)
    assert top.period == 604800


def test_daily_schedule_emits_cron():
    base = int(datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp())
    ts = [tai_from_unix(F(base + d * 86400 + 14 * 3600 + 30 * 60)).t
          for d in range(40)]
    top = infer(ts, min_resolution=60)[0]
    assert to_cron(top.cls) == "30 14 * * *"
    assert top.kind == "day"


def test_monthly_on_the_first_folds_through_the_lens():
    ts = [tai_from_unix(F(int(datetime(2025 + m // 12, m % 12 + 1, 1,
                                       tzinfo=timezone.utc).timestamp()))).t
          for m in range(14)]
    top = infer(ts, min_resolution=60)[0]
    assert to_cron(top.cls) == "0 0 1 * *"
    assert top.human() == "monthly on day 1 00:00"


def test_a_daily_rhythm_does_not_masquerade_as_weekly():
    base = int(datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp())
    ts = [tai_from_unix(F(base + d * 86400 + 9 * 3600)).t for d in range(40)]
    kinds = [r.kind for r in infer(ts, min_resolution=60, top_k=10)]
    assert kinds[0] == "day"
    assert "isoweek" not in kinds  # every day is not "every Tuesday"


# --- honesty ----------------------------------------------------------------


def test_noise_yields_no_schedule():
    rnd = random.Random(7)
    ts = sorted({F(rnd.randrange(0, 60000)) for _ in range(60)})
    assert infer(ts, min_resolution=60) == []


def test_too_few_events_cannot_buy_significance():
    # Four events on a perfect grid: a real pattern, but four points is not
    # evidence once the candidate count is accounted for.
    assert infer([F(0), F(1200), F(2400), F(3600)], min_resolution=60) == []


def test_span_caps_the_longest_detectable_period():
    ts = [F(k * 600) for k in range(8)]  # span 4200 s
    assert all(r.period is None or r.period <= 1400 for r in
               infer(ts, min_resolution=60, top_k=10))


def test_results_are_deterministic():
    rnd = random.Random(3)
    ts = [F(k * 900 + rnd.randint(-20, 20)) for k in range(40)]
    assert infer(ts, min_resolution=60) == infer(ts, min_resolution=60)


@pytest.mark.parametrize("bad,kwargs", [
    ([F(0), F(1)], {}),                      # too few events
    ([F(5)] * 8, {}),                        # zero span (dedup leaves one)
    ([F(k) for k in range(10)], {"min_resolution": 0}),
    ([F(k) for k in range(10)], {"min_resolution": -1}),
])
def test_validation(bad, kwargs):
    with pytest.raises(ValueError):
        infer(bad, **kwargs)


def test_unknown_candidate_mode_is_rejected():
    with pytest.raises(ValueError):
        infer([F(k * 60) for k in range(20)], candidates="magic")


# --- properties -------------------------------------------------------------


@given(
    # Periods at least two quanta long — a period one quantum wide has no
    # room for a pulse, which infer() refuses to pretend otherwise about.
    P=st.sampled_from([F(300), F(900), F(1200), F(3600)]),
    offset=st.integers(0, 20),
    n=st.integers(12, 40),
)
@settings(max_examples=25, deadline=None)
def test_property_generated_schedules_are_recovered(P, offset, n):
    res = F(60)
    phi = (offset * res) % P
    ts = [phi + k * P for k in range(n)]
    top = infer(ts, min_resolution=res)[0]
    assert top.period == P
    center = (top.cls.phi + top.cls.w / 2) % P
    assert center == phi
    assert top.matched_fraction == 1
    # The emitted class really is a Φ over this period.
    assert top.cls.w * top.cls.m == P
    assert top.cls == phase(top.cls.w, top.cls.m, phi=top.cls.phi)


# --- CLI --------------------------------------------------------------------


def test_cli_infer(tmp_path, capsys):
    from intervalclock.cli import main

    f = tmp_path / "stamps.txt"
    f.write_text("\n".join(str(k * 1200) for k in range(30)))
    assert main(["infer", str(f), "--resolution", "60"]) == 0
    out = capsys.readouterr().out
    assert "every 20 min" in out
    assert "ic1:c:" in out


def test_cli_infer_reports_no_schedule(tmp_path, capsys):
    from intervalclock.cli import main

    rnd = random.Random(11)
    f = tmp_path / "noise.txt"
    f.write_text("\n".join(str(rnd.randrange(0, 60000)) for _ in range(60)))
    assert main(["infer", str(f), "--resolution", "60"]) == 1
    assert "no schedule" in capsys.readouterr().out
