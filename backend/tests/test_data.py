"""Tests for backend/data.py and the committed data/chf2015.csv (SPEC.md §13)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.config import BAR_MINUTES, SHOCK_TIME
from backend.data import load_bars, replay_range

CSV = str(Path(__file__).resolve().parents[2] / "data" / "chf2015.csv")
SHOCK = datetime.fromisoformat(SHOCK_TIME)


def test_loads_the_committed_csv() -> None:
    bars = load_bars(CSV)
    assert 1400 <= len(bars) <= 1700
    assert [b.i for b in bars] == list(range(len(bars)))
    assert all(a.time < b.time for a, b in zip(bars, bars[1:]))
    assert all(b.time.tzinfo is not None and b.time.utcoffset().total_seconds() == 0 for b in bars)


def test_replay_range_is_inside_the_data() -> None:
    bars = load_bars(CSV)
    first, last = replay_range(bars)
    assert 0 < first < last < len(bars)
    assert bars[first].time == datetime(2015, 1, 12, tzinfo=timezone.utc)
    assert bars[last].time == datetime(2015, 1, 23, 21, 45, tzinfo=timezone.utc)


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
