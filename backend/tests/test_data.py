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
