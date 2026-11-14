"""Load the prepared replay data (SPEC.md §5.4). Load once at startup and treat as read-only."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from backend.config import REPLAY_END, REPLAY_START
from backend.contracts import Bar


def _utc(stamp: str) -> datetime:
    return pd.Timestamp(stamp).tz_convert("UTC").to_pydatetime()


def load_bars(path: str = "data/chf2015.csv") -> list[Bar]:
    """Read data/chf2015.csv into one Bar per row, with `i` equal to the row number."""
    df = pd.read_csv(path)
    times = pd.to_datetime(df["time"], utc=True)
    return [
        Bar(
            i=i,
            time=t.to_pydatetime(),
            S=float(row.S),
            F=float(row.F),
            eurchf=float(row.eurchf),
            rS=float(row.rS),
            rF=float(row.rF),
            rho=float(row.rho),
        )
        for i, (t, row) in enumerate(zip(times, df.itertuples(index=False)))
    ]


def replay_range(bars: list[Bar]) -> tuple[int, int]:
    """(first bar index with time ≥ REPLAY_START, last bar index with time ≤ REPLAY_END)."""
    start, end = _utc(REPLAY_START), _utc(REPLAY_END)
    first = next(b.i for b in bars if b.time >= start)
    last = max(b.i for b in bars if b.time <= end)
    return first, last


def history_payload(bars: list[Bar]) -> dict:
    """The §10.2 `history` message: the replay window, with S and F rebased to 100 at its first bar."""
    first, last = replay_range(bars)
    base_S, base_F = bars[first].S, bars[first].F
    return {
        "type": "history",
        "bars": [
            {
                "i": b.i,
                "time": b.time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "S": 100.0 * b.S / base_S,
                "F": 100.0 * b.F / base_F,
                "rho": b.rho,
            }
            for b in bars[first : last + 1]
        ],
    }
