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



def test_demo_storm_is_repeatable_with_one_clear_crash() -> None:
    from backend.data import demo_bars

    real = load_bars(CSV)
    demo, again = demo_bars(real), demo_bars(real)
    assert demo == again  # every Mac builds identical bars
    assert [b.time for b in demo] == [b.time for b in real] and [b.i for b in demo] == [b.i for b in real]
    shock = next(b for b in demo if b.time <= SHOCK < b.time + timedelta(minutes=BAR_MINUTES))
    assert max(demo, key=lambda b: abs(b.rS)) is shock  # the crash is the biggest franc move


def test_demo_storm_splits_soon_then_converges(monkeypatch) -> None:
    """The point of the demo storm: soon after the crash the starting strategies score in order (fast best),
    and the room then converges on the fast one before the end."""
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
        split.append(sum(scores[shock + 10 : shock + 20]) / 10)
    assert split == sorted(split, reverse=True) and split[0] - split[-1] > 0.05
    monkeypatch.setattr(C, "REPLAY_START", C.DEMO_REPLAY_START)  # as app.py sets these for --storm demo
    monkeypatch.setattr(C, "STEP_FRACTION", C.DEMO_STEP_FRACTION)
    first, _ = replay_range(bars)
    assert shock - first == 22  # the crash comes ~22 s into the replay
    fixed = sim.simulate(bars, 4, C.DEFAULT_SPEED_STEP, loss=None)
    on_fast = 0
    for loss in (0.1, 0.45):
        for seed in range(4):
            s = sim.summarise(sim.simulate(bars, 4, C.DEFAULT_SPEED_STEP, loss=loss, seed=seed), fixed)
            assert s.calm_held
            on_fast += s.final_steps == [0, 0, 0, 0]
    assert on_fast >= 5  # most rooms end on the fast strategy's chord (sim: 6/8 at these losses)
