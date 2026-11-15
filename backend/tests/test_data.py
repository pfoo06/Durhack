"""Tests for backend/data.py and the committed data/chf2015.csv (SPEC.md §13)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.config import BAR_MINUTES, SHOCK_TIME
from backend.data import load_bars, replay_range

CSV = str(Path(__file__).resolve().parents[2] / "data" / "chf2015.csv")
SHOCK = datetime.fromisoformat(SHOCK_TIME)


def test_loads_the_committed_csv() -> None:
    bars = load_bars(CSV)
    expected = (22 + 3 * 120) * 60 // BAR_MINUTES  # open-market hours in the data, as bars
    assert abs(len(bars) - expected) <= 0.02 * expected
    assert [b.i for b in bars] == list(range(len(bars)))
    assert all(a.time < b.time for a, b in zip(bars, bars[1:]))
    assert all(b.time.tzinfo is not None and b.time.utcoffset().total_seconds() == 0 for b in bars)


def test_replay_range_is_inside_the_data() -> None:
    bars = load_bars(CSV)
    first, last = replay_range(bars)
    assert 0 < first < last < len(bars)
    assert bars[first].time == datetime(2015, 1, 12, tzinfo=timezone.utc)
    assert bars[last].time == datetime(2015, 1, 22, 10, tzinfo=timezone.utc)  # REPLAY_END: before the ECB announcement


def test_shock_bar_is_large() -> None:
    bars = load_bars(CSV)
    bar_length = timedelta(minutes=BAR_MINUTES)
    shock = next(b for b in bars if b.time <= SHOCK < b.time + bar_length)
    assert abs(shock.rS) > 0.03


def test_no_weekend_bars() -> None:
    """Dukascopy repeats prices while the market is shut; prepare_data.py must drop those minutes."""
    for b in load_bars(CSV):
        day, hour = b.time.weekday(), b.time.hour  # Monday = 0, Sunday = 6
        assert day != 5, f"Saturday bar at {b.time}"
        assert not (day == 4 and hour >= 22), f"Friday-night bar at {b.time}"
        assert not (day == 6 and hour < 22), f"Sunday-daytime bar at {b.time}"


def test_history_payload_is_the_rebased_replay_window() -> None:
    from backend.data import history_payload

    bars = load_bars(CSV)
    first, last = replay_range(bars)
    payload = history_payload(bars)
    rows = payload["bars"]
    assert payload["type"] == "history"
    assert len(rows) == last - first + 1
    assert rows[0]["i"] == first and rows[-1]["i"] == last
    assert rows[0]["time"] == "2015-01-12T00:00:00Z"
    assert rows[0]["S"] == pytest.approx(100.0) and rows[0]["F"] == pytest.approx(100.0)
    assert set(rows[0]) == {"i", "time", "S", "F", "rho"}
    assert max(r["S"] for r in rows) > 110  # the franc jumped against the pound in the storm



def test_demo_storm_keeps_the_real_crash_and_is_repeatable() -> None:
    from backend.data import demo_bars

    real = load_bars(CSV)
    demo, again = demo_bars(real), demo_bars(real)
    shock = next(b.i for b in real if b.time <= SHOCK < b.time + timedelta(minutes=BAR_MINUTES))
    assert demo[: shock + 1] == real[: shock + 1]  # the calm and the crash are real
    assert demo == again  # every Mac builds identical bars
    assert len(demo) == len(real) and [b.time for b in demo] == [b.time for b in real]
    assert any(d.rS != r.rS for d, r in zip(demo[shock + 1 :], real[shock + 1 :]))


def test_demo_storm_splits_then_converges() -> None:
    """The point of the demo storm: right after the crash leaves the score window the four starting strategies
    score clearly differently (fast best), and the room then converges on the fast one."""
    from backend import config as C, sim
    from backend.data import demo_bars
    from backend.finance import Effectiveness, Hedger

    bars = demo_bars(load_bars(CSV))
    shock = next(b.i for b in bars if b.time <= SHOCK < b.time + timedelta(minutes=BAR_MINUTES))
    split = []
    for dial in C.START_DIALS:
        h, e, scores = Hedger(C.H_MIN_BARS * 2**dial), Effectiveness(), []
        for b in bars:
            _, rH = h.update(b)
            scores.append(e.update(b.rS, rH))
        split.append(sum(scores[shock + 25 : shock + 37]) / 12)
    assert split == sorted(split, reverse=True) and split[0] - split[-1] > 0.5
    run = sim.simulate(bars, 4, C.DEFAULT_SPEED_STEP, loss=0.1, seed=0)
    assert sim.summarise(run, sim.simulate(bars, 4, C.DEFAULT_SPEED_STEP, loss=None)).final_steps == [0, 0, 0, 0]
