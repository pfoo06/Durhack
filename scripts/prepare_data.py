"""Build data/chf2015.csv from Dukascopy 1-minute bars (SPEC.md §5.2).

Usage:
    python scripts/prepare_data.py data/raw/ data/chf2015.csv

Download the raw files first (one per pair, into data/raw/):
    npx -y dukascopy-node -i <pair> -from 2015-01-01 -to 2015-02-01 -t m1 -f csv
for <pair> in eurchf, eurgbp and gbpchf.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import BAR_MINUTES, REPLAY_END, REPLAY_START, RHO_WINDOW, SHOCK_TIME  # noqa: E402

PAIRS = ("eurchf", "eurgbp", "gbpchf")
DATA_START = pd.Timestamp("2015-01-02T00:00Z")  # 1 January is a market holiday (thin, flat filler)
DATA_END = pd.Timestamp("2015-01-24T00:00Z")  # the end of the replay week
MARKET_OPEN_HOUR = 22  # FX trades Sunday 22:00 UTC to Friday 22:00 UTC (§5.3)


def find_raw_file(raw_dir: Path, pair: str) -> Path:
    matches = sorted(raw_dir.rglob(f"{pair}-m1-*.csv"))
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly one {pair}-m1-*.csv under {raw_dir}, found {len(matches)}")
    return matches[0]


def read_closes(path: Path) -> pd.Series:
    """Dukascopy CSV: header `timestamp,open,high,low,close`, timestamp in ms since the epoch, UTC."""
    df = pd.read_csv(path)
    times = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return pd.Series(df["close"].to_numpy(dtype=float), index=times).sort_index()


def market_open(index: pd.DatetimeIndex) -> np.ndarray:
    """True for minutes when the FX market is open. Dukascopy repeats the last price when it's closed."""
    day = index.day_of_week  # Monday = 0, Sunday = 6
    hour = index.hour
    return (day <= 3) | ((day == 4) & (hour < MARKET_OPEN_HOUR)) | ((day == 6) & (hour >= MARKET_OPEN_HOUR))


def to_bars(closes: pd.Series) -> pd.Series:
    """Keep open-market minutes in the data range, then take the last close in each bar."""
    closes = closes[(closes.index >= DATA_START) & (closes.index < DATA_END)]
    closes = closes[market_open(closes.index)]
    return closes.resample(f"{BAR_MINUTES}min", label="left", closed="left").last()


def build(raw_dir: Path) -> pd.DataFrame:
    bars = {pair: to_bars(read_closes(find_raw_file(raw_dir, pair))) for pair in PAIRS}
    # Inner join and drop any bar where a pair is missing. Never forward-fill (§5.2 step 3).
    df = pd.concat(bars, axis=1, join="inner").dropna()

    out = pd.DataFrame(index=df.index)
    out["S"] = 1.0 / df["gbpchf"]  # GBP per CHF
    out["F"] = df["eurgbp"]  # GBP per EUR
    out["eurchf"] = df["eurchf"]
    out["rS"] = np.log(out["S"] / out["S"].shift(1)).fillna(0.0)
    out["rF"] = np.log(out["F"] / out["F"].shift(1)).fillna(0.0)
    out["rho"] = out["rS"].rolling(RHO_WINDOW).corr(out["rF"]).fillna(0.0)
    return out


def check(out: pd.DataFrame) -> None:
    """§5.2 step 8. Prints each check and fails loudly if one doesn't hold."""
    times = out.index
    replay_start = pd.Timestamp(REPLAY_START)
    last_replay_bar = pd.Timestamp(REPLAY_END) - pd.Timedelta(minutes=BAR_MINUTES)
    shock = pd.Timestamp(SHOCK_TIME)
    shock_bar = shock.floor(f"{BAR_MINUTES}min")

    print(f"rows: {len(out)} ({times[0]} to {times[-1]})")
    assert 1400 <= len(out) <= 1700, "row count outside 1,400–1,700"
    assert times[0].date().isoformat() == "2015-01-02", "first row isn't on 2 January"
    assert (times <= replay_start).any(), "no row on or before REPLAY_START"
    assert (times >= last_replay_bar).any(), "no bar covering the end of the replay"

    assert shock_bar in times, "no bar contains SHOCK_TIME"
    shock_rS = out.loc[shock_bar, "rS"]
    print(f"shock bar {shock_bar}: rS = {shock_rS:.4f}")
    assert abs(shock_rS) > 0.03, "shock bar |rS| isn't above 0.03"

    calm = out[times.normalize() != shock.normalize()]
    mismatch = ((calm["eurchf"] - calm["F"] / calm["S"]).abs() / calm["eurchf"]).max()
    print(f"largest |eurchf − F/S| / eurchf outside 15 January: {mismatch:.5f}")
    assert mismatch < 0.005, "S and F don't reproduce EUR/CHF: check which way round they are"

    biggest = out["rS"].abs().nlargest(5)
    print("largest five |rS|:")
    for t, v in biggest.items():
        print(f"  {t}  {v:.4f}")
    assert all(t.normalize() == shock.normalize() for t in biggest.index), "a top-five |rS| isn't on 15 January"


def write(out: pd.DataFrame, path: Path) -> None:
    csv = out.reset_index(names="time")
    csv["time"] = csv["time"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    path.parent.mkdir(parents=True, exist_ok=True)
    csv.to_csv(path, index=False, float_format="%.17g", columns=["time", "S", "F", "eurchf", "rS", "rF", "rho"])
    print(f"wrote {path}")


def main(argv: list[str]) -> None:
    if len(argv) != 3:
        raise SystemExit(__doc__)
    out = build(Path(argv[1]))
    check(out)
    write(out, Path(argv[2]))


if __name__ == "__main__":
    main(sys.argv)
