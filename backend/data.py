"""Load the prepared replay data (SPEC.md §5.4). Load once at startup and treat as read-only."""

from __future__ import annotations

from datetime import datetime

from dataclasses import replace

import numpy as np
import pandas as pd

from backend import config
from backend.config import (
    BAR_MINUTES, DEMO_BETA_END, DEMO_BETA_START, DEMO_CRASH_EURO, DEMO_CRASH_SIGMAS, DEMO_NOISE, DEMO_SEED,
    DEMO_VOL, RHO_WINDOW, SHOCK_TIME,
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
    start, end = _utc(config.REPLAY_START), _utc(config.REPLAY_END)  # read now: --storm demo moves the start
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
    """The demo storm (--storm demo): a fully SIMULATED replay on the real timestamps (SPEC §5.5).

    - Calm: the franc moves with the euro (rS ≈ rF), so every strategy hedges well.
    - Crash bar (the one containing SHOCK_TIME): the franc jumps DEMO_CRASH_SIGMAS × DEMO_VOL, the euro only
      DEMO_CRASH_EURO of that, so the euro hedge fails.
    - Aftermath: the franc follows the euro at a ratio β far from the calm 1.0, drifting from DEMO_BETA_START
      to DEMO_BETA_END. The franc keeps its usual size of moves, so the crash washes out of the score window
      fast; the fast memory tracks β and slower ones lag, so the strategies split about 10 bars after the crash
      and the room comes together on the fast one's chord within about 20 bars of it.
    Seeded (DEMO_SEED), so every Mac builds identical bars.
    """
    shock_t = _utc(SHOCK_TIME)
    bar_len = pd.Timedelta(minutes=BAR_MINUTES).to_pytimedelta()
    shock = next(b.i for b in bars if b.time <= shock_t < b.time + bar_len)
    last = max(b.i for b in bars if b.time <= _utc(config.REPLAY_END))
    rng = np.random.default_rng(DEMO_SEED)
    S, F = bars[0].S, bars[0].F
    out = []
    for b in bars:
        k = b.i - shock
        if k < 0:
            rF = float(rng.normal(0.0, DEMO_VOL))
            rS = rF + float(rng.normal(0.0, DEMO_NOISE * DEMO_VOL))
        elif k == 0:
            rS = DEMO_CRASH_SIGMAS * DEMO_VOL
            rF = DEMO_CRASH_EURO * rS
        else:
            beta = DEMO_BETA_START + (DEMO_BETA_END - DEMO_BETA_START) * min(1.0, (k - 1) / max(1, last - shock))
            rF = float(rng.normal(0.0, DEMO_VOL / beta))  # the franc's moves keep their usual size
            rS = beta * rF + float(rng.normal(0.0, DEMO_NOISE * DEMO_VOL))
        if out:
            S, F = S * np.exp(rS), F * np.exp(rF)
        else:
            rS = rF = 0.0  # row 0 has no return (§5.2)
        out.append(replace(b, S=S, F=F, eurchf=F / S, rS=rS, rF=rF))
    rs = pd.Series([b.rS for b in out]); rf = pd.Series([b.rF for b in out])
    rho = rs.rolling(RHO_WINDOW).corr(rf).fillna(0.0)
    return [replace(b, rho=float(r)) for b, r in zip(out, rho)]
