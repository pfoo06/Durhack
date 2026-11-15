"""Load the prepared replay data (SPEC.md §5.4). Load once at startup and treat as read-only."""

from __future__ import annotations

from datetime import datetime

from dataclasses import replace

import numpy as np
import pandas as pd

from backend.config import (
    BAR_MINUTES, DEMO_BETA, DEMO_BETA_PERIOD_BARS, DEMO_BETA_SWING, DEMO_NOISE, DEMO_SEED, DEMO_VOL0, DEMO_VOL_MIN, DEMO_VOL_TAU_BARS, REPLAY_END,
    REPLAY_START, RHO_WINDOW, SHOCK_TIME,
)
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


def demo_bars(bars: list[Bar]) -> list[Bar]:
    """The demo storm (--storm demo): the real bars up to and including the crash, then a SIMULATED aftermath.

    After the crash the franc follows the euro again at a new ratio (rS = β·rF plus a little noise), on euro
    volatility that starts high and dies away. β keeps shifting between DEMO_BETA ± DEMO_BETA_SWING every half
    DEMO_BETA_PERIOD_BARS: the fast-memory strategy re-learns each shift within a bar or two and the slower ones
    always lag, so the strategies split clearly and the others keep a reason to follow the fast one until they
    all play its chord and score like it.
    Deterministic (DEMO_SEED), so every Mac builds identical bars. Times and indexes are the real ones.
    """
    shock_t = _utc(SHOCK_TIME)
    bar_len = pd.Timedelta(minutes=BAR_MINUTES).to_pytimedelta()
    shock = next(b.i for b in bars if b.time <= shock_t < b.time + bar_len)
    rng = np.random.default_rng(DEMO_SEED)
    out = list(bars[: shock + 1])
    S, F = bars[shock].S, bars[shock].F
    after = bars[shock + 1 :]
    for k, b in enumerate(after):
        vol = DEMO_VOL0 * np.exp(-k / DEMO_VOL_TAU_BARS) + DEMO_VOL_MIN
        beta = DEMO_BETA + (DEMO_BETA_SWING if (k // (DEMO_BETA_PERIOD_BARS // 2)) % 2 == 0 else -DEMO_BETA_SWING)
        rF = float(rng.normal(0.0, vol))
        rS = float(beta * rF + rng.normal(0.0, DEMO_NOISE * vol))
        S, F = S * np.exp(rS), F * np.exp(rF)
        out.append(replace(b, S=S, F=F, eurchf=F / S, rS=rS, rF=rF))
    rs = pd.Series([b.rS for b in out]); rf = pd.Series([b.rF for b in out])
    rho = rs.rolling(RHO_WINDOW).corr(rf).fillna(0.0)
    return [replace(b, rho=float(r)) if b.i > shock else b for b, r in zip(out, rho)]
